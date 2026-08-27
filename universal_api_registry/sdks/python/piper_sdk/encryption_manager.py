import json
import os
import base64
import hashlib
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from stretis import EncryptionManager


class CryptoEngine(EncryptionManager):
    """
    The object PiperSDK's PostgresCredentialStore actually expects —
    something with .encrypt_value/.decrypt_value METHODS. The bare
    encrypt_value()/decrypt_value() functions above are free functions
    taking an explicit fernet key on every call; PostgresCredentialStore
    calls `crypto_engine.encrypt_value(value=..., fernet=crypto_engine)`
    — the SAME object passed back in as 'fernet' on every call. Handles
    that pattern (fernet is self) and being called with an explicit
    external Fernet key, so it works either way.
    """

    def __init__(self, key: bytes):
        self.fernet = Fernet(key)

    def _resolve(self, fernet):
        if fernet is None or fernet is self:
            return self.fernet
        if isinstance(fernet, CryptoEngine):
            return fernet.fernet
        return fernet  # assume it's already a raw Fernet instance

    def encrypt_value(self, value, fernet=None):
        
        return self._resolve(fernet).encrypt(value.encode()).decode()

    def decrypt_value(self, value, fernet=None):
        return self._resolve(fernet).decrypt(value.encode()).decode()


def get_crypto_engine(key: bytes = None) -> CryptoEngine:
    """
    Factory referenced by the hosted-OAuth example wiring
    (`crypto_engine=get_crypto_engine()`) — was referenced there but
    never actually defined anywhere until now.

    Reads PIPER_ENCRYPTION_KEY from the environment if no key is passed
    explicitly, and REFUSES to silently generate a random one. Every
    already-encrypted credential (every tenant's tokens, every app's
    CLIENT_SECRET) becomes permanently undecryptable — cryptography.fernet
    raises InvalidToken, not a friendly error — the moment this key
    changes. Generating a fresh key on every process start (which
    `Fernet.generate_key()` called inline, with nowhere to persist the
    result, silently does) means that happens on every single restart.
    """
    if key is None:
        env_key = os.environ.get("PIPER_ENCRYPTION_KEY")
        if not env_key:
            raise RuntimeError(
                "PIPER_ENCRYPTION_KEY is not set. Generate one ONCE with:\n"
                '    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"\n'
                "and set it as an environment variable. Losing or rotating this key makes every "
                "already-stored credential permanently undecryptable — there is no recovery path."
            )
        key = env_key.encode() if isinstance(env_key, str) else env_key
    return CryptoEngine(key)