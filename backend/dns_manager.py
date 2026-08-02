import requests

class DNSManager:
    def __init__(self, zone_id, api_token):
        self.zone_id = zone_id
        self.base_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }

    def create_subdomain(self, subdomain, vps_ip):
        """Creates an A record in Cloudflare pointing to the VPS IP."""
        payload = {
            "type": "A",
            "name": subdomain,  # e.g., 'client1'
            "content": vps_ip,  # e.g., '123.45.67.89'
            "ttl": 1,           # 1 = Automatic
            "proxied": True     # True = Orange Cloud
        }
        
        response = requests.post(self.base_url, json=payload, headers=self.headers)
        return response.json()

# Example Usage:
# dns = DNSManager("your_zone_id_here", "your_api_token_here")
# dns.create_subdomain("client1", "123.45.67.89")