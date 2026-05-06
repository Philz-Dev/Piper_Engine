import httpx
import json
import logging
import asyncio
import os
from shared.tools import crawler, replace_place_value, get_auth_config_file, retrieve_file
from universal_dispatcher.rategovernor import RateGovernor

# Set up logging to catch errors on the VPS without leaking secrets
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Dispatcher")

class UniversalDispatcher:
    def __init__(self):
        self.output = None

    async def fire(self, app_json, timeout):
        target_url = app_json.get("url", "").strip()
        method = app_json.get("method", "GET").upper().strip()
        try:
            # 3. Execute
            async with httpx.AsyncClient(timeout=timeout) as client:
                #logger.info(f"Firing {action_name} for client...")
                #print(f"Debugging {app_json}")
                response = await client.request(
                    method=method,
                    url=target_url,
                    headers=app_json.get("headers", {}),
                    json=app_json.get("body", {})
                )
                
            # Check for HTTP errors first (4xx, 5xx)
            response.raise_for_status()

            # NEW SECURITY CHECK: Only parse JSON if the body isn't empty
            if 200 <= response.status_code <= 300 or not response.text.strip():
                logger.info("Success: Server returned an empty response (expected).")
                # Check for success
                return response.json()

        except Exception as e:
            logger.error(f"Dispatcher Failure: {str(e)}")
            print(f'"error": "Request failed", "details": {str(e)}')
            return None

def add_cred(recieved_cont, crypto_engine, _client_name, _task_id):
    pattern = [r"\{\{\$\.\s*(\w+)\s*\}\}"]
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
        "app_name": recieved_cont.get("app_name")
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
        v_name = v.strip("{{}}").split(".")[1]
        
        if v_name in data:
            encrypted_val = data[v_name]
            decrypt_val = crypto_engine.decrypt(encrypted_val.encode()).decode()

            recieved_cont = replace_place_value(
                key_path=result["key_path"], key=key,
                content_to_modify=recieved_cont, value=decrypt_val
            )

    if not recieved_cont.get("auth_config"):
        recieved_cont["auth_config"] = {}
        
    recieved_cont["auth_config"]["universal_webhook"] = uni_webh
    return format_cont(key_path=result["key_path"], config=recieved_cont["auth_config"], content_to_modify=recieved_cont)

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
        _args: dict, _crypto_engine, 
        _client_name, _task_id, timeout: 
        int=10, max_attempts: int = 3,   
        min_backoff: int = 2,     
        max_backoff: int = 10, 
        rate_limit: int = 5, **_kwargs):
    _args = add_cred(recieved_cont=_args, crypto_engine=_crypto_engine, _client_name=_client_name, _task_id=_task_id)

    engine = UniversalDispatcher()
    print("🚀 Firing Dispatcher...")
    print(f"payload:  {_args}")
    governor = RateGovernor()
    await governor.yield_control(_args.get("service", "generic"), rate_limit)
    result = await engine.fire(
        app_json=_args, timeout=timeout
    )
    status = "SUCCESS" if result else "ERROR!"
    print(f"--- Result ---\n{status}")
    return result