"""

piper_sdk.py

============



Public SDK surface for third-party automation-platform owners.



Two calls are the whole contract:



    form   = sdk.get_input_form(app="hubspot", action="update_contact")

    ready  = sdk.build_schema(tenant_id="acct_123", app="hubspot",

                               action="update_contact",

                               field_values={"contactId": "42", "email": "a@b.com"})



`ready` is a plain {"method", "url", "headers", "body"} dict the platform

hands to *its own* HTTP executor. This SDK never makes the outbound call

itself — platform owners keep control of retries, sandboxing, logging.



Design notes (why it's shaped this way)

----------------------------------------

1. converter.py already emits, per endpoint, a `metadata.fields` block

   (label/input_type/description/required, recursive for nested objects).

   That block IS the input form. get_input_form() does not reinterpret

   the DSL at all — it just reads that block back out. No drift between

   "what the form shows" and "what actually exists in the schema" is

   possible, because they're the same JSON.



2. Filling the schema reuses the existing placeholder engine

   (tools.crawler / missing_field / replace_place_value_v3) rather than

   reimplementing substitution logic. build_schema() is a thin

   orchestration layer over it, not a parallel implementation.



3. auth_manager.py's flow (spin up a local uvicorn server on :8080,

   open a browser) only works for a single desktop user running the

   engine on their own machine. A platform owner is hosting many

   tenants behind their own domain, so that flow is replaced here with

   two plain functions:

     - get_authorization_url(tenant_id, app)   -> URL to redirect the

       end user to (platform's frontend does the redirect)

     - complete_authorization(tenant_id, app, code) -> called from the

       platform's OWN hosted callback route with the `code` query

       param it received; does the token exchange + vault save.

   Nothing here binds a port or owns a server process.



4. If a required field has no value and no static default, but its

   Default is `$env.<TOKEN>` (an OAuth-backed credential), build_schema

   does NOT crash or print-and-wait like the original engine did. It

   raises AuthorizationRequired so the platform can catch it and show

   a "Connect <app>" button, pointed at get_authorization_url().



5. Credential storage is a PLUGGABLE interface (CredentialStore below),

   not a hardcoded database. This SDK is meant to be embedded into

   whatever an indie platform owner already runs — their own Postgres,

   their own Mongo, their own users table, a managed secrets service.

   Forcing everyone onto ContextDB's schema and one Fernet key would

   mean the SDK owns a piece of infra it has no business owning.

   Implement CredentialStore against your own stack (a handful of

   methods) and pass it in; InMemoryCredentialStore is provided only

   for local dev/tests, and PostgresCredentialStore only as a reference

   implementation, not the default.

"""



from __future__ import annotations



import glob

import json

import os

import re

import time

import threading

import sqlite3

import urllib.parse as _urlparse

from abc import ABC, abstractmethod

from dataclasses import dataclass, field

from typing import Any, Dict, List, Optional



import requests



from .tools import (

    crawler,

    missing_field,

    replace_place_value_v3,

    retrieve_file,

)



# 🛠️ FIX: was r"Default\s*=\s*([\$!\.\w\d_\-\s]+)" — missing ':' and '/'

# from the allowed character class, which silently TRUNCATED any scope

# string containing them: 'attachments:read attachments:write tasks:read'

# (real Asana scopes — every one is colon-namespaced) captured only

# 'attachments', stopping dead at the first colon. Google's scopes are

# full URLs ('https://www.googleapis.com/auth/calendar'), so '/' needed

# the same fix. This regex backs BOTH the main placeholder-resolution

# loop below AND get_authorization_url's scope extraction — one fix,

# not two separate patches that could drift apart.

DEFAULT_REGEX = r"Default\s*=\s*([\$!\.\w\d_\-\s:\/]+)"

# 🛠️ NEW: converter.py now stamps every path/query/header placeholder
# with 'Required=True'/'Required=False'. Absence of this tag entirely
# (older, already-generated schemas that predate this fix) falls
# through to the exact original behavior — no Default= means required,
# full stop — so nothing already in production silently starts
# behaving differently. Only an EXPLICIT 'Required=False' unlocks the
# new omit-if-blank path below.
REQUIRED_REGEX = r"Required\s*=\s*(True|False|true|false)"





# ---------------------------------------------------------------------------

# Credential storage — the one piece every adopter plugs in themselves

# ---------------------------------------------------------------------------


@dataclass

class AppCredentials:

    """

    One app's OAuth CLIENT_ID/CLIENT_SECRET — the platform owner's OWN

    registration with the third-party service (e.g. "our platform's

    Asana app"), set up ONCE per app and shared across every tenant that

    connects through it. This is deliberately a separate concept from a

    tenant's token bundle: one CLIENT_ID exists per app regardless of

    whether 1 or 10,000 tenants have connected; a token bundle exists

    per (tenant, app) pair. Conflating the two into one storage shape

    would mean either duplicating the same CLIENT_ID/SECRET into every

    tenant's bundle (drift risk if it's ever rotated — now you're

    updating N rows instead of 1) or awkwardly overloading tenant_id

    with a sentinel value to mean "the app-level record." A distinct

    type, distinct methods, distinct storage key.

    """

    client_id: str

    client_secret: str





class CredentialStore(ABC):

    """

    Everything the SDK needs to know about where a tenant's third-party

    OAuth tokens live, AND where each app's own OAuth registration

    (CLIENT_ID/CLIENT_SECRET) lives — two different things, kept as two

    different method pairs below rather than merged into one shape.

    Implement this against whatever you already run.



    Encryption-at-rest, if any, is YOUR implementation's responsibility —

    the SDK only ever sees plain token bundle dicts / AppCredentials in

    memory, never a ciphertext format it has to agree with another

    language's SDK about.

    """



    # -- per-tenant token storage ---------------------------------------



    @abstractmethod

    def get_bundle(self, tenant_id: str, app: str) -> Optional[Dict[str, Any]]:

        """Return the stored token bundle for this tenant+app, or None if not connected."""



    @abstractmethod

    def save_bundle(self, tenant_id: str, app: str, bundle: Dict[str, Any]) -> None:

        """Persist (create or overwrite) the token bundle for this tenant+app."""



    # -- per-app OAuth registration — NOT tenant-scoped ------------------

    # Required, not optional: without these, get_authorization_url() and

    # complete_authorization() have no CLIENT_ID/CLIENT_SECRET to use at

    # all — every OAuth flow for every tenant would be broken the same

    # way, not a degraded-but-functional edge case. Making these

    # abstractmethod forces every implementation (including your own) to

    # explicitly decide how app-level secrets are stored, the same way

    # get_bundle/save_bundle already force a decision for tenant tokens,

    # rather than silently falling back to a no-op that produces the

    # exact '{{DataType=str}}'-leaking-into-the-URL bug this replaces.


    def get_app_credentials(self, app: str) -> Optional[AppCredentials]:

        """Return this app's CLIENT_ID/CLIENT_SECRET, or None if the

        platform owner hasn't registered one for this app yet."""


    def save_app_credentials(self, app: str, credentials: AppCredentials) -> None:

        """Persist (create or overwrite) this app's OAuth registration.

        Called by the platform owner during setup, not during an

        end-user's connect flow — there's no tenant_id here on purpose."""



    def record_pending_authorization(self, tenant_id: str, app: str, auth_url: str) -> None:

        """

        Optional hook: called when get_authorization_url() issues a new

        redirect, e.g. for a support dashboard of "who's mid-connect."

        No-op by default — override only if you want this.

        """

        return None



class EncryptionManager(ABC):
    """
    Implement this against whatever encryption infrastructure your
    platform already uses — a local password-derived key (see
    LocalPasswordEncryptionManager for a reference implementation), a KMS/
    HSM, a secrets manager, or per-tenant keys — and pass an instance of it
    into PiperSDK the same way you pass a CredentialStore.
 
    Both methods are synchronous by design, matching CredentialStore's own
    convention — the SDK wraps sync calls in asyncio.to_thread(...)
    wherever it invokes them from async code, so implementations (even
    ones making a real network call to a KMS) don't need to write async
    code themselves.
 
    Bundles handed to CredentialStore.save_bundle are plain dicts, not
    pre-encrypted strings — if you want values encrypted at rest, encrypt
    each value yourself (via this interface) before building the bundle
    dict, and decrypt after get_bundle returns it. EncryptionManager and
    CredentialStore are deliberately independent — a CredentialStore
    implementation is free to ignore encryption entirely (see
    SqliteCredentialStore's own "tokens stored in plaintext" warning) or to
    call an EncryptionManager internally; the SDK doesn't assume one wraps
    the other.
    """
 
    @abstractmethod
    def encrypt_value(self, plaintext: str) -> str:
        """Returns ciphertext safe to persist. Must round-trip through
        decrypt() to recover the exact original plaintext."""
        raise NotImplementedError
 
    @abstractmethod
    def decrypt_value(self, ciphertext: str) -> str:
        """Inverse of encrypt(). Implementations should raise a clear,
        specific exception (not a bare Exception) when ciphertext can't be
        decrypted — e.g. wrong key, corrupted data — so callers can
        distinguish "credentials are wrong" from "data is corrupted"
        rather than catching everything the same way."""
        raise NotImplementedError
 


class InMemoryCredentialStore(CredentialStore):

    """For local development and tests ONLY — tokens vanish on restart."""



    def __init__(self):

        self._store: Dict[tuple, Dict[str, Any]] = {}

        self._app_creds: Dict[str, AppCredentials] = {}



    def get_bundle(self, tenant_id: str, app: str) -> Optional[Dict[str, Any]]:

        return self._store.get((tenant_id, app))



    def save_bundle(self, tenant_id: str, app: str, bundle: Dict[str, Any]) -> None:

        self._store[(tenant_id, app)] = bundle



    def get_app_credentials(self, app: str) -> Optional[AppCredentials]:

        return self._app_creds.get(app)



    def save_app_credentials(self, app: str, credentials: AppCredentials) -> None:

        self._app_creds[app] = credentials





class PostgresCredentialStore(CredentialStore):

    """

    Reference implementation wrapping the engine's own ContextDB

    (`piper_vault` table) and a Fernet-compatible crypto_engine, for

    platform owners who are fine reusing the same database the engine

    itself runs on. This is an OPTION, not the SDK's assumed backend —

    most adopters should write their own CredentialStore against

    whatever database/secrets manager they already have.

    """



    def __init__(self, db, crypto_engine):

        self._db = db

        self._crypto_engine = crypto_engine

        self._encrypt_value = crypto_engine.encrypt_value

        self._decrypt_value = crypto_engine.decrypt_value



    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS piper_credentials (
                        tenant_id  TEXT NOT NULL,
                        app        TEXT NOT NULL,
                        bundle     TEXT NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        PRIMARY KEY (tenant_id, app)
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS piper_app_credentials (
                        app           TEXT PRIMARY KEY,
                        client_id     TEXT NOT NULL,
                        client_secret TEXT NOT NULL,
                        updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                """)
            conn.commit()
        finally:
            conn.close()
 
    def get_bundle(self, tenant_id: str, app: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT bundle FROM piper_credentials WHERE tenant_id = %s AND app = %s",
                    (tenant_id, app),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        return json.loads(self._decrypt_value(row[0])) if row else None
 
    def save_bundle(self, tenant_id: str, app: str, bundle: Dict[str, Any]) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO piper_credentials (tenant_id, app, bundle, updated_at)
                    VALUES (%s, %s, %s, now())
                    ON CONFLICT (tenant_id, app) DO UPDATE SET
                        bundle = EXCLUDED.bundle, updated_at = EXCLUDED.updated_at
                    """,
                    (tenant_id, app, self._encrypt_value(json.dumps(bundle))),
                )
            conn.commit()
        finally:
            conn.close()
 
    def get_app_credentials(self, app: str) -> Optional[AppCredentials]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT client_id, client_secret FROM piper_app_credentials WHERE app = %s",
                    (app,),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return AppCredentials(client_id=row[0], client_secret=self._decrypt_value(row[1]))
 
    def save_app_credentials(self, app: str, credentials: AppCredentials) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO piper_app_credentials (app, client_id, client_secret, updated_at)
                    VALUES (%s, %s, %s, now())
                    ON CONFLICT (app) DO UPDATE SET
                        client_id = EXCLUDED.client_id,
                        client_secret = EXCLUDED.client_secret,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (app, credentials.client_id, self._encrypt_value(credentials.client_secret)),
                )
            conn.commit()
        finally:
            conn.close()
 
    def record_pending_authorization(self, tenant_id: str, app: str, auth_url: str) -> None:
        # No dedicated table for this in the self-contained version —
        # override if you want a "who's mid-connect" dashboard; the old
        # ContextDB.create_intervention() call is gone along with the
        # rest of the ContextDB dependency.
        return None
 

class SqliteCredentialStore(CredentialStore):
    def __init__(self, db_path: str, crypto_engine):
        self._db_path = db_path
        # sqlite3 connections aren't safe to share across threads; a lock
        # around each short-lived connection is simpler than a connection
        # pool for what's meant to be a lightweight starting point.
        self._crypto_engine = crypto_engine
        
        self._encrypt_value = crypto_engine.encrypt_value

        self._decrypt_value = crypto_engine.decrypt_value

        self._lock = threading.Lock()

        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            # Table for per-tenant OAuth token bundles
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS credentials (
                    tenant_id  TEXT NOT NULL,
                    app        TEXT NOT NULL,
                    bundle     TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (tenant_id, app)
                )
                """
            )
            # Table for app-level OAuth registrations (Client ID & Secret)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_credentials (
                    app           TEXT PRIMARY KEY,
                    client_id     TEXT NOT NULL,
                    client_secret TEXT NOT NULL,
                    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )

    def get_bundle(self, tenant_id: str, app: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT bundle FROM credentials WHERE tenant_id = ? AND app = ?",
                (tenant_id, app),
            ).fetchone()

        return json.loads(self._decrypt_value(row[0])) if row else None

    def save_bundle(self, tenant_id: str, app: str, bundle: Dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO credentials (tenant_id, app, bundle, updated_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT (tenant_id, app) DO UPDATE SET
                    bundle = excluded.bundle,
                    updated_at = excluded.updated_at
                """,
                (tenant_id, app, self._encrypt_value(json.dumps(bundle))),
            )

    def get_app_credentials(self, app: str) -> Optional[AppCredentials]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT client_id, client_secret FROM app_credentials WHERE app = ?",
                (app,),
            ).fetchone()
        if not row:
            return None
        return AppCredentials(client_id=row[0], client_secret=self._decrypt_value(row[1]))

    def save_app_credentials(self, app: str, credentials: AppCredentials) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO app_credentials (app, client_id, client_secret, updated_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT (app) DO UPDATE SET
                    client_id = excluded.client_id,
                    client_secret = excluded.client_secret,
                    updated_at = excluded.updated_at
                """,
                (app, credentials.client_id, self._encrypt_value(credentials.client_secret)),
            )

    def record_pending_authorization(self, tenant_id: str, app: str, auth_url: str) -> None:
        # No-op, same as the CredentialStore base default — override this
        # if you want a "who's mid-connect" dashboard.
        return None


# ---------------------------------------------------------------------------

# Public result types

# ---------------------------------------------------------------------------



@dataclass

class FormField:

    key: str                     # full dotted path incl. namespace, e.g. "body.properties.email"

    label: str

    input_type: str              # text | number | checkbox | tags | group

    description: str

    required: bool

    fields: Optional[List["FormField"]] = None  # populated for input_type == "group"





@dataclass

class InputForm:

    app: str

    action: str

    display_name: str

    description: str

    icon_url: str

    requires_auth: bool

    fields: List[FormField] = field(default_factory=list)





@dataclass

class AppSummary:

    """One entry per connected app — for an app picker/grid, from _meta.json."""

    app: str

    display_name: str

    description: str

    category: str

    favicon_url: str

    logo_background_color: str





@dataclass

class NodeSummary:

    """

    One entry per app+action — for a node picker (the per-action cards you

    see in a workflow canvas: "HubSpot: Update Contact", etc). Deliberately

    lightweight — no `fields` here. Call get_input_form(app, action) once

    the user actually picks this node, to get the fields for its own panel.

    """

    app: str

    action: str

    display_name: str

    description: str

    icon_url: str

    color: str

    category: str

    node_type: str

    requires_auth: bool





@dataclass

class BuiltRequest:

    method: str

    url: str

    headers: Dict[str, Any]

    body: Optional[Dict[str, Any]]





class AuthorizationRequired(Exception):

    """

    Raised by build_schema() when a required credential (an $env.* backed

    field, e.g. an OAuth token) is missing for this tenant. Catch this and

    redirect the user to `authorization_url`.

    """

    def __init__(self, app: str, authorization_url: str):

        self.app = app

        self.authorization_url = authorization_url

        super().__init__(f"'{app}' is not connected for this tenant yet.")





class MissingFieldsError(Exception):

    """Raised when required, non-credential fields are missing from field_values."""

    def __init__(self, missing: List[str]):

        self.missing = missing

        super().__init__(f"Missing required fields: {', '.join(missing)}")





class SchemaNotFound(Exception):

    pass





class AppNotConfigured(Exception):

    """

    Raised when an app HAS an OAuth schema (_auth.json exists) but the

    platform owner hasn't registered its CLIENT_ID/CLIENT_SECRET via

    CredentialStore.save_app_credentials() yet. Deliberately distinct

    from SchemaNotFound: that means "this app doesn't support OAuth at

    all / the schema file is missing" — a catalog problem. This means

    "the schema exists and OAuth is possible, but nobody's set it up

    yet" — a platform-owner setup step, not a missing-file problem, and

    worth telling apart when deciding how to react to the error.

    """

    def __init__(self, app: str):

        self.app = app

        super().__init__(

            f"App '{app}' has an OAuth schema but no CLIENT_ID/CLIENT_SECRET "

            f"registered. Call store.save_app_credentials('{app}', AppCredentials(...)) first."

        )





# ---------------------------------------------------------------------------

# SDK

# ---------------------------------------------------------------------------



class PiperSDK:

    def __init__(

        self,

        store: CredentialStore,

        schemas_root: Optional[str] = None,

        redirect_base_url: str = "http://localhost:8080/callback",

    ):

        """

        store: your CredentialStore implementation (see above) —

                      InMemoryCredentialStore for local dev,

                      PostgresCredentialStore if you're fine sharing the

                      engine's own DB, or your own implementation against

                      whatever you already run.

        schemas_root: root dir of the schema tree

                      (schemas/<category>/<app>/<action>.json). Optional —

                      if omitted, auto-detects the installed `stretis-schemas`

                      package (`pip install stretis-schemas`) so a fresh

                      install works with zero config. Pass this explicitly

                      only if you're running your own catalog, a private

                      fork, or pinning a specific stretis-schemas version's

                      unpacked path.

        redirect_base_url: the PLATFORM's own hosted callback URL, i.e.

                      wherever `complete_authorization` gets called from.

                      This is NOT a URL this SDK serves.

        """

        self.schemas_root = schemas_root or self._autodetect_schemas_root()

        self.store = store

        self.redirect_base_url = redirect_base_url

        self._schema_index: Dict[tuple, str] = {}

        # Not constructed until dispatch() is actually called — see
        # _get_executor()'s docstring for why this matters.
        self._executor = None

        self._build_index()



    @staticmethod
    
    def _autodetect_schemas_root() -> str:
        schema_path = os.path.abspath("./schemas")
        if os.path.exists(schema_path):
            return schema_path
        raise SchemaNotFound(
            f"Local schema directory not found at {schema_path}. "
            "Pass schemas_root explicitly if your schemas are located elsewhere."
        )
    


    # -- discovery -----------------------------------------------------



    def _build_index(self):

        """Maps (app, action) -> schema file path by walking schemas_root once."""

        self._schema_index = {}

        pattern = os.path.join(self.schemas_root, "*", "*", "*.json")

        for path in glob.glob(pattern):

            fname = os.path.basename(path)

            # 🛠️ FIX: "_index.json" was missing from this exclusion set —

            # converter.py's write_schema_index() writes one per app

            # folder, and without this it was silently indexed as if it

            # were a real callable action: (app, "_index") -> pointing at

            # a file that's a schema LIST, not a schema. "_meta.json" and

            # "_auth.json" (the current, single-underscore-prefixed,

            # non-app-prefixed name — see _auth_config_path below) stay

            # excluded the same way.

            if fname in ("_meta.json", "_index.json") or fname.endswith("_auth.json"):

                continue

            app = os.path.basename(os.path.dirname(path))

            action = fname[:-len(".json")]

            self._schema_index[(app, action)] = path



    def list_apps(self) -> List[str]:

        return sorted({app for app, _ in self._schema_index})



    def list_actions(self, app: str) -> List[str]:

        return sorted(a for a_app, a in self._schema_index if a_app == app)



    def _schema_path(self, app: str, action: str) -> str:

        path = self._schema_index.get((app, action))

        if not path:

            self._build_index()  # picks up schemas added since startup

            path = self._schema_index.get((app, action))

        if not path:

            raise SchemaNotFound(f"No schema for {app}.{action}")

        return path



    def _redirect_uri_for(self, app: str) -> str:
        """
        The per-app OAuth callback URL — self.redirect_base_url with this
        app's name appended as a path segment (e.g.
        'https://platform.com/callback' + '/test_app'), matching a
        callback route shaped like '/callback/{app_name}' that reads
        app_name straight from the path rather than a query param.

        get_authorization_url() and complete_authorization() BOTH call
        this rather than reading self.redirect_base_url directly, and
        both need to compute the exact same value for the exact same app
        — an OAuth provider's token exchange validates that the
        redirect_uri sent at that step matches the one used for the
        original authorization redirect byte-for-byte; if these two ever
        drifted apart (e.g. one appending the app name and the other
        not), every token exchange would fail with a redirect_uri
        mismatch error from the provider, not from anything on this end.
        One shared method is what keeps that impossible rather than
        merely "correct as long as nobody edits one call site without the
        other."
        """
        return f"{self.redirect_base_url.rstrip('/')}/{app}"

    def _auth_config_path(self, app: str) -> Optional[str]:

        """

        🛠️ FIX: was f"{app}_auth.json" — that matched converter.py's OLD

        auth-file naming. converter.py now writes a bare "_auth.json"

        (no app-name prefix), matching "_meta.json"/"_index.json" — three

        fixed, well-known filenames identifiable by the leading

        underscore alone, since the app name is already the containing

        folder and doesn't need repeating into the filename. Left as the

        old pattern, this always missed the real file: both

        get_authorization_url() and complete_authorization() call this,

        so every OAuth flow would have raised SchemaNotFound even with a

        perfectly valid auth config sitting right there on disk.

        """

        candidate = os.path.join(

            os.path.dirname(self._schema_index.get((app, next(iter(self.list_actions(app)), "")), "")),

            "_auth.json",

        )

        return candidate if os.path.exists(candidate) else None



    # -- 1a. catalog / node listing (render the picker UI) ---------------



    def list_app_catalog(self) -> List[AppSummary]:

        """

        One card per app, from each app's _meta.json (name/description/

        favicon/category). Use this for an app-level picker — pair with

        list_nodes(app) to drill into that app's actions.

        """

        catalog = []

        for meta_path in glob.glob(os.path.join(self.schemas_root, "*", "*", "_meta.json")):

            meta = retrieve_file(file_path=meta_path) or {}

            catalog.append(AppSummary(

                app=meta.get("name", os.path.basename(os.path.dirname(meta_path))),

                display_name=meta.get("display_name", ""),

                description=meta.get("description", ""),

                category=meta.get("category", ""),

                favicon_url=meta.get("favicon_url"),

                logo_background_color=meta.get("logo_background_color", ""),

            ))

        return sorted(catalog, key=lambda a: a.display_name.lower())



    def list_nodes(self, app: Optional[str] = None) -> List[NodeSummary]:

        """

        One card per app+action — what you loop through to render the node

        picker itself. Pass app to scope it to one app's actions; omit it

        to list every node across every app (e.g. a global search).



        Deliberately cheap: reads each schema's 'metadata' block only, no

        placeholder crawling, no vault lookups, no registry. Safe to call

        on every request that renders the picker.

        """

        if not self._schema_index:

            self._build_index()



        nodes = []

        for (a, action), path in self._schema_index.items():

            if app and a != app:

                continue

            schema = retrieve_file(file_path=path) or {}

            meta = schema.get("metadata", {})

            nodes.append(NodeSummary(

                app=a,

                action=action,

                display_name=meta.get("display_name", action),

                description=meta.get("description", ""),

                icon_url=meta.get("icon_url", ""),

                color=meta.get("color", ""),

                category=meta.get("category", ""),

                node_type=meta.get("node_type", "action"),

                requires_auth=self._requires_auth(schema),

            ))

        return sorted(nodes, key=lambda n: (n.app, n.display_name.lower()))



    @staticmethod

    def _requires_auth(schema: Dict[str, Any]) -> bool:

        return any(

            isinstance(v, str) and re.search(r"Default\s*=\s*\$env\.", v)

            for v in schema.get("class", {}).values()

        )



    # -- 1b. full input form for one node (after it's picked) ------------



    def get_input_form(self, app: str, action: str) -> InputForm:

        """

        Reads back the form metadata converter.py already generated for

        this endpoint. Pure read — never runs the placeholder engine, so

        this never touches per-tenant state and can't raise

        AuthorizationRequired.

        """

        schema = self._load_schema(app, action)

        meta = schema.get("metadata", {})

        raw_fields = meta.get("fields", {})



        return InputForm(

            app=app,

            action=action,

            display_name=meta.get("display_name", action),

            description=meta.get("description", ""),

            icon_url=meta.get("icon_url", ""),

            requires_auth=self._requires_auth(schema),

            fields=self._convert_top_level_fields(raw_fields),

        )



    def _convert_top_level_fields(self, raw_fields: Dict[str, Any]) -> List[FormField]:

        """

        converter.py's metadata.fields is namespaced into 'class'

        (path/query params) and 'body' (request body) sub-objects — see

        _build_node_metadata's docstring in converter.py: a path param

        and a body field can legitimately share a literal name while

        meaning two different things, so they're kept in separate

        namespaces instead of one flat dict.



        Treating raw_fields itself as a flat {field_name: spec} dict (the

        previous behavior) reads 'class' and 'body' as if THEY were

        fields — producing two blank, mislabeled inputs and silently

        losing every real field underneath them. This unwraps the two

        namespaces into two field groups instead.



        Each leaf FormField.key below is the field's full dotted path

        (e.g. "class.contactId", "body.properties.email") — this is what

        makes build_schema() collision-proof, see its docstring. The

        LABEL shown to the end user (FormField.label) is unaffected;

        it's still just "Contact Id" / "Email", exactly as converter.py

        generated it. Only the internal key changed.

        """

        out = []

        for namespace, label in (("class", "Parameters"), ("body", "Request Body")):

            section = raw_fields.get(namespace)

            if not section:

                continue

            out.append(FormField(

                key=namespace,

                label=label,

                input_type="group",

                description="",

                required=False,

                fields=self._convert_fields(section, prefix=namespace),

            ))

        return out



    def _convert_fields(self, raw_fields: Dict[str, Any], prefix: str = "") -> List[FormField]:

        out = []

        for key, spec in raw_fields.items():

            dotted_key = f"{prefix}.{key}" if prefix else key

            out.append(FormField(

                key=dotted_key,

                label=spec.get("label", key),

                input_type=spec.get("input_type", "text"),

                description=spec.get("description", ""),

                required=bool(spec.get("required", False)),

                fields=self._convert_fields(spec["fields"], prefix=dotted_key) if spec.get("fields") else None,

            ))

        return out



    def _load_schema(self, app: str, action: str) -> Dict[str, Any]:

        path = self._schema_path(app, action)

        schema = retrieve_file(file_path=path)

        if not schema:

            raise SchemaNotFound(f"Could not read schema at {path}")

        return schema



    # -- 2. fill + build --------------------------------------------------



    def build_schema(

        self,

        tenant_id: str,

        app: str,

        action: str,

        field_values: Dict[str, Any],

    ) -> BuiltRequest:

        """

        Fills the schema's placeholders with field_values, resolving any

        $env.-backed defaults from the tenant's vault, and returns a

        ready-to-fire request. Raises AuthorizationRequired or

        MissingFieldsError instead of guessing or blocking on input.



        BREAKING CHANGE: field_values is keyed by each field's full

        dotted path (exactly FormField.key from get_input_form(), e.g.

        "class.contactId", "body.properties.email") — NOT the short

        field name. A path param and a body field can legitimately

        share a short name (both called "id" but meaning different

        things); keying by short name meant one field_values entry

        silently overwrote every same-named field anywhere in the

        schema, invisibly, regardless of which one the caller meant.

        Dotted paths make every field individually addressable, so

        that collision can't happen. Every FormField the SDK hands

        back already carries the correct key to submit — a caller

        never has to construct one by hand.

        """

        path = self._schema_path(app, action)

        schema = self._load_schema(app, action)



        # Same placeholder pattern check_key_matches() uses by default —

        # every {{...}} in the schema, including {{DataType=..., Default=...}}.

        placeholder_pattern = r"\{\{\s*([\w\s.$]+(?:=[^,}]+)?(?:\s*,\s*[\w\s.$]+=[^,}]+)*)\s*\}\}"

        matches = crawler(content_to_crawl=schema, patterns=placeholder_pattern) or {}

        # dotted-path -> placeholder string for EVERY matched placeholder.

        # This is the only mapping build_schema() uses now — each dotted

        # path is unique by construction (it's a location in the tree),

        # so there's no short-key collision to worry about, unlike the

        # old "matched_items" short-key dict this used to rely on.

        placeholder_paths: Dict[str, str] = matches.get("key_value", {})



        missing = missing_field(required=placeholder_paths, content_to_check=field_values)

        unresolved_required: List[str] = []



        for dotted_path in list(missing):

            placeholder = str(placeholder_paths.get(dotted_path, ""))

            default_match = re.search(DEFAULT_REGEX, placeholder)



            if not default_match:
                # 🛠️ FIX: was unconditional — any placeholder with no
                # Default= was treated as required, even one explicitly
                # marked Required=False by the transpiler (a real
                # optional query flag with nothing sensible to default
                # to, e.g. Asana's opt_fields). Absence of the Required=
                # tag entirely (schemas generated before this fix)
                # falls through to the original strict behavior below —
                # only an explicit 'Required=False' unlocks omission.
                required_match = re.search(REQUIRED_REGEX, placeholder)
                if required_match and required_match.group(1).lower() == "false":
                    schema = self._remove_one(schema, dotted_path)
                    continue
                unresolved_required.append(dotted_path)
                continue



            raw_default = default_match.group(1).strip()

            is_escaped = raw_default.startswith("/")

            clean_default = raw_default[1:] if is_escaped else raw_default



            if clean_default.startswith("$env.") and not is_escaped:

                token_name = clean_default.replace("$env.", "")

                # Deliberately does NOT fetch or embed the real token here.

                # We only confirm the tenant is connected; the schema gets an

                # inert marker instead of a live secret, so a BuiltRequest is

                # safe to log, return over an API response, or hand to a

                # queue without leaking credentials. PiperExecutor.dispatch()

                # (or your own executor, following the same {{$cred...}}

                # contract) resolves the marker at fire-time, and only then.

                if not self.is_connected(tenant_id, app):

                    raise AuthorizationRequired(

                        app=app,

                        authorization_url=self.get_authorization_url(tenant_id, app),

                    )

                marker = f"{{{{$cred.{app}.{token_name}}}}}"

                schema = self._fill_one(schema, dotted_path, placeholder_paths, marker)

            else:

                schema = self._fill_one(schema, dotted_path, placeholder_paths, clean_default)



        if unresolved_required:

            raise MissingFieldsError(unresolved_required)



        for dotted_path, value in field_values.items():

            if dotted_path not in placeholder_paths:
                continue
            # 🛠️ FIX: an explicitly-submitted blank value for an optional
            # field ("" or None from a form the user left empty) used to
            # get filled in verbatim — an empty string still reaches
            # _finalize_request's leftover_query and gets urlencoded into
            # a stray '?opt_fields=', the exact messy-URL problem
            # Required= exists to prevent. Treat "explicitly blank" the
            # same as "never mentioned at all": omit it, don't fill it.
            placeholder = str(placeholder_paths.get(dotted_path, ""))
            required_match = re.search(REQUIRED_REGEX, placeholder)
            is_optional = bool(required_match and required_match.group(1).lower() == "false")
            if is_optional and (value is None or value == ""):
                schema = self._remove_one(schema, dotted_path)
                continue
            schema = self._fill_one(schema, dotted_path, placeholder_paths, value)

        return self._finalize_request(schema)



    def list_dotted_paths(self, app: str, action: str) -> List[str]:

        """

        Inspection helper: crawls the schema and returns a sorted list of all 

        available dotted-path keys (e.g., 'class.goal_gid', 'body.properties.name') 

        that can be mapped inside `field_values` for build_schema().

        """

        schema = self._load_schema(app, action)

        placeholder_pattern = r"\{\{\s*([\w\s.$]+(?:=[^,}]+)?(?:\s*,\s*[\w\s.$]+=[^,}]+)*)\s*\}\}"

        matches = crawler(content_to_crawl=schema, patterns=placeholder_pattern) or {}

        return sorted(list(matches.get("key_value", {}).keys()))



    @staticmethod
    def _remove_one(schema: Dict[str, Any], dotted_path: str) -> Dict[str, Any]:
        """
        Deletes the leaf at dotted_path entirely, for an optional
        (Required=False) placeholder that resolved to nothing — no user
        value, no Default=. Deleting the key is what actually keeps it
        out of the final request, rather than filling it with an empty
        string: _finalize_request's leftover_query only ever sees keys
        still present in 'class', so a deleted key can't get urlencoded
        into a stray '?opt_fields=' the way an empty-string value would.
        A dotted path that doesn't resolve to a real location (schema
        shape changed underneath it) is a silent no-op, not an error —
        this only ever removes something optional, so there's nothing
        unsafe about it being a no-op if the path is already gone.
        """
        parts = dotted_path.split(".")
        node = schema
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                return schema
            node = node[part]
        if isinstance(node, dict):
            node.pop(parts[-1], None)
        return schema

    @staticmethod
    def _fill_one(schema: Dict[str, Any], dotted_path: str, placeholder_paths: Dict[str, str], value: Any) -> Dict[str, Any]:

        """

        Fills exactly ONE placeholder occurrence — the one at dotted_path

        — and nothing else. replace_place_value_v3 matches by an entry's

        FINAL path segment (short key), scanning whatever key_path dict

        it's given; handing it the full, schema-wide placeholder_paths

        would let a short-key match hit every same-named field in the

        tree. Scoping key_path down to this single {dotted_path: ...}

        entry makes that impossible — there's only one entry, so only

        one possible match, regardless of what else in the schema shares

        its short name.

        """

        return replace_place_value_v3(

            key_path={dotted_path: placeholder_paths[dotted_path]},

            content_to_modify=schema,

            key=dotted_path.split(".")[-1],

            value=value,

            is_metadata_replacement=False,

        )



    _SINGLE_BRACE_REF = re.compile(r"\{(\w+)\}")



    def _finalize_request(self, schema: Dict[str, Any]) -> BuiltRequest:

        """

        converter.py's current schema shape adds a top-level 'class' object

        holding resolved path/query params plus the reserved '_authorization'

        credential slot, and references them from 'url'/'headers' with

        single-brace {name} tokens (e.g. url=".../{contactId}",

        Authorization="Bearer {_authorization}") — distinct from the

        double-brace {{...}} DSL placeholders already resolved above.



        By this point every class value is either a literal (path/query

        params) or the inert '{{$cred.<app>.<token>}}' marker (the

        _authorization slot). This step substitutes those into url/headers,

        routes leftover (non-path) class params onto the query string, and

        is the only place 'class' is consulted — without it, class is

        filled but silently discarded, and every request ships with a

        literal unresolved '{name}' in its URL and/or Authorization header.

        🛠️ FIX: the reserved slot's name changed from "authorization" to

        "_authorization" on the converter.py side — a real vendor API can

        legitimately have its OWN parameter literally named "authorization"

        (Stripe's Issuing Authorizations API does), which used to collide

        with this reserved slot and get silently dropped by converter.py

        before a schema even reached here. The hardcoded check below is

        updated to match.

        """

        class_params: Dict[str, Any] = dict(schema.get("class", {}))

        url = schema.get("url", "")

        headers = dict(schema.get("headers", {}))

        body = schema.get("body")



        consumed: set = set()



        def substitute(value: Any) -> Any:

            if not isinstance(value, str):

                return value



            def _sub(m: "re.Match") -> str:

                name = m.group(1)

                if name in class_params:

                    consumed.add(name)

                    return str(class_params[name])

                return m.group(0)  # leave unknown {name} refs untouched



            return self._SINGLE_BRACE_REF.sub(_sub, value)



        url = substitute(url)

        headers = {k: substitute(v) for k, v in headers.items()}



        # Any class param not consumed as a path/header ref is a query

        # param (or, for '_authorization', simply unused — e.g. an app

        # whose auth is header-only never references {_authorization}

        # anywhere, so it's correctly dropped rather than leaked as a

        # stray query string arg).

        leftover_query = {

            k: v for k, v in class_params.items()

            if k not in consumed and k != "_authorization"

        }

        if leftover_query:

            query_string = _urlparse.urlencode(leftover_query)

            sep = "&" if "?" in url else "?"

            url = f"{url}{sep}{query_string}"



        return BuiltRequest(

            method=schema.get("method", "GET"),

            url=url,

            headers=headers,

            body=body,

        )



    # -- 3. hosted oauth (replaces auth_manager.py's local server) -------



    def is_connected(self, tenant_id: str, app: str) -> bool:

        return self.store.get_bundle(tenant_id, app) is not None



    def get_authorization_url(self, tenant_id: str, app: str) -> str:

        """Returns the URL the platform's frontend should redirect the user to."""

        auth_path = self._auth_config_path(app)

        if not auth_path:

            raise SchemaNotFound(f"No OAuth config found for app '{app}'.")

        auth_cfg = retrieve_file(file_path=auth_path)

        cls = auth_cfg.get("class", {})



        # 🛠️ FIX: CLIENT_ID now comes from the platform owner's OWN

        # app-level registration (CredentialStore.get_app_credentials),

        # not from the schema's 'class.CLIENT_ID' — that field is just a

        # '{{DataType=str}}' placeholder with no value of its own,

        # exactly like '_authorization' is elsewhere. Raises

        # AppNotConfigured rather than proceeding with a broken URL, so

        # this fails loudly at setup time instead of silently sending

        # every end user through a redirect that was never going to work.

        app_creds = self.store.get_app_credentials(app)

        if app_creds is None:

            raise AppNotConfigured(app)



        import urllib.parse as _u

        encoded = dict(cls)

        encoded["CLIENT_ID"] = app_creds.client_id

        # CLIENT_SECRET is deliberately NOT set here even though it's

        # collected below in complete_authorization — auth_link only

        # ever templates in {CLIENT_ID}/{REDIRECT_URI}/{scopes} (see

        # converter.py's extract_oauth_config), and this URL is

        # redirected through the END USER'S browser. A secret has no

        # business appearing in a browser-visible URL or history even if

        # nothing currently templates it in — not setting it here is the

        # safer default against a future template change, not just

        # "happens to be unused today."

        if "scopes" in encoded:

            match = re.search(DEFAULT_REGEX, encoded["scopes"])

            scopes_value = match.group(1).strip() if match else encoded["scopes"]

            encoded["scopes"] = _u.quote(scopes_value)

        encoded["REDIRECT_URI"] = self._redirect_uri_for(app)



        auth_link = auth_cfg["auth_link"].format(**encoded)

        # tenant_id round-trips through OAuth `state` so complete_authorization

        # knows which tenant a given callback belongs to.

        sep = "&" if "?" in auth_link else "?"

        auth_link = f"{auth_link}{sep}state={_u.quote(tenant_id)}"



        self.store.record_pending_authorization(tenant_id, app, auth_link)

        return auth_link



    def complete_authorization(self, tenant_id: str, app: str, code: str) -> None:

        """

        Call this from YOUR OWN hosted OAuth callback route (the one at

        redirect_base_url) once the provider redirects back with `code`.

        Exchanges the code for tokens and stores them via your

        CredentialStore. This is the direct replacement for

        auth_manager.py's FastAPI /callback handler — same exchange

        logic, no local server.

        """

        auth_path = self._auth_config_path(app)

        if not auth_path:

            raise SchemaNotFound(f"No OAuth config found for app '{app}'.")

        auth_cfg = retrieve_file(file_path=auth_path)



        # 🛠️ FIX: was cls.get("CLIENT_ID")/cls.get("CLIENT_SECRET") — the

        # schema's 'class' object, which no longer carries real values

        # for these (see get_authorization_url above). Same app-level

        # lookup, same AppNotConfigured on failure — this method can be

        # called independently of get_authorization_url (a platform could

        # restart between issuing the redirect and the callback landing),

        # so it re-checks rather than assuming the earlier check still holds.

        app_creds = self.store.get_app_credentials(app)

        if app_creds is None:

            raise AppNotConfigured(app)



        resp = requests.post(auth_cfg["token_url"], data={

            "grant_type": "authorization_code",

            "code": code,

            "client_id": app_creds.client_id,

            "client_secret": app_creds.client_secret,

            "redirect_uri": self._redirect_uri_for(app),

        })

        resp.raise_for_status()

        tokens = resp.json()



        bundle = {

            "access_token": tokens.get("access_token"),

            "refresh_token": tokens.get("refresh_token"),

            "expires_at": time.time() + tokens.get("expires_in", 3600),

            "token_url": auth_cfg["token_url"],

            # Still cached into the per-tenant bundle (unchanged

            # behavior) — a platform owner's own refresh-token

            # implementation may read these back out of get_bundle()

            # rather than calling get_app_credentials() a second time.

            "client_id": app_creds.client_id,

            "client_secret": app_creds.client_secret,

        }



        self.store.save_bundle(tenant_id, app, bundle)

    # -- optional convenience: build_schema() -> dispatch() in one client --

    def _get_executor(self):
        """
        Lazily imports and constructs PiperExecutor on FIRST actual use —
        deliberately not at module load time, and not in __init__. This
        is the piece that keeps dispatch() genuinely optional rather than
        optional-in-name-only: piper_executor.py's own docstring says
        "OPTIONAL... if you already have your own executor/queue, you
        don't need this file," and it pulls in real third-party
        dependencies (httpx, tenacity) to do its job. An unconditional
        `from piper_executor import PiperExecutor` at the top of this
        file would force EVERY PiperSDK user to have those installed —
        including someone who builds their own executor against
        BuiltRequest and never calls dispatch() at all — just because
        the two happen to live in the same package. Constructing it here
        means the import (and its dependency requirement) only bites the
        caller who actually asks for this convenience, exactly once,
        cached on self for the life of this PiperSDK instance.
        """
        if self._executor is None:
            try:
                from .piper_executor import PiperExecutor
            except ImportError as e:
                raise ImportError(
                    "dispatch() needs piper_executor.py's own dependencies "
                    "(httpx, tenacity) installed. Either install them, or "
                    "skip this convenience method entirely and fire "
                    "build_schema()'s BuiltRequest through your own "
                    "executor/queue — see piper_executor.py's module "
                    "docstring for the resolve-and-fire contract to follow."
                ) from e
            self._executor = PiperExecutor(store=self.store)
        return self._executor

    async def dispatch(self, tenant_id: str, app: str, request: BuiltRequest, **kwargs):
        """
        Convenience pass-through to PiperExecutor.dispatch() — resolves
        any {{$cred...}} markers left inert by build_schema(), applies
        this app's rate limit, retries on timeout/429/5xx, and fires the
        request. Reuses THIS SDK's own `store`, so the same
        CredentialStore instance is used end-to-end:

            request = sdk.build_schema(tenant_id, app, action, values)
            result = await sdk.dispatch(tenant_id, app, request)

        This is entirely optional and changes nothing about build_schema()
        itself — its return value is a plain BuiltRequest dataclass,
        useful to any executor, not just this one. If you already run
        your own execution layer (a queue, a different async runtime, your
        own retry/rate-limit policy), ignore this method completely and
        fire BuiltRequest through that instead; nothing else on PiperSDK
        depends on dispatch() ever being called. Keeping this as a thin
        pass-through rather than reimplementing PiperExecutor's logic
        here means the two never drift apart — one resolve-and-fire
        implementation, reachable two ways (standalone or via this
        convenience method), not two copies of the same logic to keep in sync.
        """
        return await self._get_executor().dispatch(tenant_id, app, request, **kwargs)