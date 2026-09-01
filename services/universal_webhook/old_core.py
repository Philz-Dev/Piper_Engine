from fastapi import FastAPI, Request
import json
import uvicorn
import os
import time  # ✅ Added for the wait loop
from pyngrok import ngrok, conf, installer  # ✅ Added 'conf' to prevent download
import sys
from shared.unpacked_data import UnZip
from datetime import datetime
from shared.database_manager import ContextDB
from shared.tools import get_auth_config_file, retrieve_file
from fastapi import FastAPI
import shared.redis_queuer as redis_queuer
import json
import uuid
from shared.redis_queuer import add_to_redis
from shared.unpacked_data import UnZip

app = FastAPI()
endpoint_root = "/incoming"

# --- Load Global Configs from CLI arguments ---
"""_cont = sys.argv[1]
trigger_cont = sys.argv[2]
recieved_cont = json.loads(_cont)
trig_cont = json.loads(trigger_cont)
all_trig = json.loads(sys.argv[3])
password = json.loads(sys.argv[4])"""

# --- Initialization ---
db = ContextDB()
if db.check_connection():
    db.initialize_tables()

def setup_ngrok():
    # 1. Define where ngrok should live
    pyngrok_config = conf.get_default()
    ngrok_path = "/usr/local/bin/ngrok"
    pyngrok_config.ngrok_path = ngrok_path

    # 2. If it's already there, just return
    if os.path.exists(ngrok_path):
        return

    # 3. If missing, download it ONLY when needed
    print("🚀 Ngrok not found. Downloading latest stable binary...")
    
    # This 'tricks' the server much better at runtime than in a Dockerfile
    installer.USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    
    # Trigger the automatic download
    installer.install_ngrok(ngrok_path)
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
        
        print(f"📦 DATA RECEIVED: {json.dumps(package, indent=2)}") # <-- ADD THIS

        print(f"📡 Received submission for Client: {client_name} | Task: {task_id}")

        # 2. Retrieve the SAVED Pipeline (Blueprint)
        # This is what you saved during the initial 'trigger_exe' setup
        pipeline_blueprint = db.get_pipeline(client_name, task_id)


        event_id = f"evt_{uuid.uuid4().hex[:8]}" 
    
        # Save with event_id to prevent overwrites
        existing_context = {}
        existing_context[event_id] = {
            app_name: package, 
            "_received_at": datetime.now().isoformat()
        }
        db.save_context(client_id=client_name, task_id=task_id, context_data=existing_context, event_id=event_id)
        
        # Pass the event_id to Redis so the Executor knows EXACTLY which data to use
        add_to_redis(
            client_name=client_name, 
            agency_id=task_id, 
            event_id=event_id, # <--- Add this
            pipeline=pipeline_blueprint.get("pipeline_data"),
            from_trigger=True
        )

        return {"status": "success"}
    
    except Exception as e:
        print(f"!!! CRASH DETECTED !!!")
        print(f"Error Type: {type(e).__name__} | Message: {e}")
        import traceback
        traceback.print_exc() 
    print("--- Webhook End ---")

def start_webhook_service(port: int = 8003):
    """
    Boots the FastAPI server and manages the Ngrok tunnel with a 
    blocking wait to ensure the URL is ready before the Dispatcher fires.
    """

    # ✅ FIX: Point to the pre-installed binary in the Docker image
    conf.get_default().ngrok_path = "/usr/local/bin/ngrok"

    CONFIG_DIR = ".piper_config"
    
    # ✅ Ensure directory exists so we don't crash on write
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)

    ngrok_filepath = os.path.join(CONFIG_DIR, ".ngrok_token")
    wbh_urlpath = os.path.join(CONFIG_DIR, ".universal_webhook")
    
    # 1. Set Auth Token
    try:
        ngrok_token = retrieve_file(file_path=ngrok_filepath)
        # Handle both dict (JSON) and string (Plain Text) fallbacks
        token = ngrok_token.get("NGROK_AUTHTOKEN") if isinstance(ngrok_token, dict) else ngrok_token
        if token:
            ngrok.set_auth_token(token.strip())
    except Exception as e:
        print(f"⚠️ Warning: Could not set Ngrok token: {e}")

    # 2. Start Tunnel with Blocking Wait
    print("⏳ Initializing Ngrok tunnel (using pre-installed binary)...")
    
    # Open the tunnel
    tunnel = ngrok.connect(port)
    
    # ✅ WAIT LOOP: Ensure the tunnel actually has a public URL before proceeding
    max_retries = 20
    public_url = None
    added_url_val = "/{}"
    for i in range(max_retries):
        public_url = tunnel.public_url 
        if public_url and "ngrok" in public_url:
            public_url = public_url + endpoint_root + added_url_val
            break
        print(f"  ... still waiting for tunnel address (Attempt {i+1}/{max_retries})")
        time.sleep(3)

    if not public_url:
        print("💥 CRITICAL ERROR: Ngrok failed to provide a public URL.")
        sys.exit(1)

    # 3. Save URL to config file (The Dispatcher reads this)
    data = {"universal_webhook": public_url}
    with open(wbh_urlpath, "w") as f:
        json.dump(data, f, indent=4)
    
    print(f"✅ Ngrok Tunnel Live: {public_url}")
    print(f"💾 URL saved to {wbh_urlpath}")

    # 4. Boot Server
    print(f"🚀 Booting Universal Webhook on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)