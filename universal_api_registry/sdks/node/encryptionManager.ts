/**
 * encryptionManager.ts
 * ---------------------
 * Node/TS mirror of encryption_manager.py — the CryptoEngine adopters can
 * pass around wherever they want an object with .encryptValue/.decryptValue
 * METHODS rather than juggling a fernet Secret/Token pair at every call
 * site (the way CredentialStore.ts's own PostgresCredentialStore and
 * SqliteCredentialStore currently do it inline).
 *
 * One structural difference from the Python original, forced by the
 * library rather than a design choice: `cryptography.fernet.Fernet` is a
 * single object with .encrypt()/.decrypt() methods, so encryption_manager.py's
 * CryptoEngine._resolve() exists to handle being handed either that raw
 * Fernet instance or another CryptoEngine (including itself) in the
 * `fernet=` kwarg. Node's `fernet` package has no equivalent single-object
 * API — every operation goes through a Secret plus a freshly-built Token
 * (Token for encoding needs `time`; Token for decoding needs `token` and
 * `ttl: 0` to disable TTL enforcement), exactly as CredentialStore.ts's own
 * classes already call it. CryptoEngine below wraps that Secret/Token
 * pattern once, behind the same encryptValue/decryptValue interface, so
 * callers never touch fernet directly. The optional second argument on
 * each method mirrors _resolve()'s flexibility: pass a different
 * fernet.Secret (or another CryptoEngine) to encrypt/decrypt against a key
 * other than this instance's own, e.g. a per-tenant key.
 *
 * 🛠️ FIX: `fernet` ships no type declarations, so every inline
 * `import("fernet").Secret` reference below used to resolve to an
 * implicit-any / "could not find a declaration file for module 'fernet'"
 * error at each of its five use sites — hence the squiggles under every
 * `fernet` type reference. Rather than sprinkling `// @ts-ignore` at each
 * spot, the shape is now declared ONCE, in the sibling `fernet.d.ts` file
 * (see that file's header for why it's kept separate from this one rather
 * than inlined here), and every type reference in this file now points at
 * that ambient declaration via the `FernetSecret` / `FernetToken` type
 * imports below instead of reaching into the untyped package inline. The
 * `require("fernet")` calls at runtime are unchanged — only the *type*
 * side was ever broken.
 */

import type { Secret as FernetSecret, Token as FernetToken } from "fernet";

export interface EncryptionManager {
  encryptValue(plaintext: string): string;
  decryptValue(ciphertext: string): string;
}

export class CryptoEngine implements EncryptionManager {
  private readonly secret: FernetSecret;

  constructor(key: string) {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const fernet = require("fernet");
    this.secret = new fernet.Secret(key);
  }

  private resolveSecret(override?: FernetSecret | CryptoEngine): FernetSecret {
    if (override === undefined) return this.secret;
    if (override instanceof CryptoEngine) return override.secret;
    return override; // assume it's already a raw fernet.Secret instance
  }

  encryptValue(plaintext: string, secretOverride?: FernetSecret | CryptoEngine): string {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const fernet = require("fernet");
    const token: FernetToken = new fernet.Token({ secret: this.resolveSecret(secretOverride), time: Date.now() });
    return token.encode(plaintext);
  }

  decryptValue(ciphertext: string, secretOverride?: FernetSecret | CryptoEngine): string {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const fernet = require("fernet");
    const token: FernetToken = new fernet.Token({
      secret: this.resolveSecret(secretOverride),
      token: ciphertext,
      ttl: 0,
    });
    return token.decode();
  }
}

export function getCryptoEngine(key?: string): CryptoEngine {
  if (key === undefined) {
    const envKey = process.env.PIPER_ENCRYPTION_KEY;
    if (!envKey) {
      throw new Error(
        "PIPER_ENCRYPTION_KEY is not set. Generate one ONCE with:\n" +
          '    node -e "console.log(require(\'crypto\').randomBytes(32).toString(\'base64url\'))"\n' +
          "and set it as an environment variable. Losing or rotating this key makes every " +
          "already-stored credential permanently undecryptable — there is no recovery path."
      );
    }
    key = envKey;
  }
  return new CryptoEngine(key);
}