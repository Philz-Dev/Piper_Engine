import webbrowser
import requests
import uvicorn
import os
import signal
from fastapi import FastAPI, Query, BackgroundTasks
from functools import partial
import sys
import json

app = FastAPI()
_cont = sys.argv[1]
recieved_cont = json.loads(_cont)
# --- CONFIGURATION ---

def shutdown():
    """Logic to kill the server process gracefully"""
    os.kill(os.getpid(), signal.SIGINT)

@app.get("/callback")
async def callback(background_tasks: BackgroundTasks, code: str = Query(None)):
    # 1. Catch the 'code' from the browser redirect
    if not code:
        return {"status": "error", "message": "No code found"}

    # 2. Exchange 'code' for 'tokens' (The Handshake)
    token_url = recieved_cont.get("token_url")
    config = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": recieved_cont["auth_config"].get("CLIENT_ID"),
        "client_secret": recieved_cont["auth_config"].get("CLIENT_SECRET"),
        "redirect_uri": recieved_cont["auth_config"].get("REDIRECT_URI")
    }
    
    response = requests.post(token_url, data=config)
    tokens = response.json()
    with open(r"templates\client_temp\auth_config.json", "r") as file:
        data = json.load(file)

    data["CRED"] = tokens
    with open(r"templates\client_temp\auth_config.json", "w") as f:
        json.dump(data, f, indent=4)

    # 3. Save to Vault
    # This is where you'd call your encryption/save logic
    print(f"DEBUG: Received token {tokens.get('access_token')[:10]}...")

    # 4. AUTO-SHUTDOWN: Tell the server to die in 2 seconds
    # This allows the browser to show the "Success" message first
    background_tasks.add_task(shutdown)
    
    return {
        "status": "success", 
        "message": "Vault updated. This server is now shutting down..."
    }

def start_auth_flow():
    # Construct the Typeform URL
    # Pop the browser

    raw_auth_link = recieved_cont.get("auth_link")
    auth_link = raw_auth_link.format(**recieved_cont.get("auth_config"))
    webbrowser.open(auth_link)

    #Start the server (This blocks the script until shutdown is called)
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="error")

start_auth_flow()