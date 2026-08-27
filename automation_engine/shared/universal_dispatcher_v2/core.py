import httpx
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_result, retry_if_exception_type
from shared.tools import crawler, replace_place_value, get_auth_config_file, retrieve_file
import os
import asyncio
from .rategovernor import RateGovernor
from shared.database_manager import ContextDB
import re
from typing import Any

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Dispatcher")
db = ContextDB()

class UniversalDispatcher:
    def __init__(self):
        self.output = None

    def is_retry_needed(self, response):
        """Retries on network timeouts (None), Rate Limits (429), or Server Errors."""
        if response is None: return True
        return response.status_code in [429, 500, 502, 503, 504]

    async def fire(self, app_json, timeout, max_attempts, min_backoff, max_backoff):
        
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=1, min=min_backoff, max=max_backoff),
            retry=(retry_if_result(self.is_retry_needed) | retry_if_exception_type(httpx.RequestError)),
            reraise=True
        )
        async def _execute():
            target_url = app_json.get("url", "").strip()
            method = app_json.get("method", "GET").upper().strip()
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(
                    method=method,
                    url=target_url,
                    headers=app_json.get("headers", {}),
                    json=app_json.get("body", {})
                )
                return response

        try:
            response = await _execute()
            response.raise_for_status()

            # Return JSON if content exists, otherwise return a success indicator
            if 200 <= response.status_code <= 300:
                return response.json() if response.text.strip() else {"status": "success"}

        except Exception as e:
            logger.error(f"Dispatcher Final Failure after {max_attempts} retries: {str(e)}")
            return None

import time
import json
import os
import redis
import requests
from shared.encryption_manager import encrypt_value, decrypt_value
from shared.database_manager import ContextDB

redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis-broker:6379/0"))
db = ContextDB()

async def get_client_auth_cred(client_name: str, app_name: str, crypto_engine, vault_data):
    # 1. Fetch current vault data from DB first (without locking)

    encrypted_token_data = vault_data.get(app_name)

    if not encrypted_token_data:
        print(f"encrypted_token_data:                         {encrypted_token_data}")
        raise ValueError(f"No authentication data found for app '{app_name}' under client '{client_name}'. Run auth flow first.")

    # 2. Decrypt tokens and check expiration
    decrypted_blob = decrypt_value(encrypted_token_data, crypto_engine)
    return json.loads(decrypted_blob) if isinstance(decrypted_blob, str) else decrypted_blob

async def get_valid_access_token(client_name: str, app_name: str, crypto_engine, vault_data) -> str:
    """
    Retrieves the access token for an app from the vault. 
    Checks DB first; if expired, acquires a Redis lock to safely refresh 
    while waiting workers sleep, re-check DB, and compare expiration timestamps.
    """
    if not vault_data:
        return {}
    
    token_info = await get_client_auth_cred(
        client_name=client_name,
        app_name=app_name, 
        crypto_engine=crypto_engine,
        vault_data=vault_data
        )

    old_expires_at = token_info.get("expires_at")
    if not old_expires_at:
        print(f"could not find an re-uthetication token for this app {app_name} for this client {client_name}, continuing anywhere")
        return token_info["access_token"]

    # If the token is still valid, return it immediately without hitting Redis lock
    if time.time() < old_expires_at:
        print(f"⚡ Token for {app_name} is valid. Using existing DB state.")
        return token_info["access_token"]

    # 3. Token is expired, proceed to locking mechanism
    lock_key = f"lock:token_refresh:{client_name}:{app_name}"
    lock = redis_client.lock(lock_key, timeout=10, blocking_timeout=10)
    acquired = False

    try:
        acquired = await asyncio.to_thread(lock.acquire, blocking=True)
        if not acquired:
            print(f"⚠️ Could not acquire lock for {app_name} within timeout.")
            time_interval = 0.5
            for _ in range(5):
                # Re-fetch from DB after entering/waiting on lock to see if another worker already refreshed it
                
                await asyncio.sleep(0.5)
                fresh_vault = await asyncio.to_thread(db.get_vault, client_name) or {}
                token_info = await get_client_auth_cred(
                    client_name=client_name, 
                    app_name=app_name, 
                    crypto_engine=crypto_engine,
                    vault_data=fresh_vault
                )
                
                new_expires_at = token_info.get("expires_at", 0)

                # Compare old expiration with the newly fetched one from DB
                if new_expires_at > old_expires_at:
                    print(f"⚡ Token for {app_name} was successfully refreshed by another worker. Using fresh DB state.")
                    return token_info["access_token"]
                time_interval += 0.5
            raise Exception(f"Timed out waiting for another worker to refresh token for {app_name}, and could not acquire lock.")
        else:
            # Re-check DB now that we hold the lock: another worker may have
            # already refreshed the token while we were waiting to acquire it.
            fresh_vault = await asyncio.to_thread(db.get_vault, client_name) or vault_data
            fresh_token_info = await get_client_auth_cred(
                client_name=client_name,
                app_name=app_name,
                crypto_engine=crypto_engine,
                vault_data=fresh_vault
            )
            fresh_expires_at = fresh_token_info.get("expires_at", 0)
            if fresh_expires_at and time.time() < fresh_expires_at:
                print(f"⚡ Token for {app_name} was already refreshed by another worker. Using fresh DB state.")
                return fresh_token_info["access_token"]

            token_info = fresh_token_info
            vault_data = fresh_vault

            # If it's still expired and we hold the lock, perform the refresh
            print(f"🔄 Token for {app_name} expired. Requesting a new token using refresh_token...")
            
            refresh_url = token_info.get("token_url")
            refresh_payload = {
                "grant_type": "refresh_token",
                "refresh_token": token_info.get("refresh_token"),
                "client_id": token_info.get("client_id"),
                "client_secret": token_info.get("client_secret"),
            }

            # Using asynchronous thread wrapper for blocking requests call
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(refresh_url, data=refresh_payload)

            if response.status_code != 200:
                raise Exception(f"Failed to refresh token: {response.text}")

            new_tokens = response.json()
            if "refresh_token" in new_tokens:
                token_info["refresh_token"] = new_tokens["refresh_token"]
            
            expires_in = new_tokens.get("expires_in", 3600)
            token_info["access_token"] = new_tokens.get("access_token", token_info["access_token"])
            if "refresh_token" in new_tokens:
                token_info["refresh_token"] = new_tokens["refresh_token"]
            token_info["expires_at"] = time.time() + expires_in

            # 4. Re-encrypt and save back to the database vault
            updated_blob = json.dumps(token_info)
            encrypted_updated_blob = encrypt_value(value=updated_blob, fernet=crypto_engine)
            
            vault_data[app_name] = encrypted_updated_blob
            await asyncio.to_thread(db.save_vault, client_name, vault_data)
            print(f"✅ Successfully refreshed and saved token for {app_name} in DB.")

            return token_info["access_token"]

    finally:
        if acquired:
            try:
                await asyncio.to_thread(lock.release)
            except redis.exceptions.LockError:
                # Lock already expired (TTL) or was reassigned to another
                # worker before we got to release it — safe to ignore.
                pass
        
async def add_cred(webhook_token, recieved_cont, crypto_engine, _client_name, _task_id, app_name):
    # Regex allows optional {{ }}, matches $env. or !.
    pattern = [r"(?:\{\{\s*)?(\$env|!)\.(\w+)(?:\s*\}\})?"]

    # --- RESOLVE PATHS DYNAMICALLY ---
    webhook_config_path = get_auth_config_file(file_type="config_service", service="universal_webhook")

    # Load the files
    vault_data = await asyncio.to_thread(db.get_vault, _client_name) or {}
    #vault_data = db.get_vault(_client_name)
    webh = retrieve_file(file_path=webhook_config_path)
    print(f"vault_data:             {vault_data}")

    if vault_data is None or webh is None:
        print(f"❌ Error: Could not load required config files. Vault: {_client_name}, Config: {webhook_config_path}")
        return recieved_cont
    # ---------------------------------

    result = crawler(content_to_crawl=recieved_cont, patterns=pattern)
    if not result:
        return recieved_cont
    
    print(f"result:                              {result}")
    # Handle if it returns a tuple vs a dictionary package
    if isinstance(result, tuple):
        matched_items, key_value = result
    else:
        matched_items = result.get("matched_items", {})
        key_path = result.get("key_path", {})

    for key, v in matched_items.items():
        # Match pattern
        match_groups = re.search(r"(?:\{\{\s*)?(\$env|!)\.(\w+)(?:\s*\}\})?", v)
        if not match_groups:
            continue
            
        prefix = match_groups.group(1) 
        v_name = match_groups.group(2)

        if prefix == "$env":
            
            resolved_val = await get_valid_access_token(
                client_name=_client_name, 
                crypto_engine=crypto_engine,
                app_name=app_name,
                vault_data=vault_data
            )
                    
            # 3. Fallback to OS Environment Variables if not found in vault
            if not resolved_val:
                resolved_val = os.getenv(v_name) or os.getenv(v_name.upper())

            # 4. Replace the placeholder with the resolved secret value
            if resolved_val:
                recieved_cont = replace_place_value(
                    key_path=key_path, key=key,
                    content_to_modify=recieved_cont, value=resolved_val
                )

        elif prefix == "!":
            # Resolve from the Webhook config
            uni_webh = webh["universal_webhook"].format(webhook_token)
            resolved_val = uni_webh if v_name == "universal_webhook" else "unknown"
            
            recieved_cont = replace_place_value(
                key_path=result["key_value"], key=key,
                content_to_modify=recieved_cont, value=resolved_val
            )
            
    if isinstance(recieved_cont, dict):
        recieve_class = recieved_cont.get("class")
        if recieve_class:
            # Recursively hydrate the entire payload argument matrix with your decrypted class configurations
            return format_cont(content_to_modify=recieved_cont, config=recieve_class)
            
    return recieved_cont

def format_cont(content_to_modify: Any, config: dict) -> Any:
    """
    Recursively scans the request configuration arguments and formats 
    any standard template strings with the decrypted class credential values.
    """
    if isinstance(content_to_modify, dict):
        return {k: format_cont(v, config) for k, v in content_to_modify.items()}
        
    if isinstance(content_to_modify, list):
        return [format_cont(item, config) for item in content_to_modify]
        
    if isinstance(content_to_modify, str):
        if "{{" in content_to_modify and "}}" in content_to_modify:
            return content_to_modify
        # Check if the string contains a formatting bracket target
        if "{" in content_to_modify and "}" in content_to_modify:
            try:
                return content_to_modify.format(**config).strip()
            except KeyError:
                return content_to_modify
                
    return content_to_modify

# --- EXECUTION LOGIC ---
async def dispatcher(
        _args: dict, 
        _crypto_engine, 
        _client_name, 
        _task_id,
        _webhook_token: str = "",
        _app_name: str="generic_service",
        timeout: int = 10, 
        max_attempts: int = 3,   
        min_backoff: int = 2,    
        max_backoff: int = 10, 
        rate_limit: int = 5, 
        **_kwargs):
    
    # 1. Resolve Credentials (Vault & Webhooks)
    _args = await add_cred(webhook_token=_webhook_token, app_name=_app_name, recieved_cont=_args, crypto_engine=_crypto_engine, _client_name=_client_name, _task_id=_task_id)
    print(f"_args:       {_args}")

    # 2. Proactive Rate Limiting (The Governor)
    governor = RateGovernor()
    await governor.yield_control(_app_name, rate_limit)

    # 3. Fire with Retry Logic
    engine = UniversalDispatcher()
    print(f"🚀 Firing {_app_name} | Attempts: {max_attempts} | Limit: {rate_limit}/s")
    
    result = await engine.fire(
        app_json=_args, 
        timeout=timeout,
        max_attempts=max_attempts,
        min_backoff=min_backoff,
        max_backoff=max_backoff
    )

    status = "SUCCESS" if result else "ERROR!"
    print(f"--- Result ---\n{status}")
    return result