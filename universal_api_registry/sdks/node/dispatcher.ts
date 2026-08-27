/**
 * dispatcher.ts
 * =============
 * OPTIONAL. Node port of piper_executor.py — resolves {{$cred.<app>.<token>}}
 * markers a BuiltRequest may contain and fires the request, with per-app
 * rate limiting and retry on timeout/429/5xx. Same contract as the Python
 * version: a resolved token exists only inside dispatch(), on a fresh copy
 * of the request, never in anything you hand back to your API layer.
 *
 * If you already have your own executor/queue, you don't need this file —
 * just follow the same contract yourself: find {{$cred.<app>.<token>}},
 * resolve via your CredentialStore, substitute, then fire.
 *
 * Import separately from the main SDK so platforms with their own executor
 * aren't forced to pull this in:
 *   import { PiperExecutor } from "@yourorg/piper-sdk/dispatcher";
 */

import { CredentialStore, TokenBundle } from "./CredentialStore";
import { BuiltRequest, AuthorizationRequiredError } from "./index";

const CRED_MARKER = /\{\{\$cred\.([\w-]+)\.([\w-]+)\}\}/g;
const RETRYABLE_STATUS = new Set([429, 500, 502, 503, 504]);

/**
 * The shape of a standard OAuth token-endpoint response. Node's built-in
 * fetch (undici's types, bundled with @types/node) types Response.json()
 * as Promise<unknown> — deliberately, unlike the DOM lib's Promise<any> —
 * so every field access on it needs a real shape asserted first, not
 * left as `any`, which would silence type-checking on this entirely.
 * All fields optional: a provider can omit refresh_token/expires_in, and
 * a malformed response shouldn't crash the cast itself.
 */
interface OAuthTokenResponse {
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
}

export interface DispatchOptions {
  timeoutMs?: number;
  maxAttempts?: number;
  minBackoffSec?: number;
  maxBackoffSec?: number;
  rateLimitPerSec?: number;
}

export interface DispatchResult {
  status: "success" | "error";
  data?: unknown;
  error?: string;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// Per-app rate limiting — same behavior as rategovernor.py's RateGovernor:
// calls to the same base app name (before the first '.') queue sequentially,
// each waiting its own 1/limit interval before proceeding.
// ---------------------------------------------------------------------------

class RateGovernor {
  private static _instance: RateGovernor;
  private chains = new Map<string, Promise<void>>();

  static instance(): RateGovernor {
    if (!RateGovernor._instance) RateGovernor._instance = new RateGovernor();
    return RateGovernor._instance;
  }

  async yieldControl(appName: string, limitPerSec: number): Promise<void> {
    const baseApp = appName.split(".")[0];
    const previous = this.chains.get(baseApp) ?? Promise.resolve();
    const interval = 1000 / limitPerSec;
    const next = previous.then(() => sleep(interval));
    this.chains.set(baseApp, next);
    await next;
  }
}

function backoffDelayMs(attempt: number, minSec: number, maxSec: number): number {
  const exp = Math.min(maxSec, minSec * Math.pow(2, attempt - 1));
  return exp * 1000;
}

export class PiperExecutor {
  private governor = RateGovernor.instance();

  constructor(private store: CredentialStore) {}

  // -- credential resolution (mirrors piper_executor.py) ------------------

  private async resolveBundle(tenantId: string, app: string): Promise<TokenBundle | null> {
    let bundle = await this.store.getBundle(tenantId, app);
    if (!bundle) return null;

    if (bundle.expires_at <= Date.now() / 1000 + 30) {
      bundle = await this.refresh(tenantId, app, bundle);
    }
    return bundle;
  }

  private async refresh(tenantId: string, app: string, bundle: TokenBundle): Promise<TokenBundle | null> {
    if (!bundle.refresh_token) return null;
    if (!bundle.token_url) return null; // static-token connections (connect_with_static_token) never set this — must not crash fetch() with an undefined URL

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

  /** Returns a NEW BuiltRequest with every {{$cred...}} marker resolved,
   *  at any depth in headers or body. Never mutates the input. */
  private async hydrate(tenantId: string, request: BuiltRequest): Promise<BuiltRequest> {
    const bundlesNeeded = new Map<string, TokenBundle | null>();

    const resolveString = async (value: string): Promise<string> => {
      const apps = new Set<string>();
      for (const m of value.matchAll(CRED_MARKER)) {
        apps.add(m[1]);
      }
      if (apps.size === 0) return value;

      // Resolve every distinct app referenced in this string first (a
      // value normally references just one, but this stays correct if
      // it ever references more than one).
      for (const app of apps) {
        if (!bundlesNeeded.has(app)) {
          bundlesNeeded.set(app, await this.resolveBundle(tenantId, app));
        }
        if (!bundlesNeeded.get(app)) {
          throw new AuthorizationRequiredError(app, "");
        }
      }

      return value.replace(CRED_MARKER, (_match, app: string) => bundlesNeeded.get(app)!.access_token);
    };

    // 🛠️ FIX: was a single flat pass over each object's top-level values
    // only. A {{$cred...}} marker nested more than one level deep in the
    // body (e.g. body.auth.token) silently passed through unresolved.
    // Recurses through objects and arrays at any depth now, building a
    // fresh structure at every level (not just the top one) so "never
    // mutates the input" holds for nested structures too.
    const deepResolve = async (value: unknown): Promise<unknown> => {
      if (typeof value === "string") return resolveString(value);
      if (Array.isArray(value)) {
        const out: unknown[] = [];
        for (const v of value) out.push(await deepResolve(v));
        return out;
      }
      if (value && typeof value === "object") {
        const out: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
          out[k] = await deepResolve(v);
        }
        return out;
      }
      return value;
    };

    const headers = (await deepResolve({ ...request.headers })) as Record<string, string>;
    const body = (request.body !== undefined && request.body !== null
      ? await deepResolve(request.body)
      : request.body) as Record<string, unknown> | undefined;

    return { method: request.method, url: request.url, headers, body };
  }

  // -- firing, with retry + rate limiting ----------------------------------

  private async fireWithRetry(
    hydrated: BuiltRequest,
    opts: Required<Omit<DispatchOptions, "rateLimitPerSec">>
  ): Promise<Response> {
    let lastErr: unknown;

    for (let attempt = 1; attempt <= opts.maxAttempts; attempt++) {
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), opts.timeoutMs);

        const headers = { ...hydrated.headers };
        if (hydrated.body && !headers["Content-Type"] && !headers["content-type"]) {
          headers["Content-Type"] = "application/json";
        }

        const resp = await fetch(hydrated.url, {
          method: hydrated.method,
          headers,
          body: hydrated.body ? JSON.stringify(hydrated.body) : undefined,
          signal: controller.signal,
        });
        clearTimeout(timer);

        if (RETRYABLE_STATUS.has(resp.status) && attempt < opts.maxAttempts) {
          await sleep(backoffDelayMs(attempt, opts.minBackoffSec, opts.maxBackoffSec));
          continue;
        }
        return resp;
      } catch (e) {
        lastErr = e;
        if (attempt >= opts.maxAttempts) throw e;
        await sleep(backoffDelayMs(attempt, opts.minBackoffSec, opts.maxBackoffSec));
      }
    }
    throw lastErr;
  }

  /**
   * Resolves any {{$cred...}} markers, applies this app's rate limit,
   * fires with retry on timeout/429/5xx, and returns the result. Throws
   * AuthorizationRequiredError if a credential marker can't be resolved
   * (tenant disconnected between buildSchema and dispatch — rare).
   */
  async dispatch(
    tenantId: string,
    app: string,
    request: BuiltRequest,
    opts: DispatchOptions = {}
  ): Promise<DispatchResult> {
    const {
      timeoutMs = 10_000,
      maxAttempts = 3,
      minBackoffSec = 2,
      maxBackoffSec = 10,
      rateLimitPerSec = 5,
    } = opts;

    const hydrated = await this.hydrate(tenantId, request);
    await this.governor.yieldControl(app, rateLimitPerSec);

    try {
      const resp = await this.fireWithRetry(hydrated, { timeoutMs, maxAttempts, minBackoffSec, maxBackoffSec });
      const text = await resp.text();

      if (!resp.ok) {
        return { status: "error", error: `${resp.status}: ${text}` };
      }
      const data = text.trim() ? JSON.parse(text) : { status: "success" };
      return { status: "success", data };
    } catch (e: any) {
      return { status: "error", error: String(e?.message ?? e) };
    }
  }
}