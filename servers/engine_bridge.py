import asyncio
import websockets
import json
import logging
import time

# Import your existing service to execute commands
# from shared.engine_server_utils import PiperService 

logger = logging.getLogger("bridge")

class PiperBridge:
    def __init__(self, backend_url, api_key):
        self.backend_url = backend_url
        self.api_key = api_key
        # piper_services = PiperService() # You already have this in main.py

    async def listen(self):
        """Main loop that keeps the connection alive."""
        while True:
            try:
                uri = f"{self.backend_url}?key={self.api_key}"
                async with websockets.connect(uri) as websocket:
                    logger.info("✅ Connected to Central Backend")
                    
                    while True:
                        # Wait for command from central server
                        message = await websocket.recv()
                        data = json.loads(message)
                        
                        # Command structure: {"action": "START", "params": {...}}
                        action = data.get("action")
                        
                        if action == "PING":
                            await websocket.send(json.dumps({"status": "PONG"}))
                            continue
                            
                        # Execute command using your existing PiperService logic
                        # result = await piper_services.execute(data)
                        print(f"🚀 Received Action: {action}")
                        
                        # Send status back to UI
                        await websocket.send(json.dumps({"status": "SUCCESS", "message": "Command processed"}))

            except (websockets.ConnectionClosed, Exception) as e:
                logger.error(f"❌ Connection lost: {e}. Retrying in 5 seconds...")
                await asyncio.sleep(5)

# How to run this alongside your FastAPI app:
# Add this to your main.py startup logic:
# asyncio.create_task(PiperBridge("wss://your-backend.com/ws/engine", "SECRET_KEY").listen())