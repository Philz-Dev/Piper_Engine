import sys
import json
import redis
import asyncio
import os
import time
import logging
from shared.pipeline_executor import PipelineExecutor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Worker")

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

CONTAINER_NAME = os.getenv("WORKER_NAME")
STREAM_NAME = "pipeline_stream"
GROUP_NAME = "pipeline_group"

async def process_task(task_data, msg_id):
    start_time = time.perf_counter()
    task_id = task_data['task_id']
    client_id = task_data.get("client_id")
    
    logger.info(f"🚀 Worker {CONTAINER_NAME} starting task {task_id}")

    try:
        master_password = r.get("MASTER_PASSWORD")
        if not master_password:
            raise ValueError("Credentials not found!")
        
        exe = PipelineExecutor()
        data = {
            "_cont": task_data.get("pipeline"), 
            "password": master_password, 
            "run_id": task_data.get("run_id"),
            "client_id": client_id, 
            "task_id": task_id,
            "from_trigger": task_data.get("from_trigger"),
            "is_schedule": task_data.get("is_schedule"),
            "event_id": task_data.get("event_id")
        }
        
        await exe.call_run_executor(**data)
        elapsed = (time.perf_counter() - start_time) * 1000
        logger.info(f"✅ Task {task_id} completed in {elapsed:.2f}ms")

    except Exception as e:
        print(f"❌ Execution failed for task {task_id}: {e}")
    finally:
        # Acknowledge message delivery and completion so Redis clears it from the PEL
        try:
            r.xack(STREAM_NAME, GROUP_NAME, msg_id)
        except Exception as ack_err:
            logger.error(f"Failed to ACK message {msg_id}: {ack_err}")
            
        r.delete(f"task_payload:{task_id}")

def worker_main_loop():
    """Continuously listen to the shared pipeline stream via Consumer Groups."""
    
    # Ensure consumer group exists (create stream automatically if it doesn't exist yet)
    try:
        r.xgroup_create(STREAM_NAME, GROUP_NAME, id="0", mkstream=True)
        logger.info(f"✅ Consumer group '{GROUP_NAME}' created on stream '{STREAM_NAME}'.")
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" in str(e):
            logger.info(f"ℹ️ Consumer group '{GROUP_NAME}' already exists.")
        else:
            raise e

    print("=" * 60)
    logger.info(f"💤 Worker {CONTAINER_NAME} ready and listening in group '{GROUP_NAME}'.")
    print("=" * 60)

    while True:
        try:
            # XREADGROUP pulls messages destined for this specific consumer
            # '>' means get messages never delivered to any other consumer in this group
            streams = r.xreadgroup(
                groupname=GROUP_NAME,
                consumername=CONTAINER_NAME,
                streams={STREAM_NAME: ">"},
                count=1,
                block=2000
            )
            
            if streams:
                for _, messages in streams:
                    for msg_id, data in messages:
                        task_str = data.get("payload")
                        if task_str:
                            task_data = json.loads(task_str)
                            asyncio.run(process_task(task_data, msg_id))

        except Exception as e:
            print(f"⚠️ Stream Read Group Error: {e}")
            time.sleep(1)

if __name__ == "__main__":
    worker_main_loop()