"""
piper_executor.py
==================

OPTIONAL. build_schema() returns a BuiltRequest that may contain inert
{{$cred.<app>.<token_name>}} markers instead of live secrets (see the
design note in piper_sdk.py). Something has to resolve those markers and
fire the request — this module is a ready-made implementation of that
"something," ported from the engine's own core.py + rategovernor.py:

  - Credential resolution happens HERE, at dispatch time only, via your
    CredentialStore. A resolved token exists only inside this function
    call, in memory, on a copy of the request — never in whatever
    build_schema() returned to your API layer.
  - Per-app rate limiting (RateGovernor) so hammering one slow integration
    doesn't starve or ban another tenant's calls to the same app.
  - Retry with exponential backoff on timeouts, 429s, and 5xxs
    (tenacity, same policy as UniversalDispatcher.fire in core.py).

If you already have your own executor/queue, you don't need this file —
just follow the same contract: crawl for {{$cred.<app>.<token>}}, resolve
via your own credential lookup, substitute, then fire.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_result, retry_if_exception_type

from stretis import BuiltRequest, CredentialStore, AuthorizationRequired

# Not anchored: piper_sdk.py's _finalize_request() now substitutes class
# params (including the '_authorization' credential slot) into strings like
# "Bearer {_authorization}", so the marker is frequently embedded inside a
# larger header value rather than being the whole string.
CRED_MARKER = re.compile(r"\{\{\$cred\.([\w\-]+)\.([\w\-]+)\}\}")


class DispatchError(Exception):
    pass


@dataclass
class DispatchResult:
    status: str  # "success" | "error"
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Per-app rate limiting — direct port of rategovernor.py, unchanged behavior.
# One shared instance per process; every app name sharing a base (e.g.
# "hubspot.contacts" / "hubspot.deals") queues behind the same lock so a
# burst against one action of an app can't starve another action of the
# same app past its rate limit.
# ---------------------------------------------------------------------------

class RateGovernor:
    _instance = None
    _locks: Dict[str, asyncio.Lock] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RateGovernor, cls).__new__(cls)
        return cls._instance

    async def yield_control(self, app_name: str, limit_per_sec: float) -> None:
        base_app = app_name.split(".")[0]
        if base_app not in self._locks:
            self._locks[base_app] = asyncio.Lock()
        async with self._locks[base_app]:
            await asyncio.sleep(1.0 / limit_per_sec)


class PiperExecutor:
    def __init__(self, store: CredentialStore):
        self.store = store
        self._governor = RateGovernor()

    # -- credential resolution (mirrors core.py's add_cred / get_valid_access_token) --

    async def _resolve_bundle(self, tenant_id: str, app: str) -> Optional[dict]:
        bundle = self.store.get_bundle(tenant_id, app)
        # Support sync OR async CredentialStore implementations transparently.
        if asyncio.iscoroutine(bundle):
            bundle = await bundle
        if not bundle:
            return None

        # Only attempt a refresh when there's a refresh_token to use. A
        # static/BYO token (e.g. a personal access token seeded via
        # connect_with_static_token(), never obtained through OAuth) has
        # no refresh_token and typically no expires_at either. Treating a
        # missing expires_at as "already expired" — bundle.get("expires_at", 0)
        # defaults to 0, which is always <= now+30 — used to route every
        # static token into _refresh() on every single call. _refresh()
        # correctly refuses without a refresh_token and returns None,
        # which then surfaced as "this tenant isn't connected" even
        # though the static token was perfectly valid the whole time.
        if bundle.get("refresh_token") and bundle.get("expires_at", 0) <= time.time() + 30:
            refreshed = await self._refresh(tenant_id, app, bundle)
            if refreshed:
                bundle = refreshed
            # If refresh failed (network hiccup, revoked refresh token),
            # fall through and use the last-known bundle rather than
            # discarding a possibly-still-valid access_token outright.

        return bundle

    async def _refresh(self, tenant_id: str, app: str, bundle: dict) -> Optional[dict]:
        if not bundle.get("refresh_token"):
            return None
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(bundle["token_url"], data={
                "grant_type": "refresh_token",
                "refresh_token": bundle["refresh_token"],
                "client_id": bundle.get("client_id"),
                "client_secret": bundle.get("client_secret"),
            })
        if resp.status_code != 200:
            # 🛠️ DIAGNOSTIC: this used to fail silently, so a refresh that
            # was ALWAYS failing (bad client_secret, revoked refresh_token,
            # wrong token_url) looked identical to "no refresh needed yet" —
            # the caller only ever saw the eventual 401 from the real API
            # call, which reads exactly like plain token expiration.
            print(
                f"[piper_executor] refresh FAILED for tenant={tenant_id} app={app} "
                f"status={resp.status_code} body={resp.text[:500]!r}",
                flush=True,
            )
            return None

        tokens = resp.json()
        bundle["access_token"] = tokens.get("access_token", bundle["access_token"])
        if "refresh_token" in tokens:
            bundle["refresh_token"] = tokens["refresh_token"]
        bundle["expires_at"] = time.time() + tokens.get("expires_in", 3600)

        result = self.store.save_bundle(tenant_id, app, bundle)
        if asyncio.iscoroutine(result):
            await result
        return bundle

    async def _hydrate(self, tenant_id: str, request: BuiltRequest) -> BuiltRequest:
        """Returns a NEW BuiltRequest with every {{$cred...}} marker resolved,
        at any depth in headers or body. Never mutates the one you passed in —
        the caller's copy stays inert."""
        bundles_needed: Dict[str, Optional[dict]] = {}

        async def resolve_string(value: str) -> str:
            if not CRED_MARKER.search(value):
                return value

            # Resolve every distinct app referenced in this string first
            # (a value normally references just one, but this stays
            # correct if it ever references more than one).
            for app in set(m.group(1) for m in CRED_MARKER.finditer(value)):
                if app not in bundles_needed:
                    bundles_needed[app] = await self._resolve_bundle(tenant_id, app)
                if bundles_needed[app] is None:
                    raise AuthorizationRequired(app=app, authorization_url="")

            def _sub(m: "re.Match") -> str:
                app = m.group(1)
                return bundles_needed[app]["access_token"]

            return CRED_MARKER.sub(_sub, value)

        # 🛠️ FIX: was a single flat pass over each dict's top-level values
        # only. A {{$cred...}} marker nested more than one level deep in the
        # body (e.g. body["auth"]["token"]) silently passed through
        # unresolved. Recurses through dicts and lists at any depth now.
        async def deep_resolve(value: Any) -> Any:
            if isinstance(value, str):
                return await resolve_string(value)
            if isinstance(value, dict):
                return {k: await deep_resolve(v) for k, v in value.items()}
            if isinstance(value, list):
                return [await deep_resolve(v) for v in value]
            return value

        resolved_headers = await deep_resolve(dict(request.headers))
        resolved_body = await deep_resolve(request.body) if request.body is not None else request.body

        return BuiltRequest(
            method=request.method, url=request.url,
            headers=resolved_headers, body=resolved_body,
        )

    # -- firing, with retry + rate limiting (mirrors core.py's UniversalDispatcher) --

    @staticmethod
    def _is_retry_needed(response) -> bool:
        if response is None:
            return True
        return response.status_code in (429, 500, 502, 503, 504)

    async def dispatch(
        self,
        tenant_id: str,
        app: str,
        request: BuiltRequest,
        timeout: int = 10,
        max_attempts: int = 3,
        min_backoff: int = 2,
        max_backoff: int = 10,
        rate_limit: float = 5,
    ) -> DispatchResult:
        """
        Resolves any {{$cred...}} markers, applies this app's rate limit,
        fires with retry on timeouts/429/5xx, and returns the result.
        Raises AuthorizationRequired if a credential marker can't be
        resolved (tenant disconnected between build_schema and dispatch —
        rare, but handle it the same way you handle it from build_schema).
        """
        hydrated = await self._hydrate(tenant_id, request)
        await self._governor.yield_control(app, rate_limit)

        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=1, min=min_backoff, max=max_backoff),
            retry=(retry_if_result(self._is_retry_needed) | retry_if_exception_type(httpx.RequestError)),
            reraise=True,
        )
        async def _execute():
            async with httpx.AsyncClient(timeout=timeout) as client:
                return await client.request(
                    method=hydrated.method,
                    url=hydrated.url,
                    headers=hydrated.headers,
                    json=hydrated.body or {},
                )

        try:
            response = await _execute()
            response.raise_for_status()
            data = response.json() if response.text.strip() else {"status": "success"}
            return DispatchResult(status="success", data=data)
        except Exception as e:
            return DispatchResult(status="error", error=str(e))