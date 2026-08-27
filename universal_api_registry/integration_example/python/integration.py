"""
integrations.py
================

This is the whole lifecycle a platform owner wires up ONCE to embed
app integrations into their product: setup, UI-facing routes, hydration,
and execution. Drop this next to your existing FastAPI app and mount it.

Five moving parts, each owned by a different piece of your stack:

  1. SETUP        — one PiperSDK instance, one CredentialStore.
  2. UI SIDE       — 3 read-only routes your frontend calls to render the
                      node picker and the dynamic input form. No mapping
                      layer: whatever get_input_form() returns is exactly
                      what your frontend renders and exactly what it
                      submits back.
  3. AUTH          — the one hosted OAuth callback route (skip this
                      entirely for apps you connect via a static token).
  4. HYDRATION     — build_schema(): user's form answers -> a fireable
                      BuiltRequest, safe to log/queue/return because the
                      credential is still an inert marker at this point.
  5. EXECUTION     — PiperExecutor.dispatch(): resolves the marker and
                      fires, in memory, at the last possible moment.
"""

import os

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from fastapi.responses import HTMLResponse, FileResponse

from stretis import (
    AuthorizationRequired,
    MissingFieldsError,
    PiperSDK,
    SchemaNotFound,
    AppCredentials
)
from stretis import SqliteCredentialStore # import PostgresCredentialStore for postgres or CredentialStore
from stretis import get_crypto_engine

# ---------------------------------------------------------------------------
# 1. SETUP — do this once, at process start.
# ---------------------------------------------------------------------------

key = "T9wkTOczZN4uGjMNuCJKl4EzdoWAtuRQL8CLCm60kFw=" # os.environ.get("PIPER_SECRET_KEY")

# 🛠️ FIX: get_crypto_engine(key)'s return value was being discarded here,
# then SqliteCredentialStore was constructed without it at all — a
# TypeError at startup, since crypto_engine has no default. CryptoEngine
# holds no global/singleton state (just self.fernet), so there was no
# way the discarded call could have had any effect — it had to be
# captured and passed in explicitly.
crypto_engine = get_crypto_engine(key)

# SqliteCredentialStore: zero infra, one file, good for day one. Swap for
# your own CredentialStore against Postgres/Mongo/a secrets manager later —
# it's five methods (see CredentialStore in piper_sdk.py), and nothing
# below this line changes when you do.

credential_store = SqliteCredentialStore(
    db_path=os.environ.get("PIPER_DB_PATH", "credentials.db"),
    crypto_engine=crypto_engine,
)

hubspot_app_cred = AppCredentials(
    client_id="4d4ef8a9-b12e-43ca-a68b-29695edda560",
    client_secret="0a669fa8-8bab-4c4e-869a-9fd5c32f27db"
)

credential_store.save_app_credentials(app="hubspot", credentials=hubspot_app_cred)

sdk = PiperSDK(
    store=credential_store,
    # Your own publicly reachable callback URL, registered with each
    # provider's OAuth app config. Only apps you actually connect via
    # OAuth need this — a static-token app never redirects anywhere.
)



router = APIRouter()

@router.get("/", response_class=FileResponse)
def index():
    file_path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    return FileResponse(file_path)

# ---------------------------------------------------------------------------
# 2. UI SIDE — your frontend calls these to build the node picker and the
#    dynamic form. Pure reads: no tenant state, nothing here can raise
#    AuthorizationRequired.
# ---------------------------------------------------------------------------

@router.get("/apps")
def list_apps():
    """One card per app — name, description, icon, category."""
    return [vars(a) for a in sdk.list_app_catalog()]


@router.get("/apps/{app_name}/nodes")
def list_nodes(app_name: str):
    """One card per action within that app — the node-picker entries."""
    return [vars(n) for n in sdk.list_nodes(app=app_name)]


@router.get("/apps/{app_name}/nodes/{action}/form")
def get_node_form(app_name: str, action: str):
    """
    The fields for a node's config panel, once the user has picked one.
    Render this straight off `fields` — each leaf's `key` is exactly what
    your submit handler should put back into field_values. No renaming,
    no lookup table on your side.
    """
    form = sdk.get_input_form(app=app_name, action=action)
    return {
        "display_name": form.display_name,
        "description": form.description,
        "requires_auth": form.requires_auth,
        "fields": [_field_to_json(f) for f in form.fields],
    }


def _field_to_json(field) -> dict:
    return {
        "key": field.key,
        "label": field.label,
        "input_type": field.input_type,
        "description": field.description,
        "required": field.required,
        "fields": [_field_to_json(f) for f in field.fields] if field.fields else None,
    }


# ---------------------------------------------------------------------------
# 3. AUTH — the one route needed for apps connected via OAuth. Skip this
#    whole section for apps you connect with a pasted-in static token
#    (see connect_with_static_token below) — REDIRECT_URI in that app's
#    provider config never needs to point here.
# ---------------------------------------------------------------------------

@router.get("/connect/{app_name}")
def start_connect(app_name: str, tenant_id: str = Query(...)):
    """Frontend redirects here when the user clicks "Connect <app>"."""
    try:
        auth_url = sdk.get_authorization_url(tenant_id=tenant_id, app=app_name)
    except SchemaNotFound:
        raise HTTPException(404, f"'{app_name}' has no OAuth config.")
    return RedirectResponse(auth_url)


@router.get("/callback/{app_name}")
def oauth_callback(app_name: str, code: str = Query(...), state: str = Query(...)):
    """
    Handles OAuth callbacks for ANY app by capturing the app_name 
    directly from the URL path.
    """
    tenant_id = state  # round-tripped through get_authorization_url()
    
    try:
        # Pass the dynamic app_name to the SDK
        sdk.complete_authorization(tenant_id=tenant_id, app=app_name, code=code)
    except Exception as e:
        raise HTTPException(400, f"Could not complete authorization for {app_name}: {e}")
    
    # Redirect back to your frontend dashboard with success status
    return RedirectResponse(url=f"/?success=connected&app={app_name}")

@router.get("/connect/{app_name}/status")
def connect_status(app_name: str, tenant_id: str = Query(...)):
    return {"app": app_name, "connected": sdk.is_connected(tenant_id, app_name)}


def connect_with_static_token(tenant_id: str, app: str, token: str) -> None:
    """
    Alternative to the OAuth dance above, for apps your user authenticates
    to with a pasted-in API key / personal access token instead. Seeds the
    SAME CredentialStore the OAuth flow writes to, so build_schema() and
    the executor treat it identically — no refresh_token means the
    executor's near-expiry refresh check never fires for it.
    """
    credential_store.save_bundle(tenant_id, app, {"access_token": token})


# ---------------------------------------------------------------------------
# 4 + 5. HYDRATION then EXECUTION — the actual "run this node" call.
#    Two separate steps on purpose: build_schema()'s output is safe to
#    persist/queue/retry because the credential in it is still just a
#    marker; only dispatch() ever touches the real token, in memory, right
#    before firing.
# ---------------------------------------------------------------------------

@router.post("/tenants/{tenant_id}/run/{app_name}/{action}")
async def run_action(tenant_id: str, app_name: str, action: str, field_values: dict):
    """
    field_values is exactly what the frontend collected from the form at
    /apps/{app}/nodes/{action}/form — same keys, unmodified, no mapping.
    """

    print(f"field_value:            {field_values}", flush=True)
    # -- 4. HYDRATION --
    try:
        request_spec = sdk.build_schema(
            tenant_id=tenant_id, app=app_name, action=action, field_values=field_values,
        )
    except AuthorizationRequired as e:
        # Tenant hasn't connected this app yet. Hand the frontend the URL
        # to redirect to — nothing was fired, nothing to roll back.
        return {"status": "needs_authorization", "authorization_url": e.authorization_url}
    except MissingFieldsError as e:
        # Required, non-credential fields weren't filled in.
        return {"status": "invalid", "missing_fields": e.missing}

    # request_spec is safe to log, queue, or hand to a background worker
    # here — it still contains only an inert {{$cred...}} marker, never a
    # live token. This is a genuine seam: nothing stops you inserting a
    # queue.enqueue(request_spec) here and calling dispatch() later, in a
    # completely different process, as long as it has the same store.

    
    try:
        result = await sdk.dispatch(tenant_id=tenant_id, app=app_name, request=request_spec)
    except AuthorizationRequired as e:
        return {"status": "needs_authorization", "authorization_url": e.authorization_url}

    return {"status": result.status, "data": result.data, "error": result.error}


# Setting up Hosted OAuth
# Because the SDK is designed to be embedded into your own platform infrastructure 
# rather than running a local server, you manage the OAuth entry and callback 
# routes directly inside your existing FastAPI application.  
# The flow consists of three core endpoints (already defined above, in
# section 3 — start_connect / oauth_callback / connect_status):
# Start Connect (GET /connect/{app_name}): Redirects the end user's browser to the
#  third-party provider's consent screen.  
# Callback Handler (GET /oauth/callback): Receives the authorization code, exchanges 
# it securely for tokens on the backend, and saves them to the tenant's vault.  
# Status Check (GET /connect/{app_name}/status): Allows your frontend to poll 
# whether the app is successfully connected.
#
# 🛠️ FIX: this section used to redefine all three routes a second time,
# nearly verbatim — FastAPI/Starlette matches the FIRST registered route,
# so this block was dead, unreachable code. Removed rather than kept as a
# second copy that could silently drift from the real one in section 3.


# ---------------------------------------------------------------------------
# Mount it.
# ---------------------------------------------------------------------------
app = FastAPI()
app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("integration:app", host="127.0.0.1", port=8080, reload=True)