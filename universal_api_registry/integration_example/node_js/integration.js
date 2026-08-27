/**
 * integration.js (Node.js / Express equivalent)
 * ============================================
 * Mirrors the exact 5-part lifecycle from the Python implementation[cite: 9]:
 * Setup, UI-facing routes, Auth/OAuth callbacks, Hydration, and Execution.
 */

const express = require('express');
const path = require('path');

// Hypothetical Node SDK import (matching your stretis SDK design)

// Correct package name and subpath imports based on your package.json
const { 
    PiperSDK, 
    AuthorizationRequiredError,
    MissingFieldsError
} = require('@stretis-labs/piper-sdk');

// 🛠️ FIX: CredentialStore.ts's stores now take an injected EncryptionManager
// (see encryptionManager.ts) instead of a raw key string, matching
// interpreter.py's crypto_engine = get_crypto_engine(key) / 
// SqliteCredentialStore(store=..., crypto_engine=...) shape exactly — one
// encrypt/decrypt implementation (CryptoEngine), reused by every store,
// instead of each store rolling its own fernet Secret/Token calls inline.
const { 
    SqliteCredentialStore
} = require('@stretis-labs/piper-sdk/credentialStore');

const { getCryptoEngine } = require('@stretis-labs/piper-sdk/encryptionManager');


const app = express();
app.use(express.json());

// ---------------------------------------------------------------------------
// 1. SETUP — Initialize the engine, store, and SDK once at process start.
// ---------------------------------------------------------------------------

const key = process.env.PIPER_SECRET_KEY || "";

// 🛠️ FIX: build the CryptoEngine once here (mirrors integration.py's
// `crypto_engine = get_crypto_engine(key)`) and inject it into the store,
// rather than handing the store a raw key it has no defined constructor
// parameter for.
const cryptoEngine = getCryptoEngine(key);

const credentialStore = new SqliteCredentialStore(
    process.env.PIPER_DB_PATH || "credentials.db",
    cryptoEngine
);

// redirectBaseUrl is required by PiperSDKOptions - it's what gets sent to the
// OAuth provider as REDIRECT_URI and must match what's registered with each
// app's OAuth client. Without it, getAuthorizationUrl() silently builds every
// auth link with REDIRECT_URI=undefined.
// redirectBaseUrl is required by PiperSDKOptions - it's the base URL that
// getAuthorizationUrl()/completeAuthorization() append the app name onto
// (via index.ts's redirectUriFor), matching this file's /callback/:app_name
// route. Do NOT include an app name here - the SDK adds it per call.
const redirectBaseUrl = process.env.PIPER_REDIRECT_BASE_URL || `http://127.0.0.1:${process.env.PORT || 8080}/callback`;

const sdk = new PiperSDK({ store: credentialStore, redirectBaseUrl });

// 🛠️ FIX: this was missing entirely. integration.py registers the
// platform's own hubspot OAuth app registration (CLIENT_ID/CLIENT_SECRET)
// via credential_store.save_app_credentials() BEFORE the server starts —
// without it, getAuthorizationUrl()/getAppCredentials() has nothing to
// return, and every /connect/hubspot request 404s with "no OAuth config"
// (or throws AppNotConfigured), no matter how correct the rest of the
// wiring is. saveAppCredentials() is async (see CredentialStore.ts), so
// setup itself needs to be async and awaited before the server starts
// accepting requests — see the startServer() IIFE at the bottom of this
// file.
const hubspotAppCred = {
    client_id: process.env.HUBSPOT_CLIENT_ID || "",
    client_secret: process.env.HUBSPOT_CLIENT_SECRET || "",
};

// Serve static frontend files (including index.html)
app.use(express.static(path.join(__dirname, "..", 'static')));


// ---------------------------------------------------------------------------
// 2. UI SIDE ROUTES — Pure reads to build the node picker and dynamic form[cite: 9].
// ---------------------------------------------------------------------------

app.get('/apps', (req, res) => {
    res.json(sdk.listAppCatalog().map(appSummaryToJson));
});

app.get('/apps/:app_name/nodes', (req, res) => {
    // listNodes(app?: string) takes the app name as a plain positional
    // string, not { app }. Passing an object here meant the internal
    // `a !== app` filter (a string !== an object) was always true, so
    // every node got filtered out - this was the "nothing is found" bug.
    res.json(sdk.listNodes(req.params.app_name).map(nodeSummaryToJson));
});

// 🛠️ FIX: these two routes used to `res.json()` the SDK's raw TS objects
// straight through — AppSummary/NodeSummary use camelCase field names
// (displayName, faviconUrl, logoBackgroundColor, iconUrl, nodeType, ...),
// but index.html reads snake_case (a.display_name, a.favicon_url,
// a.logo_background_color, n.display_name, ...). Every one of those came
// back `undefined` on the frontend: display names silently fell back to
// the raw app/action id, and the icon <img> got no src at all while the
// fallback square's background color had nothing to read either — exactly
// "no bg color and no logo". The /apps/:app_name/nodes/:action/form route
// already had this same translation via fieldToJson() below; these two
// didn't. Mirrors integration.py's `[vars(a) for a in sdk.list_app_catalog()]`
// — Python's own attribute names are already snake_case, which is why the
// Python backend never showed this symptom.
function appSummaryToJson(a) {
    return {
        app: a.app,
        display_name: a.displayName,
        description: a.description,
        category: a.category,
        favicon_url: a.faviconUrl,
        logo_background_color: a.logoBackgroundColor,
    };
}

function nodeSummaryToJson(n) {
    return {
        app: n.app,
        action: n.action,
        display_name: n.displayName,
        description: n.description,
        icon_url: n.iconUrl,
        color: n.color,
        category: n.category,
        node_type: n.nodeType,
        node_type_confidence: n.nodeTypeConfidence,
        requires_auth: n.requiresAuth,
    };
}

app.get('/apps/:app_name/nodes/:action/form', (req, res) => {
    // getInputForm(app, action) is positional and synchronous - no object, no await.
    const form = sdk.getInputForm(req.params.app_name, req.params.action);
    res.json({
        display_name: form.displayName,
        description: form.description,
        requires_auth: form.requiresAuth,
        fields: form.fields.map(f => fieldToJson(f)),
    });
});

function fieldToJson(field) {
    return {
        key: field.key,
        label: field.label,
        input_type: field.inputType,
        description: field.description,
        required: field.required,
        fields: field.fields ? field.fields.map(f => fieldToJson(f)) : null,
    };
}


// ---------------------------------------------------------------------------
// 3. AUTH ROUTES — OAuth redirection and callback handlers[cite: 9].
// ---------------------------------------------------------------------------

app.get('/connect/:app_name', async (req, res) => {
    const { app_name } = req.params;
    const tenant_id = req.query.tenant_id;
    try {
        // getAuthorizationUrl(tenantId, app) is positional AND async - the
        // missing `await` meant `authUrl` was a pending Promise object,
        // which res.redirect() can't use, and any rejection (e.g.
        // AppNotConfiguredError) would've become an unhandled rejection
        // instead of landing in this catch block.
        const authUrl = await sdk.getAuthorizationUrl(tenant_id, app_name);
        res.redirect(authUrl);
    } catch (e) {
        res.status(404).json({ error: `'${app_name}' has no OAuth config: ${e.message}` });
    }
});

app.get('/callback/:app_name', async (req, res) => {
    const { app_name } = req.params;
    const { code, state: tenant_id } = req.query;
    
    try {
        // completeAuthorization(tenantId, app, code) is positional.
        await sdk.completeAuthorization(tenant_id, app_name, code);
    } catch (e) {
        return res.status(400).send(`Could not complete authorization for ${app_name}: ${e.message}`);
    }
    
    res.redirect(`/?success=connected&app=${app_name}`);
});

app.get('/connect/:app_name/status', async (req, res) => {
    const { app_name } = req.params;
    const tenant_id = req.query.tenant_id;
    // isConnected() is async - without await this always sent back a
    // Promise object (truthy), so `connected` would serialize as `{}`
    // instead of a real boolean.
    const connected = await sdk.isConnected(tenant_id, app_name);
    res.json({ app: app_name, connected });
});


// ---------------------------------------------------------------------------
// 4 + 5. HYDRATION & EXECUTION — Building the schema and dispatching[cite: 9].
// ---------------------------------------------------------------------------

app.post('/tenants/:tenant_id/run/:app_name/:action', async (req, res) => {
    const { tenant_id, app_name, action } = req.params;
    const field_values = req.body;

    // -- 4. HYDRATION --
    let request_spec;
    try {
        // buildSchema(tenantId, app, action, fieldValues) is positional AND
        // async. Without await, the object-shaped call below returned a
        // pending Promise immediately, so this try/catch never actually
        // caught AuthorizationRequiredError/MissingFieldsError - any
        // rejection surfaced later as an unhandled promise rejection
        // instead of a JSON response, and request_spec was always a Promise
        // object, not a BuiltRequest, going into dispatch().
        request_spec = await sdk.buildSchema(tenant_id, app_name, action, field_values);
    } catch (e) {
        if (e instanceof AuthorizationRequiredError) {
            return res.json({ status: "needs_authorization", authorization_url: e.authorizationUrl });
        }
        if (e instanceof MissingFieldsError) {
            return res.json({ status: "invalid", missing_fields: e.missing });
        }
        throw e;
    }

    // -- 5. EXECUTION --
    try {
        // sdk.dispatch(tenantId, app, request, opts?) is also positional.
        const result = await sdk.dispatch(tenant_id, app_name, request_spec);
        res.json({ status: result.status, data: result.data, error: result.error });
    } catch (e) {
        if (e instanceof AuthorizationRequiredError) {
            return res.json({ status: "needs_authorization", authorization_url: e.authorizationUrl });
        }
        res.status(500).json({ error: e.message });
    }
});


// ---------------------------------------------------------------------------
// Start the server
// ---------------------------------------------------------------------------
// 🛠️ FIX: saveAppCredentials() is async (CredentialStore.ts), and the
// server has no business accepting /connect requests before that write
// has landed — otherwise there's a startup race where an early request
// could hit getAppCredentials() before hubspotAppCred is actually saved.
// Wrapped setup + listen in one async IIFE so the app credentials write
// is awaited first, same ordering integration.py gets for free by being
// synchronous top-to-bottom at import time.
const PORT = process.env.PORT || 8080;

async function startServer() {
    await credentialStore.saveAppCredentials("hubspot", hubspotAppCred);

    app.listen(PORT, () => {
        console.log(`Node integration server running at http://127.0.0.1:${PORT}`);
    });
}

startServer().catch((err) => {
    console.error("Failed to start server:", err);
    process.exit(1);
});