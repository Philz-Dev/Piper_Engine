from fastapi import FastAPI, Request
import json
import uvicorn
import os
import time
import threading
from pyngrok import ngrok, conf, installer
import sys
from datetime import datetime
from shared.database_manager import ContextDB
from shared.tools import retrieve_file
import uuid
from shared.redis_queuer import add_to_redis

app = FastAPI()
endpoint_root = "/incoming"

# --- Initialization ---
db = ContextDB()
if db.check_connection():
    db.initialize_tables()

def setup_ngrok():
    pyngrok_config = conf.get_default()
    ngrok_path = "/usr/local/bin/ngrok"
    pyngrok_config.ngrok_path = ngrok_path

    if os.path.exists(ngrok_path):
        os.chmod(ngrok_path, 0o755)
        return

    print("🚀 Ngrok not found. Downloading latest stable binary...")
    installer.USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    installer.install_ngrok(ngrok_path)
    os.chmod(ngrok_path, 0o755)
    print("✅ Ngrok installed successfully.")

@app.get("/ping")
async def ping():
    """
    Health check endpoint to verify the server is running.
    """
    return {
        "status": "online",
        "timestamp": datetime.now().isoformat(),
        "service": "Piper-Webhook-Manager"
    }

@app.post("/incoming/{webhook_token}")
async def mail_box(webhook_token: str, request: Request):
    try:
        print("--- Webhook Start (DB Mode) ---")
        webhook_metadata = db.resolve_webhook_token(token=webhook_token)
        if not webhook_metadata:
            return {"status": "error", "message": "Invalid Webhook Token"}, 404

        client_name = webhook_metadata.get("client_id")
        task_id = webhook_metadata.get("task_id")
        app_name = webhook_metadata.get("app_name")
        package = await request.json()
        
        print(f"📦 DATA RECEIVED: {json.dumps(package, indent=2)}")
        print(f"📡 Received submission for Client: {client_name} | Task: {task_id}")

        pipeline_blueprint = db.get_pipeline(client_name, task_id)
        event_id = f"evt_{uuid.uuid4().hex[:8]}" 
    
        existing_context = {}
        existing_context[event_id] = {
            app_name: package, 
            "_received_at": datetime.now().isoformat()
        }
        db.save_context(client_id=client_name, task_id=task_id, context_data=existing_context, event_id=event_id)
        
        add_to_redis(
            client_name=client_name, 
            agency_id=task_id, 
            event_id=event_id,
            pipeline=pipeline_blueprint,
            from_trigger=True
        )

        return {"status": "success"}
    
    except Exception as e:
        print(f"!!! CRASH DETECTED !!!")
        print(f"Error Type: {type(e).__name__} | Message: {e}")
        import traceback
        traceback.print_exc() 
    print("--- Webhook End ---")

def _manage_ngrok_tunnel(port: int, wbh_urlpath: str, ngrok_filepath: str):
    """
    Background worker that periodically checks for internet connectivity 
    and attempts to spin up the ngrok tunnel until it succeeds.
    """
    # 1. Set Auth Token if available
    try:
        ngrok_token = retrieve_file(file_path=ngrok_filepath)
        token = ngrok_token.get("NGROK_AUTHTOKEN") if isinstance(ngrok_token, dict) else ngrok_token
        if token:
            ngrok.set_auth_token(token.strip())
    except Exception as e:
        print(f"⚠️ Warning: Could not set Ngrok token: {e}")

    # 2. Infinite retry loop in the background
    while True:
        try:
            print("⏳ Attempting to establish Ngrok tunnel...")
            ngrok.kill()
            tunnel = ngrok.connect(port)
            
            max_retries = 10
            public_url = None
            added_url_val = "/{}"
            for i in range(max_retries):
                public_url = tunnel.public_url 
                if public_url and "ngrok" in public_url:
                    public_url = public_url + endpoint_root + added_url_val
                    break
                time.sleep(1)

            if public_url:
                data = {"universal_webhook": public_url}
                with open(wbh_urlpath, "w") as f:
                    json.dump(data, f, indent=4)
                print(f"✅ Ngrok Tunnel Live: {public_url}")
                print(f"💾 URL saved to {wbh_urlpath}")
                break  # Exit loop once successfully connected and saved
        except Exception as e:
            print(f"⚠️ Ngrok connection failed (offline or network error): {e}. Retrying in 30 seconds...")
        
        time.sleep(30)  # Wait before checking connectivity / retrying again

def start_webhook_service(port: int = 8003):
    """
    Boots the FastAPI server immediately and hands off ngrok tunnel management 
    to a background retry thread.
    """
    conf.get_default().ngrok_path = "/usr/local/bin/ngrok"

    CONFIG_DIR = ".piper_config"
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)

    ngrok_filepath = os.path.join(CONFIG_DIR, ".ngrok_token")
    wbh_urlpath = os.path.join(CONFIG_DIR, ".universal_webhook")
    
    # Setup binary permissions
    setup_ngrok()

    # Launch background retry thread for Ngrok so it never blocks local/offline boot
    ngrok_thread = threading.Thread(
        target=_manage_ngrok_tunnel, 
        args=(port, wbh_urlpath, ngrok_filepath), 
        daemon=True
    )
    ngrok_thread.start()

    # Boot Server immediately
    print(f"🚀 Booting Universal Webhook on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)