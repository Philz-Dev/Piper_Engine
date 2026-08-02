// lib/piperClient.ts
export type ConnectionMode = 'cloud' | 'local';

export class PiperClient {
  mode: ConnectionMode;
  connection: any; // WebSocket or RTCPeerConnection

  constructor(mode: ConnectionMode) {
    this.mode = mode;
  }

  // The UI calls this exactly the same way, regardless of transport
  async send(action: string, payload: any) {
    if (this.mode === 'local') {
      // Send via WebRTC DataChannel
      this.sendViaWebRTC(action, payload);
    } else {
      // Send via HTTP REST/WebSocket
      this.sendViaAPI(action, payload);
    }
  }

  // ... Implement transport-specific methods below
}