import requests
import time
import os
import datetime

# Configuration from environment variables
TOKEN = os.getenv("INSTALL_TOKEN")
# Your Next.js registration endpoint
API_URL = os.getenv("PIPER_CLOUD_URL", "https://your-cloud-domain.com") + "/api/v1/engine/register"

def smart_heartbeat():
    last_known_ip = None
    print(f"🚀 Piper Heartbeat started for token: {TOKEN}")

    while True:
        try:
            # 1. Get current public IP (fast and external)
            # Using a timeout ensures the script doesn't hang if the internet is shaky
            current_ip = requests.get("https://api.ipify.org", timeout=10).text.strip()
            
            # 2. Check if we need to update the Cloud Dashboard
            # Logic: Update if it's the first run (None) OR if the IP actually changed
            if current_ip != last_known_ip:
                if last_known_ip is not None:
                    print(f"🔄 IP Change detected! {last_known_ip} -> {current_ip}")
                else:
                    print(f"📡 Initial registration at {current_ip}")

                payload = {
                    "token": TOKEN,
                    "ip_address": current_ip,
                    "status": "active",
                    "port": 8001 , # Keep your engine port consistent
                    "last_ping": datetime.utcnow().isoformat()
                }

                response = requests.post(API_URL, json=payload, timeout=10)
                
                if response.status_code == 200:
                    last_known_ip = current_ip
                    print("✅ Cloud Dashboard updated successfully.")
                else:
                    print(f"❌ Failed to update Cloud. Status: {response.status_code}")
            
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Network error: Could not reach IP service or Cloud API. Retrying...")
        except Exception as e:
            print(f"⚠️ Unexpected error: {e}")
            
        # 3. Wait 2 minutes before checking again
        # This provides a max "down time" of 120 seconds if an IP changes
        time.sleep(120)

if __name__ == "__main__":
    if not TOKEN:
        print("❌ Error: INSTALL_TOKEN environment variable not set.")
    else:
        smart_heartbeat()