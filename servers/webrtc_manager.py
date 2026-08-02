import json
import asyncio
import socketio
import logging
import requests
import aioice  # Imported to force port boundaries

import json
import asyncio
import socketio
import logging
import requests
import sys

# 1. Force the range directly into the base module
import aioice
custom_range = range(50000, 50011)
aioice.ice.PORT_RANGE = custom_range

# 2. If aiortc or aioice submodules were already loaded elsewhere, overwrite them in sys.modules
if "aioice.ice" in sys.modules:
    sys.modules["aioice.ice"].PORT_RANGE = custom_range

# 3. Now load aiortc safely
from aiortc import RTCPeerConnection, RTCConfiguration, RTCIceServer, RTCSessionDescription, RTCIceCandidate
from aiortc.sdp import candidate_from_sdp

# 4. Force-patch aiortc's internal reference just in case it copied it early
import aiortc.rtcicetransport
if hasattr(aiortc.rtcicetransport, "aioice"):
    aiortc.rtcicetransport.aioice.ice.PORT_RANGE = custom_range

# 3. NOW it is safe to import aiortc. It will consume your patched range.
from aiortc import RTCPeerConnection, RTCConfiguration, RTCIceServer, RTCSessionDescription, RTCIceCandidate
from shared.engine_server_utils import PiperService
from shared.database_manager import ContextDB

class WebRTCManager:
    def __init__(self, room_id):
        self.room_id = room_id
        self.pc = None
        self.sio = socketio.AsyncClient()
        self.logger = logging.getLogger("uvicorn.error")
        self.piper_service = PiperService()
        self.db = ContextDB()

        # Signaling setup
        self.sio.on('offer', self.on_offer)
        self.sio.on('ice_candidate', self.on_ice_candidate)

    async def get_turn_credentials(self):
        """Fetches fresh credentials directly from Metered cleanly without blocking the loop."""
        url = "https://stretis.metered.live/api/v1/turn/credentials?apiKey=138d4cb6f3973cf4fac419d02d6a77a08072"
        try:
            # Offload the blocking requests call to a worker thread
            response = await asyncio.to_thread(requests.get, url, timeout=5)
            if response.status_code == 200:
                return response.json()  # Returns list of dicts with urls, username, credential
        except Exception as e:
            self.logger.error(f"❌ Failed to fetch dynamic TURN credentials: {e}")
        return None

    async def start_signaling(self, signaling_url):
        await self.sio.connect(signaling_url)
        await self.sio.emit("join_room", {"room_id": self.room_id})

    async def on_offer(self, data):
        sender_sid = data['sid']
        offer_payload = data['offer']
        
        # Build ice servers array dynamically
        ice_servers = [RTCIceServer(urls="stun:stun.l.google.com:19302")]
        
        # Fetch fresh TURN servers dynamically
        turn_credentials = await self.get_turn_credentials()
        
        if turn_credentials and isinstance(turn_credentials, list):
            self.logger.info("✅ Dynamically injected fresh Metered TURN credentials.")
            for server in turn_credentials:
                ice_servers.append(RTCIceServer(
                    urls=server.get("urls"),
                    username=server.get("username"),
                    credential=server.get("credential")
                ))
        else:
            # Fallback static configuration if API fails to load
            self.logger.warning("⚠️ TURN API failed or timed out. Falling back to static configuration.")
            ice_servers.extend([
                RTCIceServer(
                    urls="turn:standard.relay.metered.ca:80",
                    username="59075126c3919d701174b3d1",
                    credential="GcCEm2e2s7//WL2E"
                ),
                RTCIceServer(
                    urls="turn:standard.relay.metered.ca:443",
                    username="59075126c3919d701174b3d1",
                    credential="GcCEm2e2s7//WL2E"
                ),
                RTCIceServer(
                    urls="turn:standard.relay.metered.ca:443?transport=tcp",
                    username="59075126c3919d701174b3d1",
                    credential="GcCEm2e2s7//WL2E"
                )
            ])

        # Initialize peer connection with compiled configurations
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=ice_servers))

        @self.pc.on("datachannel")
        def on_datachannel(channel):
            self.logger.info(f"DataChannel Opened: {channel.label}")
            
            if channel.label == "logs":
                asyncio.create_task(self.logs_loop(channel, data.get('client_id'), data.get('task_id')))
            elif channel.label == "stats":
                asyncio.create_task(self.stats_loop(channel, data.get('client_name')))
            elif channel.label == "control":
                @channel.on("message")
                def on_message(raw_msg):
                    asyncio.create_task(self.handle_message(raw_msg, channel))

        # Register ICE candidate handler
        @self.pc.on("icecandidate")
        async def on_icecandidate(event):
            if event.candidate:
                await self.sio.emit(
                    "ice_candidate",
                    {
                        "room_id": self.room_id,
                        "target_sid": sender_sid,
                        "candidate": event.candidate,
                    },
                )

        await self.pc.setRemoteDescription(
            RTCSessionDescription(
                sdp=offer_payload["sdp"],
                type=offer_payload["type"]
            )
        )

        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)

        await self.sio.emit('answer', {"target_sid": sender_sid, "answer": {"sdp": self.pc.localDescription.sdp, "type": "answer"}})

    async def on_ice_candidate(self, data):
        if not self.pc or not data:
            return
            
        candidate_data = data.get('candidate')
        if not candidate_data:
            return

        # Handle browser signaling completion (null candidate)
        if isinstance(candidate_data, dict) and not candidate_data.get("candidate"):
            try:
                await self.pc.addIceCandidate(None)
                self.logger.info("ℹ️ Received null candidate (ICE gathering complete).")
            except Exception as e:
                self.logger.debug(f"Handling end-of-candidates: {e}")
            return

        if isinstance(candidate_data, dict):
            sdp_mid = candidate_data.get("sdpMid")
            sdp_mline_index = candidate_data.get("sdpMLineIndex")
            raw_candidate_str = candidate_data.get("candidate")

            if not raw_candidate_str:
                return

            try:
                clean_candidate = raw_candidate_str.replace("candidate:", "").strip()
                candidate = candidate_from_sdp(clean_candidate)
                
                candidate.sdpMid = sdp_mid
                candidate.sdpMLineIndex = sdp_mline_index

                await self.pc.addIceCandidate(candidate)
                self.logger.info(f"✅ Added ICE candidate from browser: {candidate.ip}:{candidate.port}")
                
            except Exception as e:
                self.logger.error(f"❌ Failed to parse/add ICE candidate: {e}")
        else:
            try:
                await self.pc.addIceCandidate(candidate_data)
            except Exception as e:
                self.logger.error(f"❌ Failed to add raw candidate fallback: {e}")

    # --- Message Handler ---
    async def handle_message(self, raw_message, channel):
        """Receives and routes the command."""
        try:
            msg = json.loads(raw_message)
            action = msg.get("action")
            payload = msg.get("payload", {})
            request_id = msg.get("request_id")

            result = await self.dispatch(action, payload)
            
            channel.send(json.dumps({"request_id": request_id, "data": result}))
        except Exception as e:
            channel.send(json.dumps({"error": str(e), "request_id": request_id}))

    async def dispatch(self, action, payload):
        if action == "unlock":
            return self.piper_service.unlock(password=payload.get("password"))
        elif action == "toggle":
            return await self.piper_service.toggle_container(
                container_name=payload.get("container_name"),
                action=payload.get("action"),
                client_name=payload.get("client_name")
            )
        elif action == "get_automations":
            return self.piper_service.get_automations(payload.get("client_name"))
        elif action == "get_clients":
            return self.piper_service.list_clients()
        elif action == "resolve_intervention":
            return await asyncio.to_thread(self.db.mark_intervention_resolved, payload.get("id"))
        elif action == "delete_automation":
            return await self.piper_service.delete_automation(
                client_name=payload.get("client_name"), 
                container_name=payload.get("container_name")
            )
        elif action == "get_status":
            return self.piper_service.get_status()
        return {"error": "Unknown action"}

    # --- Replicating your original WebSocket Loops ---
    async def logs_loop(self, channel, client_id, task_id):
        from main import DB 
        initial_data = await asyncio.to_thread(DB.get_latest_logs_for_task, client_id, task_id)
        channel.send(json.dumps({"type": "init", "data": initial_data}))
        
        last_log_count = len(initial_data.get('logs', []))
        try:
            while channel.readyState == "open":
                current_count = await asyncio.to_thread(self.db.get_log_count, client_id, task_id)
                if current_count > last_log_count:
                    data = {
                        "type": "update",
                        "data": {
                            "execution_logs": await asyncio.to_thread(self.db.get_latest_logs_for_task, client_id, task_id),
                            "validation_logs": await asyncio.to_thread(self.db.get_validation_logs, client_id, task_id)
                        }
                    }
                    channel.send(json.dumps(data))
                    last_log_count = current_count
                await asyncio.sleep(1)
        except Exception as e:
            self.logger.error(f"Logs Channel Error: {e}")

    async def stats_loop(self, channel, client_name):
        while channel.readyState == "open":
            try:
                stats_payload = {
                    "total": await asyncio.to_thread(self.piper_service.get_global_stats_sync),
                    "grouped": await asyncio.to_thread(self.piper_service.get_grouped_client_stats_sync, client_name),
                    "client_stat": await asyncio.to_thread(self.piper_service.get_total_client_stats_sync, client_name),
                    "interventions": await asyncio.to_thread(self.db.get_pending_interventions)
                }
                channel.send(json.dumps(stats_payload))
            except Exception as e:
                self.logger.error(f"Stats Channel Error: {e}")
            await asyncio.sleep(2)