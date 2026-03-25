import httpx
import json
import logging
import asyncio
import os
from dev_utils.task_managers import crawler, replace_place_value

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

def add_cred(recieved_cont, crypto_engine):
    pattern = [r"\{\{\$\.\s*(\w+)\s*\}\}"]
    app_json = {}
    # We use a unique 'tag' so we don't overwrite other webhooks
    #recieved_cont["url"] = recieved_cont["url"].format(**recieved_cont["auth_config"])

    with open(r"templates\client_temp\.piper_vault", "r") as file:
        data = json.load(file)

    with open(r".piper_config\.universal_webhook", "r") as file:
        uni_webh = json.load(file)

    result = crawler(content_to_crawl=recieved_cont, patterns=pattern)
    if not result:
        return recieved_cont
    for key, v in result["matched_items"].items():
        v = v.strip("{{}}")
        v = v.split(".")[1]
        v = data[v]
        decrypt_val = crypto_engine.decrypt(v.encode()).decode()

        recieved_cont = replace_place_value(
            key_path=result["key_path"], key=key,
            content_to_modify=recieved_cont, value=decrypt_val
            )
    if not recieved_cont.get("auth_config"):
        recieved_cont["auth_config"] = {}
    recieved_cont["auth_config"]["universal_webhook"] = uni_webh["universal_webhook"]
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
async def dispatcher(_args: dict, _crypto_engine, timeout: int=10):
    _args = add_cred(recieved_cont=_args, crypto_engine=_crypto_engine)
    engine = UniversalDispatcher()
    print("🚀 Firing Dispatcher...")
    result = await engine.fire(
        app_json=_args, timeout=timeout
    )
    status = "SUCCESS" if result else "ERROR!"
    print(f"--- Result ---\n{status}")
    return result