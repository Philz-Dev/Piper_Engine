import os
import asyncio
import json
import logging
import websockets
import uvicorn
from api_server import app 
from shared.engine_server_utils import PiperService   #Ensure you import your 'app' and 'piper_services'

# --- Configuration ---
ENGINE_MODE = os.getenv("ENGINE_MODE", "local")
SIGNALING_SERVER_URL = os.getenv("SIGNALING_SERVER_URL", "wss://piper-backend-production.up.railway.app/ws/engine")
API_KEY = os.getenv("PIPER_API_KEY", "your-secret-key-here")
USER_ID = os.getenv("USER_ID", "default_user_123")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator")

import socketio # Make sure you have this installed

class PiperBridge:
    def __init__(self, backend_url, api_key, user_id, piper_services):
        self.sio = socketio.AsyncClient()
        self.backend_url = backend_url
        self.api_key = api_key
        self.user_id = user_id
        self.piper_services = piper_services
        self.setup_handlers()

    async def listen(self):
        """Production-grade listener with robust reconnection loop."""
        while True:
            try:
                # 1. Pass API_KEY in 'auth'. This is safer and cleaner.
                await self.sio.connect(
                    self.backend_url, 
                    transports=['websocket'],
                    auth={"token": self.api_key} 
                )
                await self.sio.wait()
            except Exception as e:
                logger.error(f"Connection error: {e}. Retrying in 5s...")
                await asyncio.sleep(5)

    def setup_handlers(self):
        # Merge all handlers into one clean method
        @self.sio.event
        async def connect():
            logger.info("✅ Connected to Central Backend")
            await self.sio.emit('register_worker', {'user_id': self.user_id})

        @self.sio.event
        async def disconnect():
            logger.warning("❌ Disconnected from Central Backend")

        @self.sio.on('execute_task')
        async def on_execute(data):
            logger.info(f"🚀 Received command: {data}")
            method_name = data.get("method")
            params = data.get("params", {})
            task_id = data.get("task_id")

            allowed_methods = [
                "toggle_container", "delete_automation", "get_stats", 
                "list_clients", "get_automations", "resolve_intervention", 
                "get_script_content", "get_system_state", "get_file_tree"
            ]

            if method_name not in allowed_methods:
                await self.sio.emit('task_response', {
                    "status": "ERROR", 
                    "message": "Unauthorized method", 
                    "task_id": task_id,
                    "userId": self.user_id  # <--- Include userId here
                })
                return

            try:
                func = getattr(self.piper_services, method_name)
                
                if asyncio.iscoroutinefunction(func):
                    result = await func(**params)
                else:
                    result = await asyncio.to_thread(func, **params)
                
                # <--- INCLUDE userId HERE SO THE BACKEND CAN ROUTE IT TO THE ROOM --->
                print(f"result:                {result}")
                await self.sio.emit('task_response', {
                    "status": "SUCCESS", 
                    "task_id": task_id, 
                    "result": result,
                    "userId": self.user_id 
                })
            except Exception as e:
                logger.error(f"Error executing {method_name}: {e}")
                await self.sio.emit('task_response', {
                    "status": "ERROR", 
                    "task_id": task_id, 
                    "message": str(e),
                    "userId": self.user_id  # <--- Include userId here as well
                })


async def run_local_mode():
    """Runs the FastAPI server AND the WebSocket Bridge concurrently."""
    logger.info("💻 STRETIS ENGINE MODE: [LOCAL/BRIDGE]")
    
    # 1. Prepare FastAPI Server
    config = uvicorn.Config(app, host="0.0.0.0", port=8099, log_level="info")
    server = uvicorn.Server(config)
    
    piper_instance = PiperService()
    # 2. Prepare Bridge
    bridge = PiperBridge(SIGNALING_SERVER_URL, API_KEY, USER_ID, piper_instance)
    
    # 3. Run both
    await asyncio.gather(
        server.serve(),
        bridge.listen()
    )

if __name__ == "__main__":
    if ENGINE_MODE == "local":
        try:
            asyncio.run(run_local_mode())
        except KeyboardInterrupt:
            logger.info("🛑 Shutting down.")
    else:
        logger.info("☁️ STRETIS ENGINE MODE: [VPS/DIRECT-API]")
        # Standard Uvicorn run for VPS mode
        uvicorn.run(app, host="0.0.0.0", port=8099)