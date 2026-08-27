import webbrowser
import requests
import uvicorn
import asyncio
import os
import json
import platform  # ✅ Added for OS detection
from fastapi import FastAPI, Query, BackgroundTasks
from shared.unpacked_data import UnZip
from shared.encryption_manager import encrypt_value
from shared.tools import get_auth_config_file, retrieve_file

app = FastAPI()

# Global variable to hold the server instance
server_instance = None

async def stop_server():
    """Stops the uvicorn server without exiting the Python process"""
    if server_instance:
        print("\n--- PHASE 2: Auth Complete. Closing local server... ---")
        server_instance.should_exit = True
        server_instance.force_exit = True

@app.get("/ping")
async def ping():
    return {"status": "alive"}

@app.get("/callback")
async def callback(background_tasks: BackgroundTasks, code: str = Query(None)):
    recieved_cont = app.state.cont 
    crypto_engine = app.state.crypto_engine
    secret_path = app.state.secret_path

    if not code:
        return {"status": "error", "message": "No code found"}

    file_data = retrieve_file(file_path=secret_path)
    if not file_data:
        file_data = {}
    
    print(f"file_data : {file_data}")

    # 1. Exchange 'code' for 'tokens'
    token_url = recieved_cont.get("token_url")
    auth_cfg = recieved_cont.get("auth_config", {})
    
    config = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": auth_cfg.get("CLIENT_ID"),
        "client_secret": auth_cfg.get("CLIENT_SECRET"),
        "redirect_uri": auth_cfg.get("REDIRECT_URI"),
    }
    
    response = requests.post(token_url, data=config)
    tokens = response.json()

    unzip = UnZip()
    unzip.unpack_bulk_data(content=tokens)

    # 2. Update the JSON file
    try:
        # Check if the specific app key exists in keywords or just save everything
        secret_keywords = ["access_token", "refresh_token"]
        for key, value in unzip.unpacked_key_value.items():
            if key in secret_keywords:
                encrypted_v = encrypt_value(value=value, fernet=crypto_engine)
                # Store under App Name so HubSpot doesn't overwrite Typeform
                file_data[recieved_cont["app_name"]] = encrypted_v
        
        with open(secret_path, "w") as f:
            json.dump(file_data, f, indent=4)
    except Exception as e:
        return {"status": "error", "message": f"Save failed: {e}"}

    # 3. TRIGGER GRACEFUL SERVER STOP
    background_tasks.add_task(stop_server)
    
    return {
        "status": "success", 
        "message": f"Authentication for {recieved_cont['app_name']} successful! You can close this tab."
    }

async def start_auth_flow(_cont, _crypto_engine):
    global server_instance
    
    secret_file_path = get_auth_config_file(client_name=_cont['client_name'], file_type="piper_vault")
    fil = retrieve_file(file_path=secret_file_path)
    if fil.get(_cont["app_name"]):
        print(f"✅ Token for {_cont['app_name']} already exists. Skipping auth.")
        return
    # Construct URL
    raw_auth_link = _cont.get("auth_link")
    auth_link = raw_auth_link.format(**_cont.get("auth_config"))

    print(f"\n--- PHASE 1: {_cont['app_name']} Authentication ---")
    
    app.state.cont = _cont
    app.state.crypto_engine = _crypto_engine
    app.state.secret_path = secret_file_path
    

    # ✅ DETECTION LOGIC: Linux vs Windows
    current_os = platform.system().lower()
    is_docker = os.path.exists('/.dockerenv') # Detect if inside container

    if current_os == "windows" and not is_docker:
        print("💻 Windows detected: Opening browser automatically...")
        webbrowser.open(auth_link)
    else:
        # In Linux/Docker, we print the URL so the user can click it in their terminal
        print("🐧 Linux/Container detected.")
        print("🔗 ACTION REQUIRED: Please open the following URL in your browser to authorize:")
        print(f"\n{auth_link}\n")
        
        # We still TRY to open it just in case the user has X11 forwarding
        try:
            webbrowser.open(auth_link)
        except:
            pass

    # Start local callback listener
    # Added loop="asyncio" and interface details for better stability in Docker
    config = uvicorn.Config(
        app, 
        host="0.0.0.0", 
        port=8080, 
        log_level="info", # Changed to info to see if requests actually hit the server
        loop="asyncio",
        timeout_keep_alive=5
    )
    server_instance = uvicorn.Server(config)
    
    await server_instance.serve()
    print("--- Server stopped. Continuing main program... ---")