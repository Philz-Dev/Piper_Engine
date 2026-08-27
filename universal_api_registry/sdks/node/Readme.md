# @stretis-lab/piper-sdk

Node.js SDK for indie automation platforms: list app/action nodes for your
picker UI, render their input forms from schema metadata, and turn filled
forms into a ready-to-fire HTTP request — `{method, url, headers, body}`.
You call your own HTTP client with it; this SDK never makes the outbound
call itself.

Reads the same `schemas/<category>/<app>/<action>.json` files produced by
[`converter.py`](#) / [`batch-runner.py`](#) — no Python runtime required
on the Node side.

## Install

```bash
npm install @stretis-lab/piper-sdk
```

You also need a schema catalog on disk — either:


or point `schemasRoot` at your own generated `schemas/` directory (see
[Providing your own schemas](#providing-your-own-schemas) below).

### Optional peer dependencies

- `pg` + `fernet` — only needed if you use the bundled `PostgresCredentialStore`
  reference implementation. Most adopters should write their own
  [`CredentialStore`](./src/credentialStore.ts) against whatever they already
  run (Postgres, Mongo, a managed secrets service, etc.) — install nothing
  extra in that case.

## Quick start

```ts
import { PiperSDK } from "@stretis-labs/piper-sdk";
import { InMemoryCredentialStore } from "@stretis-labs/piper-sdk/credentialStore";

const sdk = new PiperSDK({
  store: new InMemoryCredentialStore(), // swap for your own CredentialStore in production
  redirectBaseUrl: "https://yourapp.com/oauth/callback",
});

// 1. Render your app/action picker
const apps = sdk.listAppCatalog();
const nodes = sdk.listNodes("hubspot");

// 2. Render the input form for one action
const form = sdk.getInputForm("hubspot", "create_contact");
// form.fields -> [{ key: "body.email", label: "Email", inputType: "text", required: true, ... }, ...]

// 3. User fills the form, you pass their values back keyed exactly as received
const request = await sdk.buildSchema("tenant_123", "hubspot", "create_contact", {
  "body.email": "a@b.com",
  "body.firstname": "Ada",
});
// request -> { method: "POST", url: "...", headers: {...}, body: {...} }

// 4. Fire it with your own HTTP client (or use the optional dispatcher — see below)
```

### Handling OAuth

```ts
if (!(await sdk.isConnected(tenantId, "hubspot"))) {
  const authUrl = await sdk.getAuthorizationUrl(tenantId, "hubspot");
  // redirect the user to authUrl
}

// in your OAuth callback route:
await sdk.completeAuthorization(tenantId, "hubspot", req.query.code);
```

### Optional: built-in executor

If you don't already have your own request executor, `PiperExecutor` (in
`./dispatcher`) resolves `{{$cred.<app>.<token>}}` markers, applies
per-app rate limiting, and retries on timeout/429/5xx:

```ts
import { PiperExecutor } from "@yourorg/piper-sdk/dispatcher";

const executor = new PiperExecutor(store);
const result = await executor.dispatch(tenantId, "hubspot", request);
```

Import it separately — platforms with their own executor/queue aren't
forced to pull this in.

## Providing your own schemas

```ts
const sdk = new PiperSDK({
  store,
  schemasRoot: "/absolute/path/to/your/schemas",
  redirectBaseUrl: "...",
});
```

## Field keys

`FormField.key` (from `getInputForm`) is a dot-path prefixed with its
section — e.g. `"class.id"` or `"body.address.street"` — because a
path/query parameter and a body property can legitimately share the same
literal name while meaning two different things. Pass keys back to
`buildSchema`'s `fieldValues` exactly as received from `getInputForm`.

## Development

```bash
npm install
npm run build   # tsc -> dist/
```

## License

Apache-2.0 — see [LICENSE](./LICENSE).