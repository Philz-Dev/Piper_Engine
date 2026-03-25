import webbrowser
import requests
import uvicorn
import asyncio
import os
import json
from fastapi import FastAPI, Query, BackgroundTasks
from dev_utils.unpacked_data import UnZip
from dev_utils.encryption_manager import encrypt_value

app = FastAPI()

# Global variable to hold the server instance so we can shut it down
server_instance = None

async def stop_server():
    """Stops the uvicorn server without exiting the Python process"""
    if server_instance:
        print("--- PHASE 2: Auth Complete. Closing local server... ---")
        server_instance.should_exit = True

@app.get("/callback")
async def callback(background_tasks: BackgroundTasks, code: str = Query(None)):
    recieved_cont = app.state.cont 
    crypto_engine = app.state.crypto_engine
    secret_path = app.state.secret_path

    if not code:
        return {"status": "error", "message": "No code found"}

    with open(secret_path, "r") as file:
        file_data = json.load(file)

    # 1. Exchange 'code' for 'tokens'
    token_url = recieved_cont.get("token_url")
    auth_cfg = recieved_cont.get("auth_config", {})
    
    config = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": auth_cfg.get("CLIENT_ID"),
        "client_secret": auth_cfg.get("CLIENT_SECRET"),
        "redirect_uri": auth_cfg.get("REDIRECT_URI")
    }
    
    response = requests.post(token_url, data=config)
    tokens = response.json()

    unzip = UnZip()
    unzip.unpack_bulk_data(content=tokens)

    # 2. Update the JSON file
    try:
        secret_keywords = ["access_token"]
        for key, value in unzip.unpacked_key_value.items():
            if key in secret_keywords:
                encryted_v = encrypt_value(value=value, fernet=crypto_engine)
                file_data[recieved_cont["app_name"]] = encryted_v
        
        with open(secret_path, "w") as f:
            json.dump(file_data, f, indent=4)
    except Exception as e:
        return {"status": "error", "message": f"Save failed: {e}"}

    # 3. TRIGGER GRACEFUL SERVER STOP
    # This adds the task to run AFTER the response is sent to the browser
    background_tasks.add_task(stop_server)
    
    return {
        "status": "success", 
        "message": "Authentication successful! You can close this tab."
    }

async def start_auth_flow(_cont, _crypto_engine):
    global server_instance
    
    secret_file_path = f"templates/{_cont['client_name']}/.piper_vault"

    with open(secret_file_path, "r") as f:
        fil = json.load(f)

    if fil.get(_cont["app_name"]):
        print("Token already exists. Skipping auth.")
        return

    app.state.cont = _cont
    app.state.crypto_engine = _crypto_engine
    app.state.secret_path = secret_file_path

    # Construct and open URL
    raw_auth_link = _cont.get("auth_link")
    auth_link = raw_auth_link.format(**_cont.get("auth_config"))
    print("--- PHASE 1: Authentication ---")
    webbrowser.open(auth_link)

    # NEW: Run uvicorn manually so we can stop it programmatically
    config = uvicorn.Config(app, host="127.0.0.1", port=8080, log_level="error")
    server_instance = uvicorn.Server(config)
    
    # This blocks here until server_instance.should_exit is set to True
    await server_instance.serve()
    
    print("--- Server stopped. Continuing main program... ---")