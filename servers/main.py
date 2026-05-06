from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import docker
import uvicorn
import os
import yaml
import subprocess
import glob
import hashlib
import base64
from typing import List, Dict
from shared.encryption_manager import verify_password, initialize_salt, MASTER_SALT, CONFIG_DIR
from shared.setup_build import execute_piper_start

client = docker.from_env()
app = FastAPI(title="Piper Engine API")

# Configuration
PROJECT_ROOT = "/app"
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")
WATERFALL_DIR = os.path.join(PROJECT_ROOT, "waterfall")
MASTER_PASSWORD = None  # Persistent within the session

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/v1/status")
async def get_status():
    """
    locked: True if the current session doesn't have the password.
    exists: True if a master password has been initialized in the CLI.
    """
    return {
        "locked": MASTER_PASSWORD is None,
        "exists": os.path.exists(MASTER_SALT)
    }

@app.post("/api/v1/unlock")
async def unlock_engine(payload: Dict[str, str]):
    global MASTER_PASSWORD
    pwd = payload.get("password")
    
    if not pwd:
        raise HTTPException(status_code=400, detail="Password required")
    
    # 1. Check if we need to CREATE a password
    if not os.path.exists(MASTER_SALT):
        if not os.path.exists(CONFIG_DIR):
            os.makedirs(CONFIG_DIR)
        initialize_salt(pwd)
        MASTER_PASSWORD = pwd
        return {"status": "created", "message": "Master password initialized"}

    # 2. Otherwise, VERIFY against the CLI manager logic
    if verify_password(pwd):
        MASTER_PASSWORD = pwd
        return {"status": "unlocked", "message": "Access granted"}
    else:
        # feedback for the UI to display "wrong or incorrect password"
        raise HTTPException(status_code=401, detail="Incorrect Master Password")

@app.get("/api/v1/clients")
async def get_clients():
    if MASTER_PASSWORD is None:
        raise HTTPException(status_code=401, detail="Locked")
    try:
        if not os.path.exists(TEMPLATES_DIR):
            return []
        return [d for d in os.listdir(TEMPLATES_DIR) if os.path.isdir(os.path.join(TEMPLATES_DIR, d))]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/automations/{client_name}")
async def get_automations(client_name: str):
    if MASTER_PASSWORD is None:
        raise HTTPException(status_code=401, detail="Locked")
        
    automations = []
    client_path = os.path.join(TEMPLATES_DIR, client_name, "waterfall")
    
    if not os.path.exists(client_path):
        raise HTTPException(status_code=404, detail="Client templates not found")

    running_containers = {c.name: c.status for c in client.containers.list(all=True)}

    for file in os.listdir(client_path):
        if file.endswith(('.yml', '.yaml')):
            file_path = os.path.join(client_path, file)
            with open(file_path, 'r') as f:
                try:
                    config = yaml.safe_load(f)
                    name = config.get('name', file.replace('.yml', ''))
                    status = running_containers.get(name, "stopped")
                    
                    automations.append({
                        "id": name,
                        "name": name,
                        "status": status,
                        "file_path": file_path,
                        "cpu": "0%",
                        "mem": "0B"
                    })
                except yaml.YAMLError:
                    continue
    return automations

@app.post("/api/v1/toggle/{container_name}")
async def toggle_container(
    container_name: str, 
    action: str = Query(...), 
    client_name: str = Query(...)
):
    global MASTER_PASSWORD
    if not MASTER_PASSWORD:
        raise HTTPException(status_code=401, detail="Engine is locked.")

    try:
        if action == "start":
            # Direct Python Call
            success, message = await execute_piper_start(
                clients=[client_name], 
                dsl=[f"{container_name}.yml"], 
                password=MASTER_PASSWORD
            )
            if not success:
                raise HTTPException(status_code=500, detail=message)
            return {"status": "success", "message": message}

        else:
            # Stop logic still uses subprocess (unless you extract stop logic too)
            command = f"piper stop {container_name}"
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            
            if result.returncode != 0:
                raise HTTPException(status_code=500, detail=result.stderr)

            return {"status": "success", "output": result.stdout}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
def start_server(port: int=8099):
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    start_server()