import os
import asyncio
from api_server import start_server
from webrtc_manager import WebRTCManager

ROOM_ID = os.getenv("NODE_ROOM_ID", "piper-engine-room-1")
ENGINE_MODE = os.getenv("ENGINE_MODE", "local")
SIGNALING_SERVER_URL = os.getenv("SIGNALING_SERVER_URL", "https://piper-backend-production.up.railway.app")

async def run_local_node():
    """Asynchronous runner that manages connection lifecycle and graceful shutdown."""
    print("💻 STRETIS ENGINE MODE: [LAPTOP/WEBRTC]")
    print(f"-> Connecting to signaling room '{ROOM_ID}' at {SIGNALING_SERVER_URL}...")
    
    # Instantiate WebRTC node runner
    webrtc_node = WebRTCManager(room_id=ROOM_ID)
    
    # Connect and join the signaling room
    try:
        await webrtc_node.start_signaling(SIGNALING_SERVER_URL)
    except Exception as e:
        print(f"❌ Failed to establish initial signaling connection: {e}")
        # Sleep briefly before exiting to prevent high-frequency Docker CPU thrashing on failure
        await asyncio.sleep(5)
        return

    # Yield control to the event loop momentarily to let the sio.connected state bind cleanly
    await asyncio.sleep(0.5)
    
    if webrtc_node.sio.connected:
        print("🚀 Node connected. Awaiting WebRTC offer from peer client...")
    else:
        print("⚠️ Warning: Socket connection status is pending or failed.")

    # Keep the node alive while our Socket.IO connection is active
    try:
        # A robust fallback: if sio isn't active yet, give it 10 seconds to handshake before dying
        grace_period = 10
        while webrtc_node.sio.connected or grace_period > 0:
            if not webrtc_node.sio.connected:
                grace_period -= 1
            else:
                # Reset grace period once we have a confirmed active connection
                grace_period = 10
                
            await asyncio.sleep(1)
            
        print("🔌 Lost connection to signaling server permanently.")
    except asyncio.CancelledError:
        print("⚡ Connection loop cancelled.")
    finally:
        # Graceful cleanup
        if hasattr(webrtc_node, 'pc') and webrtc_node.pc:
            print("🔌 Closing WebRTC peer connection...")
            try:
                await webrtc_node.pc.close()
            except Exception:
                pass
        if hasattr(webrtc_node, 'sio'):
            print("🔌 Disconnecting and cleaning up signaling client...")
            try:
                await webrtc_node.sio.disconnect()
            except Exception:
                pass

def run_orchestrator():
    if ENGINE_MODE == "local":
        try:
            # Modern, clean event loop runner (avoids deprecated get_event_loop() warnings)
            asyncio.run(run_local_node())
        except KeyboardInterrupt:
            print("\n🛑 Node engine shutting down safely.")
    else:
        print("☁️ STRETIS ENGINE MODE: [VPS/DIRECT-API]")
        print("-> Firing standard HTTP Uvicorn Server on Port 8099...")
        start_server()

if __name__ == "__main__":
    run_orchestrator()