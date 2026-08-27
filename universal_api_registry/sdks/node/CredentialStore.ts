/**
 * credentialStore.ts
 * -------------------
 * The one piece every adopter plugs in themselves. This SDK is meant to
 * embed into whatever an indie platform owner already runs — their own
 * Postgres, Mongo, a users table, a managed secrets service — so it
 * depends on this small interface, not a specific database client.
 *
 * Encryption-at-rest, if any, is YOUR implementation's job. The SDK only
 * ever sees plain token bundle objects in memory.
 *
 * 🛠️ FIX: PostgresCredentialStore and SqliteCredentialStore used to take a
 * raw fernetKey string and build their own ad-hoc fernet.Secret/Token pair
 * inline at every single call site (getBundle, saveBundle,
 * getAppCredentials, saveAppCredentials — four copies of the same
 * encode/decode dance per class). That's exactly what encryptionManager.ts's
 * CryptoEngine exists to centralize behind one encryptValue/decryptValue
 * interface, matching interpreter.py / integration.py's
 * `crypto_engine = get_crypto_engine(key)` shape: one CryptoEngine built
 * once, injected into every store, instead of each store re-deriving its
 * own fernet.Secret from a raw key string. Both stores below now take an
 * EncryptionManager in their constructor and call
 * encryptionManager.encryptValue()/decryptValue() instead of touching
 * `fernet` directly.
 */

import { EncryptionManager } from "./encryptionManager";

export interface TokenBundle {
  access_token: string;
  refresh_token?: string;
  expires_at: number; // epoch seconds
  token_url: string;
  client_id?: string;
  client_secret?: string;
}

/**
 * One app's OAuth CLIENT_ID/CLIENT_SECRET - the platform owner's OWN
 * registration with the third-party service (e.g. "our platform's Asana
 * app"), set up ONCE per app and shared across every tenant that connects
 * through it. Deliberately a separate concept from a tenant's TokenBundle:
 * one CLIENT_ID exists per app regardless of whether 1 or 10,000 tenants
 * have connected; a token bundle exists per (tenantId, app) pair.
 * Mirrors interpreter.py's AppCredentials exactly - see that class's
 * docstring for the full reasoning against merging the two shapes.
 */
export interface AppCredentials {
  client_id: string;
  client_secret: string;
}

export interface CredentialStore {
  // -- per-tenant token storage --
  getBundle(tenantId: string, app: string): Promise<TokenBundle | null>;
  saveBundle(tenantId: string, app: string, bundle: TokenBundle): Promise<void>;

  // -- per-app OAuth registration - NOT tenant-scoped --
  // Required, not optional: without these, getAuthorizationUrl() and
  // completeAuthorization() have no CLIENT_ID/CLIENT_SECRET to use at
  // all - every OAuth flow for every tenant would be broken the same
  // way, not a degraded-but-functional edge case. See interpreter.py's
  // CredentialStore docstring for the same reasoning on the Python side.
  getAppCredentials(app: string): Promise<AppCredentials | null>;
  /** Called by the platform owner during setup, not during an end-user's connect flow - no tenantId here on purpose. */
  saveAppCredentials(app: string, credentials: AppCredentials): Promise<void>;

  /** Optional: called when getAuthorizationUrl() issues a new redirect. */
  recordPendingAuthorization?(tenantId: string, app: string, authUrl: string): Promise<void>;
}

/** For local development and tests ONLY — tokens vanish on restart. */
export class InMemoryCredentialStore implements CredentialStore {
  private store = new Map<string, TokenBundle>();
  private appCreds = new Map<string, AppCredentials>();

  async getBundle(tenantId: string, app: string): Promise<TokenBundle | null> {
    return this.store.get(`${tenantId}::${app}`) ?? null;
  }

  async saveBundle(tenantId: string, app: string, bundle: TokenBundle): Promise<void> {
    this.store.set(`${tenantId}::${app}`, bundle);
  }

  async getAppCredentials(app: string): Promise<AppCredentials | null> {
    return this.appCreds.get(app) ?? null;
  }

  async saveAppCredentials(app: string, credentials: AppCredentials): Promise<void> {
    this.appCreds.set(app, credentials);
  }
}

/**
 * Reference implementation against the SAME `piper_vault` table
 * database_manager.py's ContextDB uses, for platform owners fine with
 * sharing the engine's own database. An OPTION, not the SDK's assumed
 * backend — most adopters should write their own CredentialStore
 * instead. `fernet` API is written from documentation, not verified in
 * this environment (no network access) — round-trip test it against
 * `encryption_manager.py`'s output before relying on it in production.
 */
export class PostgresCredentialStore implements CredentialStore {
  constructor(
    private pool: import("pg").Pool,
    private encryptionManager: EncryptionManager
  ) {}

  async getBundle(tenantId: string, app: string): Promise<TokenBundle | null> {
    const { rows } = await this.pool.query(
      "SELECT vault_data FROM piper_vault WHERE client_name = $1",
      [tenantId]
    );
    if (!rows.length) return null;
    const vault = typeof rows[0].vault_data === "string" ? JSON.parse(rows[0].vault_data) : rows[0].vault_data;
    const blob = vault[app];
    if (!blob) return null;

    return JSON.parse(this.encryptionManager.decryptValue(blob));
  }

  async saveBundle(tenantId: string, app: string, bundle: TokenBundle): Promise<void> {
    const { rows } = await this.pool.query(
      "SELECT vault_data FROM piper_vault WHERE client_name = $1",
      [tenantId]
    );
    const vault = rows.length
      ? typeof rows[0].vault_data === "string"
        ? JSON.parse(rows[0].vault_data)
        : rows[0].vault_data
      : {};

    vault[app] = this.encryptionManager.encryptValue(JSON.stringify(bundle));

    await this.pool.query(
      `INSERT INTO piper_vault (client_name, vault_data, updated_at)
       VALUES ($1, $2, NOW())
       ON CONFLICT (client_name)
       DO UPDATE SET vault_data = EXCLUDED.vault_data, updated_at = NOW()`,
      [tenantId, JSON.stringify(vault)]
    );
  }

  async recordPendingAuthorization(tenantId: string, app: string, authUrl: string): Promise<void> {
    await this.pool.query(
      `INSERT INTO auth_interventions (client_id, app_name, auth_url, status)
       VALUES ($1, $2, $3, 'pending')`,
      [tenantId, app, authUrl]
    );
  }

  // -- per-app OAuth registration --
  // Unlike piper_vault above (an existing table this class matches
  // against), there's no existing "one CLIENT_ID/CLIENT_SECRET per app"
  // table to port from - this is a new table this implementation needs
  // created, not just verified. Adjust name/columns freely; only the
  // CredentialStore method contract matters to the SDK.
  //
  //   CREATE TABLE piper_app_credentials (
  //     app_name TEXT PRIMARY KEY,
  //     credentials_blob TEXT NOT NULL,  -- fernet-encrypted JSON: {client_id, client_secret}
  //     updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  //   );

  async getAppCredentials(app: string): Promise<AppCredentials | null> {
    const { rows } = await this.pool.query(
      "SELECT credentials_blob FROM piper_app_credentials WHERE app_name = $1",
      [app]
    );
    if (!rows.length) return null;

    return JSON.parse(this.encryptionManager.decryptValue(rows[0].credentials_blob));
  }

  async saveAppCredentials(app: string, credentials: AppCredentials): Promise<void> {
    const blob = this.encryptionManager.encryptValue(JSON.stringify(credentials));

    await this.pool.query(
      `INSERT INTO piper_app_credentials (app_name, credentials_blob, updated_at)
       VALUES ($1, $2, NOW())
       ON CONFLICT (app_name)
       DO UPDATE SET credentials_blob = EXCLUDED.credentials_blob, updated_at = NOW()`,
      [app, blob]
    );
  }
}

/**
 * Reference implementation on `better-sqlite3` — a lighter-weight starting
 * point than PostgresCredentialStore above for platform owners not running
 * Postgres (local dev against a real file, or a single-node deployment).
 * Mirrors interpreter.py's SqliteCredentialStore: two tables,
 * `piper_credentials` (per-tenant token bundles) and
 * `piper_app_credentials` (per-app OAuth registration) — same shape as
 * PostgresCredentialStore's tables, just SQLite-flavored SQL (`?`
 * placeholders, `datetime('now')`, `ON CONFLICT ... DO UPDATE`).
 * `better-sqlite3` is synchronous under the hood; every method here still
 * returns a Promise so it satisfies the CredentialStore interface exactly
 * like the async-native implementations above.
 *
 * An OPTION, not the SDK's assumed backend — most adopters should write
 * their own CredentialStore. `fernet` API is written from documentation,
 * not verified in this environment (no network access) — round-trip test
 * it against `encryption_manager.py`'s output before relying on it in
 * production. SQLite's single-writer model also means this isn't a fit
 * for multi-process deployments; that's a reason to reach for
 * PostgresCredentialStore instead, not a bug in this class.
 */
export class SqliteCredentialStore implements CredentialStore {
  private db: import("better-sqlite3").Database;

  constructor(dbPath: string, private encryptionManager: EncryptionManager) {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const Database = require("better-sqlite3");
    this.db = new Database(dbPath);
    this.db.pragma("journal_mode = WAL"); // readers don't block the writer
    this.initSchema();
  }

  private initSchema(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS piper_credentials (
        tenant_id  TEXT NOT NULL,
        app        TEXT NOT NULL,
        bundle     TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (tenant_id, app)
      )
    `);
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS piper_app_credentials (
        app           TEXT PRIMARY KEY,
        client_id     TEXT NOT NULL,
        client_secret TEXT NOT NULL,
        updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
      )
    `);
  }

  async getBundle(tenantId: string, app: string): Promise<TokenBundle | null> {
    const row = this.db
      .prepare("SELECT bundle FROM piper_credentials WHERE tenant_id = ? AND app = ?")
      .get(tenantId, app) as { bundle: string } | undefined;
    if (!row) return null;

    return JSON.parse(this.encryptionManager.decryptValue(row.bundle));
  }

  async saveBundle(tenantId: string, app: string, bundle: TokenBundle): Promise<void> {
    const encrypted = this.encryptionManager.encryptValue(JSON.stringify(bundle));

    this.db
      .prepare(
        `INSERT INTO piper_credentials (tenant_id, app, bundle, updated_at)
         VALUES (?, ?, ?, datetime('now'))
         ON CONFLICT (tenant_id, app) DO UPDATE SET
           bundle = excluded.bundle, updated_at = excluded.updated_at`
      )
      .run(tenantId, app, encrypted);
  }

  // -- per-app OAuth registration --
  // Same table shape as PostgresCredentialStore's piper_app_credentials,
  // but two encrypted columns instead of one blob: client_id is stored
  // in the clear (it's not secret — it's sent as a query param in every
  // authorization redirect) and only client_secret is encrypted.

  async getAppCredentials(app: string): Promise<AppCredentials | null> {
    const row = this.db
      .prepare("SELECT client_id, client_secret FROM piper_app_credentials WHERE app = ?")
      .get(app) as { client_id: string; client_secret: string } | undefined;
    if (!row) return null;

    return { client_id: row.client_id, client_secret: this.encryptionManager.decryptValue(row.client_secret) };
  }

  async saveAppCredentials(app: string, credentials: AppCredentials): Promise<void> {
    const encryptedSecret = this.encryptionManager.encryptValue(credentials.client_secret);

    this.db
      .prepare(
        `INSERT INTO piper_app_credentials (app, client_id, client_secret, updated_at)
         VALUES (?, ?, ?, datetime('now'))
         ON CONFLICT (app) DO UPDATE SET
           client_id = excluded.client_id,
           client_secret = excluded.client_secret,
           updated_at = excluded.updated_at`
      )
      .run(app, credentials.client_id, encryptedSecret);
  }

  // recordPendingAuthorization is optional on the interface and there's
  // no dedicated table for it here (same as PostgresCredentialStore) —
  // override in a subclass if you want a "who's mid-connect" dashboard.
}