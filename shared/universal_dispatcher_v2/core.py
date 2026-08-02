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

    for key, v in result["matched_items"].items():
        # Match pattern
        match_groups = re.search(r"(?:\{\{\s*)?(\$env|!)\.(\w+)(?:\s*\}\})?", v)
        if not match_groups:
            continue
            
        prefix = match_groups.group(1) 
        v_name = match_groups.group(2)

        if prefix == "$env":
            resolved_val = None
            
            # 2. Check the Database Vault first (and decrypt if crypto_engine is provided)
            # It checks both exact case ('Hubspot') and uppercase ('HUBSPOT')
            vault_key = v_name if v_name in vault_data else v_name.upper()
            if vault_key in vault_data:
                encrypted_val = vault_data[vault_key]
                try:
                    # Decrypt using your crypto_engine (Fernet instance) if applicable
                    if crypto_engine and hasattr(crypto_engine, "decrypt"):
                        resolved_val = crypto_engine.decrypt(encrypted_val.encode()).decode()
                    else:
                        resolved_val = encrypted_val # Fallback if already plain text
                except Exception:
                    resolved_val = encrypted_val # Fallback if decryption fails

            # 3. Fallback to OS Environment Variables if not found in vault
            if not resolved_val:
                resolved_val = os.getenv(v_name) or os.getenv(v_name.upper())

            # 4. Replace the placeholder with the resolved secret value
            if resolved_val:
                recieved_cont = replace_place_value(
                    key_path=result["key_value"], key=key,
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