/**
 * fernet.d.ts
 * -----------
 * Minimal ambient type declaration for the untyped `fernet` npm package
 * (it ships no .d.ts of its own). Kept in its own file, separate from
 * encryptionManager.ts, on purpose: a `declare module "fernet" { ... }`
 * block placed INSIDE a file that itself has top-level import/export
 * statements (as encryptionManager.ts does) is treated by TypeScript as
 * an augmentation of an existing module rather than a fresh ambient
 * declaration — which requires "fernet" to already resolve on disk and
 * is fragile/order-dependent. A standalone .d.ts with no top-level
 * import/export of its own is treated as a global ambient script, so
 * this declaration is picked up regardless of resolution order. Add only
 * the surface encryptionManager.ts actually uses; expand if other code
 * starts calling more of `fernet`'s API.
 */

declare module "fernet" {
  export class Secret {
    constructor(key: string);
  }
  export class Token {
    constructor(opts: { secret: Secret; time?: number; token?: string; ttl?: number });
    encode(plaintext: string): string;
    decode(): string;
  }
}