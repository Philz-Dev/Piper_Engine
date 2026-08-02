import docker
import redis
import time
import os
import json
import secrets

# Setup
client = docker.from_env()
r = redis.Redis(host='redis-broker', port=6379, decode_responses=True)
MAX_WORKERS = int(os.getenv("MAX_WORKERS", 5))

def generate_random_token(length=32):
    """Generates a secure hex token for webhook URLs."""
    return secrets.token_hex(length // 2)

def monitor_and_spawn():
    print(f"🕵️ Controller started. Max capacity: {MAX_WORKERS} workers.")
    
    # Existing variables from your env
    database_url = os.getenv("DATABASE_URL")
    master_password = os.getenv("MASTER_PASSWORD")
    host_path = os.getenv("HOST_PROJECT_PATH", "/app")
    
    # 1. DETECT DOCKER HOST (Logic to match your shell script)
    # If we are on Windows/Mac using TCP, we pass that. Otherwise, we use the socket.
    internal_docker_host = os.getenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    
    clean_host_path = host_path.replace('\\', '/').replace('C:', '/c')
    
    while True:
        active_workers = client.containers.list(filters={"label": "service=piper-worker"})

        for container in client.containers.list(all=True, filters={"label": "service=piper-worker"}):
            if container.status == "exited":
                container.remove()
        current_count = len(active_workers)
        
        if current_count < MAX_WORKERS:
            result = r.blpop("task_queue", timeout=5)
            
            if result:
                queue_name, task_str = result
                try:
                    task_dict = json.loads(task_str)
                    client_name = task_dict.get("client_id", "unknown") 
                    dsl_name = task_dict.get("dsl_name", "default").split(".")[0]
                    uid = generate_random_token()
                    container_instance_name = f"worker.{client_name}.{dsl_name}.{uid}"
                    
                    # 2. CONSTRUCT VOLUMES DYNAMICALLY
                    worker_volumes = {
                        # Mount the client templates (Read/Write)
                        f"{clean_host_path}/templates/{client_name}": {'bind': f'/app/templates/{client_name}', 'mode': 'rw'},
                        # Mount global piper config (Read-Only)
                        f"{clean_host_path}/.piper_config": {'bind': '/app/.piper_config', 'mode': 'ro'},
                        # Mount the shared named volume for persistent storage
                        'piper_storage': {'bind': '/app/piper_storage', 'mode': 'rw'}
                    }

                    # 3. ADD DOCKER SOCKET IF ON LINUX
                    # On Windows, we use DOCKER_HOST env instead of a volume mount
                    if internal_docker_host.startswith("unix://"):
                        socket_path = internal_docker_host.replace("unix://", "")
                        worker_volumes[socket_path] = {'bind': '/var/run/docker.sock', 'mode': 'ro'}

                    worker_container = client.containers.run(
                        image="ghcr.io/philz-dev/piper-worker:v1",
                        name=container_instance_name,
                        labels={"service": "piper-worker"},
                        detach=True,
                        auto_remove=False,
                        extra_hosts={"host.docker.internal": "host-gateway"},
                        environment={
                            "TASK_DATA": task_str,
                            "CLIENT_NAME": client_name,
                            "DSL_NAME": dsl_name,
                            "MASTER_PASSWORD": master_password,
                            "DATABASE_URL": database_url,
                            "PYTHONPATH": "/app",
                            "HOST_PROJECT_PATH": clean_host_path,
                            # 4. PASS THE DOCKER HOST (Critical for Windows support)
                            "DOCKER_HOST": internal_docker_host 
                        },
                        volumes=worker_volumes,
                        network_mode="piper-network",
                        dns=["8.8.8.8", "1.1.1.1"]
                    )
                    print(f"🚀 Worker {container_instance_name} spawned via {internal_docker_host}")
                    
                except Exception as e:
                    print(f"❌ SDK Spawn Error: {e}")
        else:
            time.sleep(2)

"""def monitor_and_spawn():
    print(f"🕵️ Controller started. Max capacity: {MAX_WORKERS} workers.")
    database_url = os.getenv("DATABASE_URL")
    master_password = os.getenv("MASTER_PASSWORD")
    host_path = os.getenv("HOST_PROJECT_PATH", "/app")
    clean_host_path = host_path.replace('\\', '/').replace('C:', '/c')
    print(f"DEBUG: Raw HOST_PROJECT_PATH from env: {host_path}")
    print(f"clean:     {clean_host_path}")
    
    while True:
        # 1. Count ONLY our workers (using the Label we discussed!)
        active_workers = client.containers.list(filters={"label": "service=piper-worker"})
        current_count = len(active_workers)
        
        if current_count < MAX_WORKERS:
            # 2. 'Pop' the task. This deletes it from Redis immediately.
            # blpop(queue_name, timeout) - it waits until a task appears!
            result = r.blpop("task_queue", timeout=5)
            
            if result:
                print(f"📦 Task received! Spawning worker {current_count + 1}/{MAX_WORKERS}")
                queue_name, task_str = result
                
                try:
                    # 1. Parse JSON FIRST so we have the data
                    task_dict = json.loads(task_str)
                    
                    # 2. Extract identifiers (match these to what you push to Redis)
                    client_name = task_dict.get("client_id", "unknown") 
                    dsl_name = task_dict.get("dsl_name", "default").split(".")[0]
                    
                    # 3. Create a truly unique name (prevents Docker Name Conflicts)
                    timestamp = int(time.time())
                    container_instance_name = f"worker.{client_name}.{dsl_name}.{timestamp}"
                    
                    print(f"📦 Task received! Spawning worker for {client_name}")
                    print(f"DEBUG: Raw HOST_PROJECT_PATH from env: {host_path}")
                    print(f"clean:     {clean_host_path}")
                    worker_container = client.containers.run(
                        image="ghcr.io/philz-dev/piper-worker:v1",
                        name=container_instance_name,
                        labels={"service": "piper-worker"},
                        detach=True,
                        auto_remove=False, 
                        dns=["8.8.8.8", "1.1.1.1"],
                        environment={
                            "TASK_DATA": task_str, # The worker reads this!
                            "CLIENT_NAME": client_name,
                            "DSL_NAME": dsl_name,
                            "MASTER_PASSWORD": master_password,
                            "DATABASE_URL": database_url,
                            "PYTHONPATH": "/app",
                            "HOST_PROJECT_PATH": clean_host_path
                        },
                        network_mode="piper-network",
  
                        # 2. Only mount what is necessary
                        volumes={
                            # Mount the client folder to a dedicated context folder
                            f"{clean_host_path}/templates/{client_name}": {'bind': f'/app/templates/{client_name}', 'mode': 'rw'},
                            f"{clean_host_path}/.piper_config": {'bind': '/app/.piper_config', 'mode': 'ro'},
                            clean_host_path: {'bind': '/app', 'mode': 'ro'},
                            'piper_storage': {'bind': '/app/piper_storage', 'mode': 'rw'}
                        }
                    )
                    time.sleep(1)
                    worker_container.reload()
                    print(f"🚀 Worker {container_instance_name} spawned.")
                    if worker_container.status == "running":
                        print(f"🚀 Worker {worker_container.name} is confirmed healthy and active.")
                    else:
                        print(f"⚠️ Worker spawned but is in state: {worker_container.status}")
                        print(f"Logs: {worker_container.logs().decode('utf-8')}")
                    
                except json.JSONDecodeError:
                    print("❌ Failed to parse task JSON")
                except Exception as e:
                    print(f"❌ SDK Spawn Error: {e}")
                            
        else:
            # VPS is full! Wait a bit before checking if a worker finished
            time.sleep(2)"""

    

if __name__ == "__main__":
    monitor_and_spawn()