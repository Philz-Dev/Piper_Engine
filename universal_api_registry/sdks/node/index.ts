/**
 * @stretis/piper-sdk
 * ==================
 * Node.js port of piper_sdk.py — same five methods, same public contract,
 * same schema JSON files as the source of truth (the output of
 * converter.py / batch-runner.py). A Node platform never touches
 * interpreter.py / auth_manager.py directly; it reads the same
 * schemas/<category>/<app>/<action>.json files and shares the same
 * Postgres vault, so it's a first-class alternative to the Python SDK,
 * not a thin proxy in front of it.
 *
 *   const form  = await sdk.getInputForm("hubspot", "update_contact");
 *   const ready = await sdk.buildSchema("acct_123", "hubspot", "update_contact",
 *                                        { contactId: "42", email: "a@b.com" });
 *
 * `ready` is {method, url, headers, body} — hand it to your own HTTP client.
 * This SDK never makes the outbound call itself.
 */


import * as fs from "fs";
import * as path from "path";
import { CredentialStore, TokenBundle, AppCredentials } from "./CredentialStore";
import { crawlPlaceholders, missingFields, extractDefault, replaceByShortKey, resolveReferences, Section } from "./placeholders";
import type { DispatchOptions, DispatchResult, PiperExecutor as PiperExecutorType } from "./dispatcher";

/**
 * Same shape/reasoning as dispatcher.ts's OAuthTokenResponse — kept as a
 * separate local declaration rather than importing one from dispatcher.ts,
 * since index.ts is imported BY dispatcher.ts (`from "./index"`) and a
 * reverse import back would create a circular dependency. If
 * CredentialStore.ts ever centralizes shared types, this is a natural
 * candidate to move there instead of staying duplicated in both files.
 */
interface OAuthTokenResponse {
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
}

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface AppSummary {
  app: string;
  displayName: string;
  description: string;
  category: string;
  faviconUrl: string;
  logoBackgroundColor: string;
}

export interface NodeSummary {
  app: string;
  action: string;
  displayName: string;
  description: string;
  iconUrl: string;
  color: string;
  category: string;
  nodeType: string;
  /** 'heuristic' | 'verified' — converter.py flags auto-guessed node types so a
   *  review UI can distinguish them from confirmed ones instead of presenting
   *  both as equally authoritative. */
  nodeTypeConfidence: string;
  requiresAuth: boolean;
}

export interface FormField {
  key: string; // dot-path incl. section prefix, e.g. "class.email" or "body.address.street" — pass back as-is in buildSchema's fieldValues
  section: "class" | "body";
  label: string;
  inputType: "text" | "number" | "checkbox" | "tags" | "group" | string;
  description: string;
  required: boolean;
  fields?: FormField[]; // populated when inputType === "group"
}

export interface InputForm {
  app: string;
  action: string;
  displayName: string;
  description: string;
  iconUrl: string;
  requiresAuth: boolean;
  fields: FormField[];
}

export interface BuiltRequest {
  method: string;
  url: string;
  headers: Record<string, string>;
  body?: Record<string, unknown>;
}

export class AuthorizationRequiredError extends Error {
  constructor(public app: string, public authorizationUrl: string) {
    super(`'${app}' is not connected for this tenant yet.`);
    this.name = "AuthorizationRequiredError";
  }
}

export class MissingFieldsError extends Error {
  constructor(public missing: string[]) {
    super(`Missing required fields: ${missing.join(", ")}`);
    this.name = "MissingFieldsError";
  }
}

export class SchemaNotFoundError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SchemaNotFoundError";
  }
}

export class AppNotConfiguredError extends Error {
  constructor(public app: string) {
    super(
      `App '${app}' has no OAuth registration yet. Call ` +
      `store.saveAppCredentials('${app}', {...}) with your platform's own ` +
      `CLIENT_ID/CLIENT_SECRET for this app before any tenant can connect it.`
    );
    this.name = "AppNotConfiguredError";
  }
}

// ---------------------------------------------------------------------------
// SDK
// ---------------------------------------------------------------------------

export interface PiperSDKOptions {
  store: CredentialStore; // your implementation — see credentialStore.ts
  schemasRoot?: string; // optional — auto-detects @yourorg/piper-schemas if omitted
  redirectBaseUrl: string; // YOUR hosted OAuth callback URL
}

export class PiperSDK {
  private schemasRoot: string;
  private store: CredentialStore;
  private redirectBaseUrl: string;
  private schemaIndex: Map<string, string> = new Map(); // "app::action" -> file path
  private _executor: PiperExecutorType | null = null; // lazily constructed PiperExecutor - see getExecutor()

  constructor(opts: PiperSDKOptions) {
    this.schemasRoot = opts.schemasRoot ?? PiperSDK.autodetectSchemasRoot();
    this.store = opts.store;
    this.redirectBaseUrl = opts.redirectBaseUrl;
    this.buildIndex();
  }

  private static autodetectSchemasRoot(): string {
    const schemaPath = path.resolve("./schemas");
    if (fs.existsSync(schemaPath)) {
        return schemaPath;
    }
    throw new SchemaNotFoundError(
        `Local schema directory not found at ${schemaPath}. ` +
        "Pass schemasRoot explicitly if your schemas are located elsewhere."
    );
}

  // -- discovery ---------------------------------------------------------

  private buildIndex(): void {
    this.schemaIndex.clear();
    if (!fs.existsSync(this.schemasRoot)) return;

    for (const category of fs.readdirSync(this.schemasRoot)) {
      const categoryDir = path.join(this.schemasRoot, category);
      if (!fs.statSync(categoryDir).isDirectory()) continue;

      for (const app of fs.readdirSync(categoryDir)) {
        const appDir = path.join(categoryDir, app);
        if (!fs.statSync(appDir).isDirectory()) continue;

        for (const file of fs.readdirSync(appDir)) {
          if (file === "_meta.json" || file === "_index.json" || file.endsWith("_auth.json") || !file.endsWith(".json")) {
            continue;
          }
          const action = file.slice(0, -".json".length);
          this.schemaIndex.set(`${app}::${action}`, path.join(appDir, file));
        }
      }
    }
  }

  listApps(): string[] {
    const apps = new Set<string>();
    for (const key of this.schemaIndex.keys()) apps.add(key.split("::")[0]);
    return [...apps].sort();
  }

  listActions(app: string): string[] {
    const actions: string[] = [];
    for (const key of this.schemaIndex.keys()) {
      const [a, action] = key.split("::");
      if (a === app) actions.push(action);
    }
    return actions.sort();
  }

  private schemaPath(app: string, action: string): string {
    let p = this.schemaIndex.get(`${app}::${action}`);
    if (!p) {
      this.buildIndex(); // picks up schemas added since startup
      p = this.schemaIndex.get(`${app}::${action}`);
    }
    if (!p) throw new SchemaNotFoundError(`No schema for ${app}.${action}`);
    return p;
  }

  /**
   * The per-app OAuth callback URL - this.redirectBaseUrl with the app name
   * appended as a path segment (e.g. "https://platform.com/callback" +
   * "/hubspot"), matching a callback route shaped like "/callback/:appName".
   *
   * getAuthorizationUrl() and completeAuthorization() BOTH call this rather
   * than reading this.redirectBaseUrl directly, and both need to compute the
   * exact same value for the exact same app - an OAuth provider's token
   * exchange validates that the redirect_uri sent at that step matches the
   * one used for the original authorization redirect byte-for-byte; if these
   * two ever drifted apart (e.g. one appending the app name and the other
   * not), every token exchange would fail with a redirect_uri mismatch error
   * from the provider, not from anything on this end. Direct port of
   * interpreter.py's _redirect_uri_for.
   */
  private redirectUriFor(app: string): string {
    return `${this.redirectBaseUrl.replace(/\/+$/, "")}/${app}`;
  }

  private authConfigPath(app: string): string | null {
    // 🛠️ FIX: was `${app}_auth.json` — that matched converter.py's OLD
    // auth-file naming. converter.py now writes a bare "_auth.json" (no
    // app-name prefix), matching "_meta.json"/"_index.json" - the app name
    // is already the containing folder and doesn't need repeating into the
    // filename. Left as the old pattern, this always missed the real file,
    // so both getAuthorizationUrl() and completeAuthorization() raised
    // SchemaNotFoundError even with a perfectly valid auth config sitting
    // right there on disk. Same fix as interpreter.py's _auth_config_path.
    const anyAction = this.listActions(app)[0];
    if (!anyAction) return null;
    const appDir = path.dirname(this.schemaPath(app, anyAction));
    const candidate = path.join(appDir, "_auth.json");
    return fs.existsSync(candidate) ? candidate : null;
  }

  private loadSchema(app: string, action: string): any {
    const filePath = this.schemaPath(app, action);
    return JSON.parse(fs.readFileSync(filePath, "utf-8"));
  }

  private static requiresAuth(schema: any): boolean {
    const cls = schema.class ?? {};
    return Object.values(cls).some(
      (v) => typeof v === "string" && /Default\s*=\s*\$env\./.test(v)
    );
  }

  // -- 1a. catalog / node listing (render the picker UI) -----------------

  /** One card per app, from each app's _meta.json. For an app-level picker. */
  listAppCatalog(): AppSummary[] {
    const catalog: AppSummary[] = [];
    if (!fs.existsSync(this.schemasRoot)) return catalog;

    for (const category of fs.readdirSync(this.schemasRoot)) {
      const categoryDir = path.join(this.schemasRoot, category);
      if (!fs.statSync(categoryDir).isDirectory()) continue;

      for (const app of fs.readdirSync(categoryDir)) {
        const metaPath = path.join(categoryDir, app, "_meta.json");
        if (!fs.existsSync(metaPath)) continue;
        const meta = JSON.parse(fs.readFileSync(metaPath, "utf-8"));
        catalog.push({
          app: meta.name ?? app,
          displayName: meta.display_name ?? "",
          description: meta.description ?? "",
          category: meta.category ?? "",
          // 🛠️ FIX: was `meta.favicon_local_path ?? meta.favicon_url ?? ""`.
          // favicon_local_path is a bare filename written next to _meta.json
          // by converter.py's favicon downloader (e.g. "hubspot_favicon.png")
          // — a relative path on disk, not a URL. Nothing here (or in
          // integration.js) exposes schemasRoot over HTTP, so that bare
          // filename could never resolve as an <img src>. favicon_url (the
          // vendor-hosted logo URL) is an actual absolute URL and renders
          // correctly as-is. Mirrors the identical fix already applied to
          // interpreter.py's Python SDK.
          faviconUrl: meta.favicon_url ?? "",
          logoBackgroundColor: meta.logo_background_color ?? "",
        });
      }
    }
    return catalog.sort((a, b) => a.displayName.localeCompare(b.displayName));
  }

  /**
   * One card per app+action — loop through this to render the node picker
   * itself. Pass `app` to scope it to one app; omit it to list every node
   * across every app. Deliberately cheap: no placeholder crawling, no
   * vault lookups — safe to call on every request that renders the picker.
   */
  listNodes(app?: string): NodeSummary[] {
    const nodes: NodeSummary[] = [];
    for (const [key, filePath] of this.schemaIndex) {
      const [a, action] = key.split("::");
      if (app && a !== app) continue;

      const schema = JSON.parse(fs.readFileSync(filePath, "utf-8"));
      const meta = schema.metadata ?? {};
      nodes.push({
        app: a,
        action,
        displayName: meta.display_name ?? action,
        description: meta.description ?? "",
        iconUrl: meta.icon_url ?? "",
        color: meta.color ?? "",
        category: meta.category ?? "",
        nodeType: meta.node_type ?? "action",
        nodeTypeConfidence: meta.node_type_confidence ?? "heuristic",
        requiresAuth: PiperSDK.requiresAuth(schema),
      });
    }
    return nodes.sort(
      (a, b) => a.app.localeCompare(b.app) || a.displayName.localeCompare(b.displayName)
    );
  }

  // -- 1b. full input form for one node (after it's picked) --------------

  getInputForm(app: string, action: string): InputForm {
    const schema = this.loadSchema(app, action);
    const meta = schema.metadata ?? {};
    const rawFields = meta.fields ?? {};
    return {
      app,
      action,
      displayName: meta.display_name ?? action,
      description: meta.description ?? "",
      iconUrl: meta.icon_url ?? "",
      requiresAuth: PiperSDK.requiresAuth(schema),
      fields: [
        ...PiperSDK.convertSection(rawFields.class ?? {}, "class"),
        ...PiperSDK.convertSection(rawFields.body ?? {}, "body"),
      ],
    };
  }

  /**
   * converter.py's metadata.fields is namespaced as {class: {...}, body: {...}}
   * — NOT a flat {fieldName: spec} map — specifically so a path/query param
   * and a body property that happen to share a literal name (e.g. a URL
   * 'id' identifying which record to update vs. an unrelated body 'id'
   * field) stay distinguishable instead of one silently overwriting the
   * other. `key` carries the section + full nested path (e.g.
   * "body.address.street") so it round-trips unambiguously into
   * buildSchema's fieldValues, matching crawlPlaceholders' own key format
   * in placeholders.ts.
   */
  private static convertSection(sectionFields: Record<string, any>, section: Section, path: string[] = []): FormField[] {
    return Object.entries(sectionFields).map(([fieldName, spec]) => {
      const fullPath = [...path, fieldName];
      return {
        key: `${section}.${fullPath.join(".")}`,
        section,
        label: spec.label ?? fieldName,
        inputType: spec.input_type ?? "text",
        description: spec.description ?? "",
        required: Boolean(spec.required),
        fields: spec.fields ? PiperSDK.convertSection(spec.fields, section, fullPath) : undefined,
      };
    });
  }

  // -- 2. fill + build -----------------------------------------------------

  /**
   * Fills the schema's placeholders with fieldValues, resolving any
   * $env.-backed defaults from the tenant's vault, and returns a
   * ready-to-fire request. Throws AuthorizationRequiredError or
   * MissingFieldsError instead of guessing or blocking on input.
   */
  async buildSchema(
    tenantId: string,
    app: string,
    action: string,
    fieldValues: Record<string, unknown>
  ): Promise<BuiltRequest> {
    const schema = this.loadSchema(app, action);
    const { matchedItems, keyValue } = crawlPlaceholders(schema);

    const missing = missingFields(matchedItems, fieldValues);
    const unresolvedRequired: string[] = [];

    for (const m of missing) {
      const placeholder = matchedItems[m];
      const rawDefault = extractDefault(placeholder);

      if (rawDefault === null) {
        unresolvedRequired.push(m);
        continue;
      }

      const isEscaped = rawDefault.startsWith("/");
      const cleanDefault = isEscaped ? rawDefault.slice(1) : rawDefault;

      if (cleanDefault.startsWith("$env.") && !isEscaped) {
        const tokenName = cleanDefault.replace("$env.", "");
        const resolved = await this.resolveCredential(tenantId, app, tokenName);
        if (resolved === null) {
          throw new AuthorizationRequiredError(app, await this.getAuthorizationUrl(tenantId, app));
        }
        replaceByShortKey(schema, keyValue, m, resolved);
      } else {
        replaceByShortKey(schema, keyValue, m, cleanDefault);
      }
    }

    if (unresolvedRequired.length) {
      throw new MissingFieldsError(unresolvedRequired);
    }

    for (const [key, value] of Object.entries(fieldValues)) {
      if (key in matchedItems) {
        replaceByShortKey(schema, keyValue, key, value);
      }
    }

    // Value placeholders in class/body are now filled — but headers and
    // the url template can still hold single-brace REFERENCES to a class
    // field (headers.Authorization = "Bearer {_authorization}", url =
    // ".../users/{id}"), which point at the resolved value, not the
    // marker. This pass was previously entirely missing: buildSchema
    // returned schema.headers/schema.url as-is, so a caller would get
    // back the literal string "Bearer {_authorization}" instead of a
    // usable Authorization header. (Purely illustrative naming here —
    // this resolver is generic and works off whatever key names actually
    // appear in schema.class; it required no code change when
    // converter.py renamed its reserved slot from "authorization" to
    // "_authorization".)
    const resolvedClass: Record<string, unknown> = schema.class ?? {};
    const url = resolveReferences(schema.url ?? "", resolvedClass);
    const headers: Record<string, string> = {};
    for (const [hKey, hValue] of Object.entries<unknown>(schema.headers ?? {})) {
      headers[hKey] = typeof hValue === "string" ? resolveReferences(hValue, resolvedClass) : String(hValue);
    }

    return {
      method: schema.method ?? "GET",
      url,
      headers,
      body: schema.body,
    };
  }

  private async resolveCredential(
    tenantId: string,
    app: string,
    _tokenName: string
  ): Promise<string | null> {
    let bundle = await this.store.getBundle(tenantId, app);
    if (!bundle) return null;

    if (bundle.expires_at <= Date.now() / 1000 + 30) {
      bundle = await this.refreshToken(tenantId, app, bundle);
      if (!bundle) return null;
    }
    return bundle.access_token;
  }

  private async refreshToken(
    tenantId: string,
    app: string,
    bundle: TokenBundle
  ): Promise<TokenBundle | null> {
    if (!bundle.refresh_token) return null;
    if (!bundle.token_url) {
      // Same category of gap as access_token above: a bundle with a
      // refresh_token but no token_url can't actually be refreshed —
      // silently falling through to fetch(undefined, ...) would throw a
      // low-level TypeError deep inside fetch() instead of a clear
      // "this bundle is missing what it needs" error at the one place
      // that knows why.
      return null;
    }

    const resp = await fetch(bundle.token_url, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        refresh_token: bundle.refresh_token,
        client_id: bundle.client_id ?? "",
        client_secret: bundle.client_secret ?? "",
      }),
    });
    if (!resp.ok) return null;

    const tokens = (await resp.json()) as OAuthTokenResponse;
    const updated: TokenBundle = {
      ...bundle,
      access_token: tokens.access_token ?? bundle.access_token,
      refresh_token: tokens.refresh_token ?? bundle.refresh_token,
      expires_at: Date.now() / 1000 + (tokens.expires_in ?? 3600),
    };
    await this.store.saveBundle(tenantId, app, updated);
    return updated;
  }

  // -- 3. hosted oauth (replaces auth_manager.py's local server) ---------

  async isConnected(tenantId: string, app: string): Promise<boolean> {
    return (await this.store.getBundle(tenantId, app)) !== null;
  }

  /** Returns the URL YOUR frontend should redirect the user to. */
  async getAuthorizationUrl(tenantId: string, app: string): Promise<string> {
    const authPath = this.authConfigPath(app);
    if (!authPath) throw new SchemaNotFoundError(`No OAuth config found for app '${app}'.`);
    const authCfg = JSON.parse(fs.readFileSync(authPath, "utf-8"));
    const cls = authCfg.class ?? {};

    const appCreds = await this.store.getAppCredentials(app);
    if (appCreds === null) throw new AppNotConfiguredError(app);

    const encoded: Record<string, string> = { ...cls };
    encoded.CLIENT_ID = appCreds.client_id;
    // CLIENT_SECRET intentionally not set here - see fix note above.
    if (encoded.scopes) encoded.scopes = encodeURIComponent(encoded.scopes);
    encoded.REDIRECT_URI = this.redirectUriFor(app);

    let authLink: string = authCfg.auth_link;
    for (const [k, v] of Object.entries(encoded)) {
      authLink = authLink.replaceAll(`{${k}}`, v);
    }
    const sep = authLink.includes("?") ? "&" : "?";
    authLink = `${authLink}${sep}state=${encodeURIComponent(tenantId)}`;

    if (this.store.recordPendingAuthorization) {
      await this.store.recordPendingAuthorization(tenantId, app, authLink);
    }
    return authLink;
  }

  /**
   * Call from YOUR hosted OAuth callback route once the provider redirects
   * back with `code`. Exchanges it for tokens and stores them, encrypted,
   * in the tenant's vault.
   */
  async completeAuthorization(tenantId: string, app: string, code: string): Promise<void> {
    const authPath = this.authConfigPath(app);
    if (!authPath) throw new SchemaNotFoundError(`No OAuth config found for app '${app}'.`);
    const authCfg = JSON.parse(fs.readFileSync(authPath, "utf-8"));

    const appCreds = await this.store.getAppCredentials(app);
    if (appCreds === null) throw new AppNotConfiguredError(app);

    const resp = await fetch(authCfg.token_url, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "authorization_code",
        code,
        client_id: appCreds.client_id,
        client_secret: appCreds.client_secret,
        redirect_uri: this.redirectUriFor(app),
      }),
    });
    if (!resp.ok) {
      throw new Error(`Token exchange failed: ${resp.status} ${await resp.text()}`);
    }
    const tokens = (await resp.json()) as OAuthTokenResponse;
    if (!tokens.access_token) {
      // A malformed/non-standard provider response could omit this even
      // on a 2xx status — TokenBundle.access_token is required (it's the
      // one field every request needs), so this can't fall through as
      // undefined the way a plain `tokens.access_token` assignment would
      // let it. Throwing here beats storing a bundle with a missing
      // access_token that only surfaces as a confusing 401 later, on
      // whatever request happens to use it first.
      throw new Error(`Token exchange succeeded (${resp.status}) but response had no access_token`);
    }

    const bundle: TokenBundle = {
      access_token: tokens.access_token,
      refresh_token: tokens.refresh_token,
      expires_at: Date.now() / 1000 + (tokens.expires_in ?? 3600),
      token_url: authCfg.token_url,
      // Still cached into the per-tenant bundle (unchanged behavior) - a
      // platform's own refresh-token implementation may read these back
      // out of getBundle() rather than calling getAppCredentials() again.
      client_id: appCreds.client_id,
      client_secret: appCreds.client_secret,
    };
    await this.store.saveBundle(tenantId, app, bundle);
  }

  // -- optional convenience: buildSchema() -> dispatch() in one client ---

  /**
   * Lazily imports and constructs PiperExecutor on FIRST actual use -
   * deliberately not at module load time, and not in the constructor.
   * dispatcher.ts's own module docstring says "OPTIONAL... if you already
   * have your own executor/queue, you don't need this file" - constructing
   * it eagerly here would defeat that for every PiperSDK user, including
   * one who builds their own executor against BuiltRequest and never calls
   * dispatch() at all, just because the two happen to live in the same
   * package. Direct port of interpreter.py's _get_executor.
   */
  private getExecutor(): PiperExecutorType {
    if (this._executor !== null) {
      return this._executor;
    }
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { PiperExecutor } = require("./dispatcher");
    const executor: PiperExecutorType = new PiperExecutor(this.store);
    this._executor = executor;
    return executor;
  }

  /**
   * Convenience pass-through to PiperExecutor.dispatch() - resolves any
   * {{$cred...}} markers left inert by buildSchema(), applies this app's
   * rate limit, retries on timeout/429/5xx, and fires the request. Reuses
   * THIS SDK's own `store`, so the same CredentialStore instance is used
   * end-to-end:
   *
   *   const request = await sdk.buildSchema(tenantId, app, action, values);
   *   const result  = await sdk.dispatch(tenantId, app, request);
   *
   * Entirely optional and changes nothing about buildSchema() itself - its
   * return value is a plain BuiltRequest object, useful to any executor,
   * not just this one. If you already run your own execution layer, ignore
   * this method completely and fire BuiltRequest through that instead;
   * nothing else on PiperSDK depends on dispatch() ever being called.
   */
  async dispatch(
    tenantId: string,
    app: string,
    request: BuiltRequest,
    opts?: DispatchOptions
  ): Promise<DispatchResult> {
    return this.getExecutor().dispatch(tenantId, app, request, opts);
  }
}