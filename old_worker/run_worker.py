import sys
import json
import redis
import asyncio
import os
from shared.pipeline_executor import PipelineExecutor

r = redis.Redis(host='redis-broker', port=6379, decode_responses=True)

def get_masters_password():
    password = r.get("MASTER_PASSWORD")
    return password

async def start_worker():
    # 1. Get task_id from CLI argument (e.g., python run_worker.py 12345)
    if len(sys.argv) < 2:
        print("❌ No task_id provided!")
        return
    
    task_id = sys.argv[1]
    
    # 2. Fetch the actual task data from Redis
    raw_task_data = r.get(f"task_payload:{task_id}")
    
    if not raw_task_data:
        print(f"❌ No data found in Redis for task_id: {task_id}")
        return

    master_password = get_masters_password()
    if not master_password:
        raise ValueError("Credentials not found!")
    
    # 3. Process as normal
    task_data = json.loads(raw_task_data)
    
    run_id = task_data.get("run_id")
    pipeline = task_data.get("pipeline")
    client_id = task_data.get("client_id")
    
    print(f"Executing Pipeline for Run ID: {run_id}")
    
    exe = PipelineExecutor()
    data = {
        "_cont": pipeline, 
        "password": master_password, 
        "run_id": run_id,
        "client_id": client_id, 
        "task_id": task_id
    }
    await exe.call_run_executor(**data)
    
    # 4. Optional: Cleanup the Redis key after processing
    r.delete(f"task_payload:{task_id}")

if __name__ == "__main__":
    asyncio.run(start_worker())