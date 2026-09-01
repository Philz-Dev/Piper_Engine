from fastapi import FastAPI, HTTPException, Query, Response, Request
from fastapi.middleware.cors import CORSMiddleware
import docker
import uvicorn
import os
import yaml
import sys
root_path = os.path.dirname(os.path.abspath(__file__))
if root_path not in sys.path:
    sys.path.append(root_path)

import subprocess
import glob
import hashlib
import base64
from typing import List, Dict
from shared.encryption_manager import verify_password, initialize_salt, MASTER_SALT, CONFIG_DIR
from shared.setup_build import execute_piper_start, execute_piper_stop
from shared.engine_server_utils import PiperService
from shared.database_manager import ContextDB
import logging
from sqlalchemy import text
import asyncio
from fastapi import WebSocket, WebSocketDisconnect
import json


# --- Inside main.py ---

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="Piper Engine API")
piper_services = PiperService()
DB = ContextDB
MASTER_PASSWORD = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "https://www.stretis.com",],  # For development, allow everything
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_private_network_headers(request: Request, call_next):
    # Handle preflight OPTIONS request
    if request.method == "OPTIONS":
        response = Response()
        response.headers["Access-Control-Allow-Origin"] = request.headers.get("origin", "https://www.stretis.com")
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        # This header is the magic bullet for PNA
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response

    response = await call_next(request)
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response

@app.websocket("/ws/logs/{client_id}/{task_id}")
async def logs_websocket(websocket: WebSocket, client_id: str, task_id: str):
    await websocket.accept()
    
    # Initial setup: Get initial data AND initial count
    initial_data = await asyncio.to_thread(DB.get_latest_logs_for_task, client_id, task_id)
    await websocket.send_json({"type": "init", "data": initial_data})
    
    # Store just the integer count
    last_log_count = len(initial_data.get('logs', []))

    try:
        while True:
            # OPTIMIZATION: Only fetch the count first
            current_count = await asyncio.to_thread(DB.get_log_count, client_id, task_id)

            if current_count > last_log_count:
                # ONLY now do we fetch the heavy payload
                current_logs = await asyncio.to_thread(DB.get_latest_logs_for_task, client_id, task_id)
                current_validation = await asyncio.to_thread(DB.get_validation_logs, client_id, task_id)
                
                await websocket.send_json({
                    "type": "update", 
                    "data": {
                        "execution_logs": current_logs,
                        "validation_logs": current_validation
                    }
                })
                last_log_count = current_count
            
            await asyncio.sleep(1) # Frequency is fine now because the check is lightweight
            
    except WebSocketDisconnect:
        logger.info(f"Log WebSocket disconnected for {task_id}")
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")

@app.websocket("/ws/stats/{client_name}")
async def stats_websocket(websocket: WebSocket, client_name: str):
    await websocket.accept()
    try:
        # 2. Use a timeout for the blocking Docker calls
        # This prevents the loop from hanging if Docker is unresponsive
        total_stats = await asyncio.wait_for(asyncio.to_thread(piper_services.get_global_stats_sync), timeout=3.0)
        grouped_stats = await asyncio.to_thread(piper_services.get_grouped_client_stats_sync, client_name)
        client_stats = await asyncio.to_thread(piper_services.get_total_client_stats_sync, client_name)
        interventions = await asyncio.to_thread(DB.get_pending_interventions)

        # 3. Push
        await websocket.send_json({
            "total": total_stats,
            "grouped": grouped_stats,
            "client_stat": client_stats,
            "interventions": interventions
        })
    except asyncio.TimeoutError:
        logger.error("Docker stats call timed out")
    except Exception as e:
        logger.error(f"Error in stats loop: {e}")
        # Don't break the loop, just wait and retry
        
        await asyncio.sleep(2) # Increased to 2s to reduce Docker load
        
    except WebSocketDisconnect:
        logger.info(f"Stats WebSocket disconnected for {client_name}")
    except Exception as e:
        logger.error(f"WebSocket Fatal Error: {e}")

@app.post("/api/v1/resolve-intervention/{intervention_id}")
async def resolve_intervention(intervention_id: int):
    """Called by the UI after the OAuth popup closes."""
    try:
        # Assuming you added the method to DB as discussed
        await asyncio.to_thread(DB.mark_intervention_resolved, intervention_id)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/automations/{client_name}/{container_name}")
async def delete_automation(client_name: str, container_name: str):
    # This now properly awaits the async method in your service
    return await piper_services.delete_automation(client_name, container_name)

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
    
    try:
        return piper_services.unlock(password=pwd)
    except HTTPException as he:
        raise he

@app.get("/api/v1/clients")
async def get_clients():
    return piper_services.list_clients()


@app.get("/api/v1/automations/{client_name}")
async def get_automations(client_name: str):
    return piper_services.get_automations(client_name=client_name)

@app.post("/api/v1/toggle/{container_name}")
async def toggle_container(
    container_name: str, 
    action: str = Query(...), 
    client_name: str = Query(...)
): 
    try:
        return await piper_services.toggle_container(container_name=container_name, action=action, client_name=client_name)
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
"""def get_client_memory_usage(client_name):
    # 1. Get registry
    registry = r.hgetall("worker_registry")
    
    # 2. Filter for containers currently working for THIS client
    busy_workers = []
    for worker_name, status_json in registry.items():
        status = json.loads(status_json)
        if status['status'] == 'busy' and status['client_id'] == client_name:
            busy_workers.append(worker_name)
    
    # 3. Aggregate Docker stats
    total_mem = 0
    for w_name in busy_workers:
        container = client.containers.get(w_name)
        stats = container.stats(stream=False)
        total_mem += stats['memory_stats']['usage']
        
    return total_mem"""
    
def start_server(port: int=8099):
    uvicorn.run(app, host="0.0.0.0", port=port)
