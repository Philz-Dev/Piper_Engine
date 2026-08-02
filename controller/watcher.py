import docker
import redis
import time
import os
import json
import logging

# Setup
client = docker.from_env()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WorkerController")

def get_redis_connection():
    while True:
        try:
            client = redis.Redis(host='redis-broker', port=6379, decode_responses=True)
            client.ping()
            logger.info("✅ Connected to redis-broker successfully.")
            return client
        except Exception as e:
            logger.warning(f"⚠️ Connecting to redis-broker:6379 failed ({e}). Retrying in 2s...")
            time.sleep(2)

r = get_redis_connection()
database_url = os.getenv("DATABASE_URL")
master_password = os.getenv("MASTER_PASSWORD")
host_path = os.getenv("HOST_PROJECT_PATH", "/app")

internal_docker_host = os.getenv("DOCKER_HOST", "unix:///var/run/docker.sock")
clean_host_path = host_path.replace('\\', '/').replace('C:', '/c')

MAX_WORKERS = int(os.getenv("MAX_WORKERS", 5))
WORKER_IMAGE = "ghcr.io/philz-dev/piper-worker:v1"

LANGUAGES = {
    "python": {"image": "ghcr.io/philz-dev/piper-runner-python:latest", "ext": ".py", "cmd": "python3"},
    "javascript": {"image": "ghcr.io/philz-dev/piper-runner-node:latest", "ext": ".js", "cmd": "node"},
    "typescript": {"image": "ghcr.io/philz-dev/piper-runner-ts:latest", "ext": ".ts", "cmd": "ts-node"},
    "php": {"image": "ghcr.io/philz-dev/piper-runner-php:latest", "ext": ".php", "cmd": "php"},
    "golang": {"image": "ghcr.io/philz-dev/piper-runner-go:latest", "ext": ".go", "cmd": "/app/bootstrap"},
    "rust": {"image": "ghcr.io/philz-dev/piper-runner-rust:latest", "ext": ".rs", "cmd": "/app/bootstrap"},
    "ruby": {"image": "ghcr.io/philz-dev/piper-runner-ruby:latest", "ext": ".rb", "cmd": "ruby"},
    "java": {"image": "ghcr.io/philz-dev/piper-runner-java:latest", "ext": ".java", "cmd": "java"},
    "csharp": {"image": "ghcr.io/philz-dev/piper-runner-csharp:latest", "ext": ".cs", "cmd": "dotnet run"},
    "c": {"image": "ghcr.io/philz-dev/piper-runner-c:latest", "ext": ".c", "cmd": "/app/bootstrap"},
    "cpp": {"image": "ghcr.io/philz-dev/piper-runner-cpp:latest", "ext": ".cpp", "cmd": "/app/bootstrap"},
    "swift": {"image": "ghcr.io/philz-dev/piper-runner-swift:latest", "ext": ".swift", "cmd": "swift"},
    "kotlin": {"image": "ghcr.io/philz-dev/piper-runner-kotlin:latest", "ext": ".kt", "cmd": "kotlinc"},
    "r": {"image": "ghcr.io/philz-dev/piper-runner-r:latest", "ext": ".r", "cmd": "Rscript"},
    "lua": {"image": "ghcr.io/philz-dev/piper-runner-lua:latest", "ext": ".lua", "cmd": "lua"},
    "perl": {"image": "ghcr.io/philz-dev/piper-runner-perl:latest", "ext": ".pl", "cmd": "perl"},
    "bash": {"image": "ghcr.io/philz-dev/piper-runner-bash:latest", "ext": ".sh", "cmd": "bash"}
}

def get_dynamic_max_containers() -> int:
    try:
        info = client.info()
        mem_total_bytes = info.get("MemTotal", 0)
        mem_total_gb = mem_total_bytes / (1024 ** 3)
        calculated_limit = max(1, int(mem_total_gb / 1.5))
        env_limit = os.getenv("MAX_LANGUAGE_CONTAINERS")
        if env_limit:
            return int(env_limit)
        return min(calculated_limit, 10)
    except Exception as e:
        logger.error(f"Error determining machine capacity: {e}")
        return int(os.getenv("MAX_LANGUAGE_CONTAINERS", 3))

def sync_language_runners(chosen_langs: list[str]):
    valid_chosen = [lang for lang in chosen_langs if lang in LANGUAGES]
    max_capacity = get_dynamic_max_containers()
    if len(valid_chosen) > max_capacity:
        valid_chosen = valid_chosen[:max_capacity]
    
    active_runners = client.containers.list(all=True, filters={"label": "service=piper-runner"})
    for container in active_runners:
        lang_label = container.labels.get("language")
        if lang_label not in valid_chosen:
            try:
                container.stop(timeout=5)
                container.remove(force=True)
            except Exception as e:
                logger.error(f"Failed to stop/remove container {container.name}: {e}")

    for selected_lang in valid_chosen:
        target_name = f"piper-runner-{selected_lang}"
        try:
            existing = client.containers.get(target_name)
            if existing.status != "running":
                existing.start()
        except docker.errors.NotFound:
            lang_config = LANGUAGES[selected_lang]
            client.containers.run(
                lang_config["image"],
                name=target_name,
                detach=True,
                labels={"service": "piper-runner", "language": selected_lang},
                network="piper-network",
                volumes={'piper_storage': {'bind': '/app/piper_storage', 'mode': 'rw'}},
                command=lang_config["cmd"]
            )

def init_worker_pool():
    print(f"🛠️ Initializing pool of {MAX_WORKERS} warm workers...")
    worker_volumes = {
        f"{clean_host_path}/.piper_config": {'bind': '/app/.piper_config', 'mode': 'ro'},
        'piper_storage': {'bind': '/app/piper_storage', 'mode': 'rw'}
    }

    if internal_docker_host.startswith("unix://"):
        socket_path = internal_docker_host.replace("unix://", "")
        worker_volumes[socket_path] = {'bind': '/var/run/docker.sock', 'mode': 'ro'}

    for i in range(MAX_WORKERS):
        name = f"piper-worker-{i}"
        should_create = False
        
        try:
            container = client.containers.get(name)
            if container.status != "running":
                try:
                    container.start()
                except docker.errors.APIError:
                    try:
                        container.remove(force=True)
                    except Exception:
                        pass
                    should_create = True
        except docker.errors.NotFound:
            should_create = True

        if should_create:
            try:
                client.containers.run(
                    WORKER_IMAGE,
                    name=name,
                    detach=True,
                    labels={"service": "piper-worker", "pool": "piper-engine"},
                    network="piper-network",
                    volumes=worker_volumes,
                    command="python3 /app/run_worker.py",
                    dns=["8.8.8.8", "1.1.1.1"],
                    extra_hosts={"host.docker.internal": "host-gateway"},
                    environment={
                        "DATABASE_URL": database_url,
                        "DOCKER_HOST": internal_docker_host,
                        "WORKER_NAME": name,
                        "PYTHONUNBUFFERED": "1"
                    }
                )
            except docker.errors.APIError as e:
                if "Conflict" in str(e):
                    try:
                        client.containers.get(name).remove(force=True)
                        client.containers.run(
                            WORKER_IMAGE, name=name, detach=True,
                            labels={"service": "piper-worker", "pool": "piper-engine"},
                            network="piper-network",
                            volumes=worker_volumes,
                            command="python3 /app/run_worker.py",
                            dns=["8.8.8.8", "1.1.1.1"],
                            extra_hosts={"host.docker.internal": "host-gateway"},
                            environment={
                                "DATABASE_URL": database_url,
                                "DOCKER_HOST": internal_docker_host,
                                "WORKER_NAME": name,
                                "PYTHONUNBUFFERED": "1"
                            }
                        )
                    except Exception as critical_err:
                        logger.error(f"❌ Failed to resolve container run for {name}: {critical_err}")
                        continue

def monitor_and_spawn():
    init_worker_pool()

    sync_language_runners([
        "python", "javascript", "typescript", "php", "golang",
        "rust", "java", "cpp", "csharp"
    ])

    print(f"🕵️ Controller active. Warm pool ready with Consumer Groups.")
    last_memory_check = 0
    MEMORY_CHECK_INTERVAL = 30
    
    while True:
        # 1. Health Check
        active_workers = client.containers.list(filters={"label": "service=piper-worker"})
        if len(active_workers) < MAX_WORKERS:
            init_worker_pool()

        # 2. Process Queue via shared stream ingestion
        result = r.blpop("task_queue", timeout=2)
        if result:
            _, task_str = result
            task_data = json.loads(task_str)
            task_id = task_data['task_id']
            client_name = task_data['client_id']

            # Write individual payload mapping for downstream references
            r.set(f"task_payload:{task_id}", task_str)

            # Push directly to the shared stream (Consumer Group takes over distribution)
            r.xadd("pipeline_stream", {"payload": task_str})
            print(f"🚀 Dispatched task {task_id} to shared pipeline_stream")

        current_time = time.time()
        if current_time - last_memory_check > MEMORY_CHECK_INTERVAL:
            last_memory_check = current_time
            for w in active_workers:
                try:
                    stats = w.stats(stream=False)
                    mem_usage = stats['memory_stats']['usage']
                    mem_limit = stats['memory_stats']['limit']
                    if (mem_usage / mem_limit) > 0.85:
                        print(f"⚠️ Worker {w.name} memory high! Recycling...")
                        w.restart()
                except Exception:
                    continue

if __name__ == "__main__":
    monitor_and_spawn()