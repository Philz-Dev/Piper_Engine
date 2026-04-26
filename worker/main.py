import os
import json
from pipeline_executor import Executor
import redis
import asyncio
# 1. Get the string from the Docker environment

r = redis.Redis(host='redis', port=6379, decode_responses=True)
raw_task_data = os.getenv("TASK_DATA")

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
        is_schedule = task_data.get("is_shedule")
        from_trigger = task_data.get("from_trigger")
        print(f"Executing Pipeline for Run ID: {run_id}")
        exe = Executor()
        data = {
            "_cont": pipeline, "password": master_password,
            "from_trigger": True, "run_id": run_id,
            "client_id": client_id, "task_id": task_id,
            "is_schedule": is_schedule,
            "from_trigger": from_trigger
        }
        await exe.call_run_executor(**data)
    else:
        print("❌ No TASK_DATA found in environment!")

if __name__ == "__main__":
    asyncio.run(start_worker())