import json
import os
import base64
import hashlib
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

CONFIG_DIR = ".piper_config"
MASTER_SALT = os.path.join(CONFIG_DIR, ".master_salt")

def initialize_salt(password: str):
    """Creates salt AND a password verifier."""
    """if os.path.exists(salt_file_path):
        return """
    
    salt = os.urandom(16)
    # Create a hash of the password + salt to verify future attempts
    verifier = hashlib.sha256(salt + password.encode()).hexdigest()
    
    # Store both (you can use a simple JSON or a custom format)
    data = {
        "salt": base64.b64encode(salt).decode('utf-8'),
        "verifier": verifier
    }
    with open(MASTER_SALT, "w") as f:
        json.dump(data, f)

def verify_password(password: str) -> bool:
    """Checks if the provided password matches the stored verifier."""
    if not os.path.exists(MASTER_SALT):
        return False
        
    with open(MASTER_SALT, "r") as f:
        data = json.load(f)
    
    salt = base64.b64decode(data['salt'])
    stored_verifier = data['verifier']
    current_hash = hashlib.sha256(salt + password.encode()).hexdigest()
    
    return current_hash == stored_verifier

def encrypt_value(value, fernet):
    return fernet.encrypt(value.encode()).decode()

def get_decrypted_vault(client_name, master_password):
    """Helper to get a dictionary of plain-text secrets."""
    vault_file = f"templates/{client_name}/.piper_vault"
    vault = load_vault(vault_file)
    
    # Get the key engine
    fernet = get_encryption_key(master_password)
    
    # Return decrypted dict
    return {k: fernet.decrypt(v.encode()).decode() for k, v in vault.items()}

def get_encryption_key(password: str):
    """Derives key using salt from the JSON config."""
    with open(MASTER_SALT, "r") as f:
        data = json.load(f)
    
    salt = base64.b64decode(data['salt'])
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=600000,
    )
    return Fernet(base64.urlsafe_b64encode(kdf.derive(password.encode())))

def load_vault(vault_file_path: str):
    if os.path.exists(vault_file_path):
        with open(vault_file_path, "r") as f: return json.load(f)
    return {}