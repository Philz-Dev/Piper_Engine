import webbrowser
import requests
import uvicorn
import asyncio
import os
import json
import platform
from fastapi import FastAPI, Query, BackgroundTasks
from shared.unpacked_data import UnZip
from shared.encryption_manager import encrypt_value
from shared.database_manager import ContextDB
import urllib.parse  # ✅ Import your DB manager
import time

app = FastAPI()
db = ContextDB() # ✅ Initialize DB globally or in app.state
server_instance = None

async def stop_server():
    if server_instance:
        print("\n--- PHASE 2: Auth Complete. Closing local server... ---")
        server_instance.should_exit = True

@app.get("/callback/{hubspot}")
async def callback(background_tasks: BackgroundTasks, code: str = Query(None)):
    recieved_cont = app.state.cont 
    crypto_engine = app.state.crypto_engine
    client_name = recieved_cont['client_name']
    app_name = recieved_cont["app_name"]

    if not code:
        return {"status": "error", "message": "No code found"}

    # 1. Fetch current vault from DB instead of file
    vault_data = db.get_vault(client_name)
    
    # 2. Exchange 'code' for 'tokens'
    token_url = recieved_cont.get("token_url")
    auth_cfg = recieved_cont.get("class", {})
    
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

    # 3. Encrypt and update the vault dictionary
    try:
        # Inside your callback endpoint after getting 'tokens' from the response:
        expires_in = tokens.get("expires_in", 3600)
        token_bundle = {
            "access_token": tokens.get("access_token"),
            "refresh_token": tokens.get("refresh_token"),
            "expires_at": time.time() + expires_in,
            "token_url": recieved_cont.get("token_url"),
            "client_id": auth_cfg.get("CLIENT_ID"),
            "client_secret": auth_cfg.get("CLIENT_SECRET"),
        }
        print(f"token:               {token_bundle}")
        # Encrypt the complete dictionary blob
        encrypted_blob = encrypt_value(value=json.dumps(token_bundle), fernet=crypto_engine)
        vault_data[app_name] = encrypted_blob
        
        # Save back to Database
        db.save_vault(client_name, vault_data)

        print(f"✅ Vault updated in DB for {client_name} -> {app_name}")

    except Exception as e:
        return {"status": "error", "message": f"DB Save failed: {e}"}

    background_tasks.add_task(stop_server)
    return {
        "status": "success", 
        "message": f"Authentication for {app_name} successful! Data saved to Piper Vault."
    }

async def start_auth_flow(_cont, _crypto_engine):
    global server_instance
    
    # ✅ Check DB instead of local file
    current_vault = db.get_vault(_cont['client_name'])
    if current_vault.get(_cont["app_name"]):
        print(f"✅ Token for {_cont['app_name']} already exists in DB. Skipping auth.")
        return

    raw_auth_link = _cont.get("auth_link")
    auth_data = _cont.get("class")
    encoded_data = auth_data.copy()

    # Encode the scopes (converts spaces to %20)
    if "scopes" in encoded_data:
        encoded_data["scopes"] = urllib.parse.quote(encoded_data["scopes"])

    # Now format using the safe data
    auth_link = raw_auth_link.format(**encoded_data)

    print(f"\n--- PHASE 1: {_cont['app_name']} Authentication ---")
    
    app.state.cont = _cont
    app.state.crypto_engine = _crypto_engine

    # Browser logic remains the same
    current_os = platform.system().lower()
    is_docker = os.path.exists('/.dockerenv')
    
    db.create_intervention(_cont['client_name'], _cont['app_name'], auth_link)

    if current_os == "windows" and not is_docker:
        webbrowser.open(auth_link)
    else:
        print(f"🔗 ACTION REQUIRED: Open this URL:\n\n{auth_link}\n")
        try: webbrowser.open(auth_link)
        except: pass

    config = uvicorn.Config(app, host="0.0.0.0", port=8080, loop="asyncio")
    server_instance = uvicorn.Server(config)
    await server_instance.serve()