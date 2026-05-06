import httpx
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_result, retry_if_exception_type
from universal_dispatcher_v2.rategovernor import RateGovernor
from shared.tools import crawler, replace_place_value, get_auth_config_file, retrieve_file
import os

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Dispatcher")

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
        
def add_cred(recieved_cont, crypto_engine, _client_name, _task_id, app_name):
    pattern = [r"\{\{([\$!])\.\s*(\w+)\s*\}\}"]
    client_name = os.environ.get('CLIENT_NAME', 'client_temp')

    # --- RESOLVE PATHS DYNAMICALLY ---
    # Get Vault Path
    vault_path = get_auth_config_file(client_name=client_name, file_type="piper_vault")
    # Get System Webhook Config Path
    webhook_config_path = get_auth_config_file(file_type="config_service", service="universal_webhook")

    # Load the files
    # Note: We use base_dir=True if your retrieve_file needs the absolute path
    data = retrieve_file(file_path=vault_path) 
    webh = retrieve_file(file_path=webhook_config_path)
    client_data = {
        "client_name": _client_name,
        "task_id": _task_id,
        "app_name": app_name
    }
    uni_webh = webh["universal_webhook"].format(**client_data)
    print(f"uni_webh:   {uni_webh}")

    if data is None or uni_webh is None:
        print(f"❌ Error: Could not load required config files. Vault: {vault_path}, Config: {webhook_config_path}")
        return recieved_cont
    # ---------------------------------

    result = crawler(content_to_crawl=recieved_cont, patterns=pattern)
    if not result:
        return recieved_cont

    for key, v in result["matched_items"].items():
        prefix = v.strip("{{}}").split(".")[0] # This will be $ or !
        v_name = v.strip("{{}}").split(".")[1]

        if prefix == "$":
            if v_name in data:
                encrypted_val = data[v_name]
                decrypt_val = crypto_engine.decrypt(encrypted_val.encode()).decode()

                recieved_cont = replace_place_value(
                    key_path=result["key_path"], key=key,
                    content_to_modify=recieved_cont, value=decrypt_val
                )
        
        elif prefix == "!":
            # Resolve from the Webhook config
            # This allows you to treat ! variables as first-class citizens
            resolved_val = uni_webh if v_name == "universal_webhook" else "unknown"
            
            recieved_cont = replace_place_value(
                key_path=result["key_path"], key=key,
                content_to_modify=recieved_cont, value=resolved_val
            )
    recieve_class = recieved_cont.get("class")
    if recieve_class:
        return format_cont(key_path=result["key_path"], config=recieve_class, content_to_modify=recieved_cont)

def format_cont(key_path, content_to_modify, config: dict):
    for k, v in key_path.items():
        split_key = k.split(".")
        temp = content_to_modify

        for ky in split_key[:-1]:
            if ky.isdigit():
                ky = int(ky)
            temp = temp[ky]
        last_key = int(split_key[-1]) if split_key[-1].isdigit() else split_key[-1]
        if isinstance(temp[last_key], str):
            #temp[last_key] = temp[last_key].format(**config)
            formatted_val = temp[last_key].format(**config)
            temp[last_key] = formatted_val.strip() 
    return content_to_modify

# --- EXECUTION LOGIC ---
async def dispatcher(
        _args: dict, 
        _crypto_engine, 
        _client_name, 
        _task_id,
        _app_name: str="generic_service",
        timeout: int = 10, 
        max_attempts: int = 3,   
        min_backoff: int = 2,     
        max_backoff: int = 10, 
        rate_limit: int = 5, 
        **_kwargs):
    
    # 1. Resolve Credentials (Vault & Webhooks)
    _args = add_cred(app_name=_app_name, recieved_cont=_args, crypto_engine=_crypto_engine, _client_name=_client_name, _task_id=_task_id)
    print(f"_args:      {_args}")

    # 2. Proactive Rate Limiting (The Governor)
    # Uses the 'service' string (e.g., 'Hubspot') to pace requests
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