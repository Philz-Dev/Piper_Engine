import socketio
from typing import Dict
import json

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins="*")

# 1. Existing WebRTC Storage
active_rooms: Dict[str, list] = {}

# 2. New Controller-Agent Storage
connected_workers: Dict[str, str] = {} # {user_id: sid}
# Tracks: { task_id: frontend_sid }
pending_tasks = {}

# --- CONTROLLER-AGENT BRIDGE ---

@sio.event
async def register_worker(sid, data):
    """Local agents call this to announce they are online."""
    user_id = data.get('user_id')
    if user_id:
        connected_workers[user_id] = sid
        print(f"✅ Worker Registered: {user_id} (SID: {sid})")
        await sio.emit('status', {'message': 'registered'}, to=sid)

# --- ROUTING LOGIC ---

@sio.on('execute_task')
async def handle_execute_task(sid, data):
    print(f"📦 Payload received from Frontend: {json.dumps(data, indent=2)}")
    
    # SAVE THE ORIGINATOR: Map this task_id to the UI's current sid
    task_id = data.get('task_id')
    pending_tasks[task_id] = sid
    
    user_id = data.get('userId')
    target_sid = connected_workers.get(user_id)
    
    if target_sid:
        await sio.emit('execute_task', data, to=target_sid)
    else:
        # If engine offline, clean up the pending task
        pending_tasks.pop(task_id, None) 
        await sio.emit('task_response', {
            "status": "ERROR", 
            "message": "Engine is offline", 
            "task_id": task_id
        }, to=sid)

# --- WEBRTC SIGNALING ---

@sio.event
async def connect(sid, environ, auth=None):
    print(f"Client connected: {sid}")
    if auth:
        print(f"Auth data received: {auth}")

@sio.on('join_user_room')
async def join_user_room(sid, data):
    """The UI calls this on mount to create a private response channel."""
    user_id = data.get('user_id')
    if user_id:
        await sio.enter_room(sid, user_id)
        print(f"✅ UI User joined room: {user_id}")

@sio.event
async def join_room(sid, data):
    room_id = data.get("room_id")
    await sio.enter_room(sid, room_id)
    
    if room_id not in active_rooms:
        active_rooms[room_id] = []
    
    existing_peers = [peer for peer in active_rooms[room_id] if peer != sid]
    
    if sid not in active_rooms[room_id]:
        active_rooms[room_id].append(sid)
        
    print(f"Client {sid} joined room {room_id}")
    await sio.emit("user-joined", {"sid": sid}, room=room_id, skip_sid=sid)
    await sio.emit("room_users", {"peers": existing_peers}, to=sid)

@sio.event
async def offer(sid, data):
    target_sid = data.get("target_sid")
    room_id = data.get("room_id")
    # ... (Keep your existing offer/answer/ice logic here) ...
    # (Removed for brevity, keep your original code)

# --- ADD THESE TO YOUR SCRIPT ---

@sio.event
async def answer(sid, data):
    """Relay the SDP Answer to the correct target."""
    target_sid = data.get("target_sid")
    print(f"🔄 Relaying Answer to {target_sid}")
    await sio.emit("answer", {"sdp": data["sdp"], "sender_sid": sid}, to=target_sid)

@sio.event
async def candidate(sid, data):
    """Relay the ICE Candidate to the correct target."""
    target_sid = data.get("target_sid")
    await sio.emit("candidate", {"candidate": data["candidate"], "sender_sid": sid}, to=target_sid)

@sio.on('task_response')
async def handle_task_response(sid, data):
    """
    Worker sends result to Hub.
    Hub forwards it to the specific room (user_id) the UI is listening to.
    """
    user_id = data.get('userId') # Ensure your worker sends the userId in the response
    task_id = data.get('task_id')
    
    # Forward to the room named after the user
    await sio.emit('task_response', data, room=user_id)
    print(f"🔄 Routed Task {task_id} response to Room {user_id}")

# --- DISCONNECT HANDLING ---

@sio.event
async def disconnect(sid):
    # 1. Clean up WebRTC Rooms
    for room_id, sids in list(active_rooms.items()):
        if sid in sids:
            sids.remove(sid)
            await sio.emit("user-disconnected", {"sid": sid}, room=room_id)
            if not sids:
                del active_rooms[room_id]
            break

    # 2. Clean up Controller-Agent Sessions
    for user_id, registered_sid in list(connected_workers.items()):
        if registered_sid == sid:
            del connected_workers[user_id]
            print(f"❌ Worker Disconnected: {user_id}")
            break

    print(f"Client disconnected: {sid}")