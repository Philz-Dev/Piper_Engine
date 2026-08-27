import json
import logging
import os
import subprocess
import sys
import time
import redis

# Configure logging format matching your previous error output style
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("PythonWorker")

r = redis.Redis(
    host=os.getenv("REDIS_HOST", "redis-broker"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    decode_responses=True,
)
WORKER_STREAM = "piper_python_stream"
GROUP_NAME = "python_workers"
CONSUMER_NAME = os.getenv("SANDBOX_WORKER_NAME", "python-worker-1")


def process_stream_task(task_data: dict):
    file_path = task_data.get("file_path")
    context = task_data.get("context", {})
    response_channel = task_data.get("response_channel")

    # Configure environment variables for the single-shot bootstrap.py execution
    env = os.environ.copy()
    env["PIPER_CONTEXT"] = json.dumps(context)
    if response_channel:
        env["PIPER_RESPONSE_CHANNEL"] = response_channel
    env["PYTHONUNBUFFERED"] = "1"

    # Invoke your single-shot bootstrap.py safely via subprocess
    cmd = ["python3", "/app/runner-python/runner.py", file_path]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
    except Exception as e:
        logger.error(f"Subprocess launch crash: {str(e)}")
        if response_channel:
            r.publish(
                response_channel,
                json.dumps({"error": f"Subprocess launch crash: {str(e)}"}),
            )


def main():
    while True:
        try:
            r.xgroup_create(WORKER_STREAM, GROUP_NAME, id="0", mkstream=True)
            logger.info(f"✅ Consumer group '{GROUP_NAME}' verified on stream '{WORKER_STREAM}'.")
            break
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.info(f"ℹ️ Consumer group '{GROUP_NAME}' already exists.")
                break
            else:
                logger.warning(f"⚠️ Waiting for Redis stream initialization: {e}")
                time.sleep(2)
        except Exception as e:
            logger.error(f"Worker Error: Redis connection error during init: {e}")
            time.sleep(2)
            
    logger.info(f"Python Stream Worker {CONSUMER_NAME} is listening to {WORKER_STREAM}...")

    while True:
        try:
            streams = r.xreadgroup(
                groupname=GROUP_NAME,
                consumername=CONSUMER_NAME,
                streams={WORKER_STREAM: ">"},
                count=1,
                block=2000
            )
            if streams:
                for _, messages in streams:
                    for msg_id, data in messages:
                        task_str = data.get("payload")
                        if task_str:
                            try:
                                process_stream_task(json.loads(task_str))
                            except Exception as e:
                                logger.error(f"Worker Error: Task {msg_id} failed: {e}")
                            finally:
                                r.xack(WORKER_STREAM, GROUP_NAME, msg_id)
        except Exception as e:
            logger.error(f"Worker Error: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()