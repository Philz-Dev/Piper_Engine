import docker
import redis
import time
import os
import json

# Setup
client = docker.from_env()
r = redis.Redis(host='redis-broker', port=6379, decode_responses=True)
MAX_WORKERS = int(os.getenv("MAX_WORKERS", 5))

def monitor_and_spawn():
    print(f"🕵️ Controller started. Max capacity: {MAX_WORKERS} workers.")
    database_url = os.getenv("DATABASE_URL")
    master_password = os.getenv("MASTER_PASSWORD")
    host_path = os.getenv("HOST_PROJECT_PATH", "/app")
    
    while True:
        # 1. Count ONLY our workers (using the Label we discussed!)
        active_workers = client.containers.list(filters={"label": "service=piper-worker"})
        current_count = len(active_workers)
        
        if current_count < MAX_WORKERS:
            # 2. 'Pop' the task. This deletes it from Redis immediately.
            # blpop(queue_name, timeout) - it waits until a task appears!
            result = r.blpop("task_queue", timeout=5)
            
            if result:
                queue_name, task_str = result
                print(f"📦 Task received! Spawning worker {current_count + 1}/{MAX_WORKERS}")
                
                # 3. Spawn the Worker with all the "Compose" bells and whistles
                try:
                    task_dict = json.loads(task_str)
                    client_name = task_dict.get("client_id", "unknown")
                    client.containers.run(
                        image="ghcr.io/philz-dev/piper-worker:v1",
                        name=f"{client_name}_worker_{int(time.time())}", # Unique name
                        labels={"service": "piper-worker"},
                        detach=True,
                        auto_remove=True, # Dies immediately when finished
                        
                        # --- THE DNS SETTINGS ---
                        dns=["8.8.8.8", "1.1.1.1"],
                        
                        # --- THE NETWORK ---
                        network="piper-network",
                        
                        # --- THE PORTS ---
                        # Format: { container_port: host_port }
                        # Note: If running multiple workers, they can't all use 8080!
                        # You might want to leave this out for workers and only use it for the Webhook Engine.
                        #ports={'8080/tcp': None}, 

                        # --- THE ENVIRONMENT ---
                        environment={
                            "TASK_DATA": task_str,
                            "CLIENT_NAME": client_name,
                            "MASTER_PASSWORD": master_password,
                            "DATABASE_URL": database_url,
                            "PYTHONPATH": "/app"
                        },

                        # --- THE VOLUMES (The tricky part) ---
                        volumes={
                            f"{host_path}/templates/{client_name}/.piper_vault": {'bind': '/app/.piper_vault', 'mode': 'rw'},
                            f"{host_path}/templates/{client_name}/.env": {"bind": "/app/.env", "mode": "rw"},
                            'piper_storage': {'bind': '/app/piper_storage', 'mode': 'rw'}
                        }
                    )
                    print(f"🚀 Worker {client_name} spawned with full config.")
                except Exception as e:
                    print(f"❌ SDK Spawn Error: {e}")
        else:
            # VPS is full! Wait a bit before checking if a worker finished
            time.sleep(2)

    

if __name__ == "__main__":
    monitor_and_spawn()