from fastapi import FastAPI, Request
import json
import uvicorn
import os
from pyngrok import ngrok
import sys
from dev_utils.pipeline_executor import Executor
from dev_utils.unpacked_data import UnZip
from dev_utils.registry import ACTION_MAP
from datetime import datetime

app = FastAPI()
endpoint_root = "/incoming"
_cont = sys.argv[1]
trigger_cont = sys.argv[2]
recieved_cont = json.loads(_cont)
trig_cont = json.loads(trigger_cont)
all_trig = json.loads(sys.argv[3])
password = json.loads(sys.argv[4])
piper_run = Executor()

@app.post("/incoming")
async def mail_box(request: Request):
    try:
        print("--- Webhook Start ---")
        
        # 1. Get the payload early to ensure we have the data
        package = await request.json()
        
        # 2. Safety Check: Ensure trig_cont and client_name exist
        # If trig_cont is a global, ensure it's not None
        client_name = trig_cont.get('client_name', 'default_client') 
        path = f"templates/{client_name}/.context_manager"
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(path), exist_ok=True)

        print(f"Received submission for form: {package.get('form_response', {}).get('form_id')}")
        
        # 3. Handle Empty or Missing File safely
        context_file = {}
        if os.path.exists(path) and os.path.getsize(path) > 0:
            try:
                with open(path, "r") as f:
                    context_file = json.load(f)
            except json.JSONDecodeError:
                print(f"⚠️ Warning: {path} was corrupted or invalid JSON. Resetting.")
                context_file = {}
        else:
            print(f"ℹ️ Info: Context manager file not found or empty. Creating new state.")
            context_file = {}

        # 4. Update and Write
        tid = all_trig.get("id", "UNKNOWN_ID")
        execution_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        context_file[execution_id] = {
            tid: package
        }
        print(f"Writing to file: {path}")
        with open(path, "w") as f:
            json.dump(context_file, f, indent=4)
    
        # Use package instead of _cont for the print check to avoid NameErrors
        print(f"File write successful. Content check: {str(package)[:50]}...")
        print("Attempting to run piper_run...")
        # Ensure 'recieved_cont' is defined; you might mean 'package' or a global
        await piper_run.call_run_executor(
            _cont=recieved_cont, action=ACTION_MAP, 
            password=password, from_trigger=True
        )
        print("piper_run finished successfully.")

    except Exception as e:
        print(f"!!! CRASH DETECTED !!!")
        print(f"Error Type: {type(e).__name__}")
        print(f"Error Message: {e}")
        import traceback
        traceback.print_exc() 

    print("--- Webhook End ---")

def start_webhook_service(port: int = 8000):
    """
    This function is what the Universal Dispatcher calls.
    It boots the FastAPI server inside your Iron Fortress.
    """
    
    CONFIG_DIR = ".piper_config"
    wbh_urlpath = os.path.join(CONFIG_DIR, ".universal_webhook")

    public_url = ngrok.connect(port).public_url + endpoint_root
    print(public_url)
    print(f" * ngrok tunnel available at: {public_url}")
    data = {
        "universal_webhook": public_url
    }
    with open(wbh_urlpath, "w") as f:
        json.dump(data, f, indent=4)

    print(f"🚀 Booting Universal Webhook on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)

start_webhook_service()
