"""
smoke_test.py
==============

Live "is this schema still reachable and shaped correctly" check —
complementary to diff_catalog.py's structural diff, NOT a replacement
for it. See this module's role in cli.py's --check-drift flow: a green
smoke-test verdict can only ever ADD confidence to an otherwise-clean
structural diff. It can never override a structural BREAKING verdict —
a required field silently vanishing from a request body is breaking
regardless of whether the live endpoint happens to still accept
requests without it.

Fixes four real gaps found in an earlier proposed version of this idea
(see conversation) rather than reproducing them:

  1. A 200/201/204 status is NOT unconditionally healthy — some vendor
     APIs return HTTP success with an error payload in the body (e.g.
     {"status": "error", "message": "Invalid API Key"}). _looks_like_error_body()
     inspects the body for this specific anti-pattern before trusting a
     success status. This is a HEURISTIC over arbitrary vendor JSON
     shapes, not a guarantee — documented as such below, not oversold.

  2. 404 is NOT a reliable "dead route" signal for any endpoint with a
     path parameter (DELETE /contacts/{id}, GET /orders/{id}, etc.) — a
     mock ID like "test" will correctly 404 on a perfectly healthy
     endpoint. Only a 404 on a NO-path-param (collection-level) endpoint
     is treated as a confident break; path-parameterized 404s are
     INCONCLUSIVE, not BROKEN.

  3. 429 and 5xx get an actual retry-with-backoff path instead of
     falling through undefined or straight to a false "broken" verdict —
     a rate-limited batch run over hundreds of vendors must not flood
     the human review queue with false breaks on the busiest, most-used
     integrations.

  4. Timeouts/connection errors also retry before concluding anything,
     rather than treating one transient network blip as a confirmed
     schema break.
"""

from __future__ import annotations

import json
import random
import string
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

# Deliberately GET-only by default. A write method (POST/PUT/PATCH/DELETE)
# is never safe to fire with a mock payload against a real vendor endpoint —
# see the module docstring in the original proposal for why, which this
# keeps rather than relaxes. Raise this only with a specific, reviewed
# reason for a specific schema, never as a blanket default.
SAFE_METHODS = {"GET"}

RETRYABLE_STATUS = {429, 502, 503, 504}
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 2

# Verdicts, in the order they should be preferred when combining with a
# structural diff result (see cli.py integration) — HEALTHY is the only
# one that can ever ADD confidence; every other verdict is neutral-to-
# cautionary and should never promote an otherwise-risky change.
HEALTHY = "HEALTHY"
NEEDS_TUNING = "NEEDS_TUNING"
BROKEN = "BROKEN"
INCONCLUSIVE = "INCONCLUSIVE"
SKIPPED = "SKIPPED"


@dataclass
class SmokeTestResult:
    verdict: str
    reason: str
    status_code: Optional[int] = None
    attempts: int = 0


def _looks_like_error_body(body_text: str) -> bool:
    """
    Heuristic check for the "200 OK with an error payload" anti-pattern.
    Only catches a FEW common shapes ({"error": ...}, {"status": "error"},
    {"success": false}) — arbitrary vendor JSON can express failure in
    infinitely many other ways this won't catch. Treat a False return as
    "didn't detect an error," not "confirmed this is a real success" —
    the caller already has other signals (the status code itself) doing
    the heavier lifting.
    """
    if not body_text:
        return False
    try:
        data = json.loads(body_text)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(data, dict):
        return False

    lowered = {str(k).lower(): v for k, v in data.items()}
    if lowered.get("error"):
        return True
    if str(lowered.get("status", "")).lower() in ("error", "failed", "failure"):
        return True
    if lowered.get("success") is False:
        return True
    return False


def classify_response(status_code: int, body_text: str, has_path_params: bool,
                       attempt: int, max_attempts: int = MAX_ATTEMPTS) -> tuple[str, str]:
    """
    Pure function, no network — the actual classification logic, kept
    separate from run_smoke_test() specifically so it's unit-testable
    without ever making a real HTTP call. Returns (verdict, reason);
    verdict is one of the module-level constants above, OR the literal
    string "RETRY" (a signal to the caller's retry loop, not a final
    verdict — never returned to code outside this module).
    """
    if status_code in RETRYABLE_STATUS:
        if attempt < max_attempts:
            return ("RETRY", f"{status_code} — retrying (attempt {attempt}/{max_attempts})")
        return (INCONCLUSIVE, f"{status_code} after {max_attempts} attempts — "
                               f"rate-limited or busy, not a verdict on the schema itself")

    if status_code in (401, 403):
        return (HEALTHY, f"{status_code} — route exists, auth header shape accepted by the server")

    if status_code in (200, 201, 204):
        if _looks_like_error_body(body_text):
            return (BROKEN, f"{status_code} but response body looks like an error payload "
                             f"(200-with-error-body anti-pattern)")
        return (HEALTHY, f"{status_code} — public/successful route, mock payload accepted")

    if status_code in (400, 422):
        return (NEEDS_TUNING, f"{status_code} — route and auth reached the server, "
                               f"but the mock payload shape was rejected")

    if status_code == 404:
        if has_path_params:
            return (INCONCLUSIVE, "404 on a path-parameterized endpoint — indistinguishable "
                                   "from 'no such resource with this mock ID' without a real record")
        return (BROKEN, "404 on a collection-level endpoint (no path params) — route no longer exists")

    if status_code >= 500:
        if attempt < max_attempts:
            return ("RETRY", f"{status_code} — retrying (attempt {attempt}/{max_attempts})")
        return (INCONCLUSIVE, f"{status_code} after {max_attempts} attempts — "
                               f"could be a transient vendor outage, not necessarily a schema break")

    return (INCONCLUSIVE, f"unrecognized status {status_code} — no classification rule matches")


def _has_path_params(url: str) -> bool:
    return "{" in url and "}" in url


def _fake_credential() -> str:
    """
    A random, provably-never-valid string, generated fresh per run.
    Deliberately does NOT read any $env.* value, even the schema's own
    configured default — an accidentally-real credential sitting in the
    environment for other purposes must never leak into a smoke test,
    which by design fires against production vendor endpoints.
    """
    return "smoketest_" + "".join(random.choices(string.ascii_letters + string.digits, k=32))


def run_smoke_test(schema: dict, timeout: float = 5.0, max_attempts: int = MAX_ATTEMPTS) -> SmokeTestResult:
    """
    Fires ONE schema's request with a fake credential and no real payload
    values (every {{DataType=...}} placeholder in class/body is left as a
    harmless dummy — see _dummy_value below), classifying the response.

    Returns SKIPPED without making any network call for anything other
    than a SAFE_METHODS method — this is the actual enforcement point for
    "never fire against DELETE or a financial POST," not just a comment.
    """
    method = (schema.get("method") or "GET").upper()
    if method not in SAFE_METHODS:
        return SmokeTestResult(SKIPPED, f"method={method} is not in SAFE_METHODS — never fired")

    url = schema.get("url", "")
    has_path_params = _has_path_params(url)
    # Path params get a harmless placeholder value so the URL is at least
    # well-formed — NOT a real resource ID, which is exactly why a 404 on
    # a path-parameterized endpoint is INCONCLUSIVE rather than BROKEN
    # above, not a bug in this substitution.
    for match in list(schema.get("class", {}).keys()):
        if f"{{{match}}}" in url:
            url = url.replace(f"{{{match}}}", "smoketest")

    headers = dict(schema.get("headers", {}))
    fake_cred = _fake_credential()
    for k, v in list(headers.items()):
        if isinstance(v, str) and "{authorization}" in v:
            headers[k] = v.replace("{authorization}", fake_cred)

    attempt = 0
    while True:
        attempt += 1
        try:
            req = urllib.request.Request(url, method=method, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < max_attempts:
                backoff = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                print(f"      ⏳ connection error ({e}), retrying in {backoff}s (attempt {attempt}/{max_attempts})...")
                time.sleep(backoff)
                continue
            return SmokeTestResult(INCONCLUSIVE, f"connection error after {max_attempts} attempts: {e}", attempts=attempt)

        verdict, reason = classify_response(status, body, has_path_params, attempt, max_attempts)
        if verdict == "RETRY":
            backoff = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            print(f"      ⏳ {reason}, sleeping {backoff}s...")
            time.sleep(backoff)
            continue
        return SmokeTestResult(verdict, reason, status_code=status, attempts=attempt)