import time
import os
import datetime
from pyngrok import ngrok
from shared.database_manager import ContextDB 

TOKEN = os.getenv("INSTALL_TOKEN")
API_URL = os.getenv("PIPER_CLOUD_URL", "https://your-cloud-domain.com") + "/api/v1/engine/register"

def get_active_tunnel_url():
    """Fetches the public URL from the currently running Ngrok tunnel."""
    try:
        tunnels = ngrok.get_tunnels()
        if not tunnels:
            print("⚠️ No active Ngrok tunnels found.")
            return None
        # Return the public URL of the first tunnel
        return tunnels[0].public_url
    except Exception as e:
        print(f"⚠️ Error fetching Ngrok tunnel: {e}")
        return None

def smart_heartbeat():
    db = ContextDB()
    db.initialize_metadata_table() 
    
    print(f"🚀 Piper Heartbeat started for token: {TOKEN}")

    while True:
        try:
            # 1. Get the current Ngrok Tunnel URL
            current_url = get_active_tunnel_url()
            
            if current_url:
                # 2. Compare with stored value using the DB manager
                # (Note: We are using get_stored_ip, but it now stores the URL)
                last_known_url = db.get_stored_ip()
                
                if current_url != last_known_url:
                    print(f"🔄 Tunnel Change detected! {last_known_url} -> {current_url}")
                    
                    payload = {
                        "token": TOKEN,
                        "ip_address": current_url, # Storing URL in the ip_address field
                        "status": "active",
                        "port": 443, # Ngrok uses 443 for HTTPS
                        "last_ping": datetime.datetime.utcnow().isoformat()
                    }

                    # Using requests.post to notify your cloud dashboard
                    import requests
                    response = requests.post(API_URL, json=payload, timeout=10)
                    
                    if response.status_code == 200:
                        db.update_stored_ip(current_url)
                        print("✅ Cloud Dashboard updated with new Ngrok URL.")
                    else:
                        print(f"❌ Failed to update Cloud. Status: {response.status_code}")
            
            else:
                print("⏳ Waiting for Ngrok tunnel to establish...")
            
        except Exception as e:
            print(f"⚠️ Unexpected error: {e}")
            
        time.sleep(60)

if __name__ == "__main__":
    if not TOKEN:
        print("❌ Error: INSTALL_TOKEN environment variable not set.")
    else:
        smart_heartbeat()