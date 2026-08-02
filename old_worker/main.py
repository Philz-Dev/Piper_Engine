import os
import json
from shared.pipeline_executor import PipelineExecutor
import redis
import asyncio
import sys
import time

# 1. Get the string from the Docker environment

r = redis.Redis(host='redis-broker', port=6379, decode_responses=True)
raw_task_data = os.getenv("TASK_DATA")

# Get container name from ENV (Docker sets this automatically)
CONTAINER_NAME = os.getenv("HOSTNAME")

def update_registry(status, client_id=None, task_id=None):
    payload = {
        "status": status,
        "client_id": client_id,
        "task_id": task_id,
        "updated_at": time.time()
    }
    r.hset("worker_registry", CONTAINER_NAME, json.dumps(payload))

def get_masters_password():
    password = r.get(f"MASTER_PASSWORD")
    if password:
        print(f"Worker retrieved password: {password}")
        return password
    print("Credentials expired or not found!")
    return None


async def start_worker():
    master_password = get_masters_password()
    if not master_password:
        raise ValueError("master password seesion expires please re enter master password to continue")
    if raw_task_data:
        # 2. Convert the string back into a Python Dictionary
        task_data = json.loads(raw_task_data)
        
        # 3. Now you can use it!
        run_id = task_data.get("run_id")
        task_id = task_data.get("task_id")
        client_id = task_data.get("client_id")
        pipeline = task_data.get("pipeline")
        is_schedule = task_data.get("is_schedule")
        from_trigger = task_data.get("from_trigger")
        event_id = task_data.get("event_id")
        print(f"is schedule:     {is_schedule}")
        print(f"Executing Pipeline for Run ID: {run_id}")
        exe = PipelineExecutor()
        data = {
            "_cont": pipeline, "password": master_password, 
            "run_id": run_id,
            "client_id": client_id, 
            "task_id": task_id,
            "from_trigger": from_trigger,
            "is_schedule": is_schedule,
            "event_id": event_id
        }
        update_registry("busy", client_id=task_data['client_id'], task_id=task_id)

        try:
            # ... logic ...
            await exe.call_run_executor(**data)
        finally:
            # 4. Critical: Always release the worker back to idle
            update_registry("idle")
            r.delete(f"task_payload:{task_id}")
    else:
        print("❌ No TASK_DATA found in environment!")

if __name__ == "__main__":
    asyncio.run(start_worker())