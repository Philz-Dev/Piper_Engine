import redis
import json
import uuid

r = redis.Redis(host='redis-broker', port=6379, decode_responses=True)

def add_to_redis(dsl_name, agency_id, pipeline=None, from_trigger=False, is_schedule=False):
    run_id = str(uuid.uuid4())
    
    job_ticket = {
        "run_id": run_id,
        "agency_id": agency_id,
        "client_id": dsl_name,
        "pipeline": pipeline, # This now contains the full logic/blueprint
        "step_index": 0,
        "context": {},
        "is_schedule": is_schedule,
        "from_trigger": from_trigger
    }
    
    r.rpush("task_queue", json.dumps(job_ticket))
    return {"status": "queued", "run_id": run_id}

def handover_password(password):
    # We save the password with an expiry of 300 seconds (5 minutes)
    # This ensures the password doesn't sit in RAM forever
    r.set(f"MASTER_PASSWORD", password, ex=300)
    print(f"MASTER_PASSWORD credentials Stored")

def remove_from_redis_queue(run_id):
    """
    Scans the task_queue for a job_ticket matching the run_id and removes it.
    """
    try:
        # 1. Get all items in the queue to find the exact string match
        # Note: In a massive queue, this is O(N). 
        # For 'Piper' scale, LREM is generally efficient.
        tasks = r.lrange("task_queue", 0, -1)
        
        target_ticket = None
        for task_str in tasks:
            task_data = json.loads(task_str)
            if task_data.get("run_id") == run_id:
                target_ticket = task_str
                break
        
        if target_ticket:
            # 2. LREM: count=0 means remove all occurrences of this specific string
            removed_count = r.lrem("task_queue", count=0, value=target_ticket)
            
            if removed_count > 0:
                print(f"🛑 Task {run_id} removed from queue successfully.")
                return {"status": "stopped", "run_id": run_id}
        
        print(f"⚠️ Task {run_id} not found in queue (it might already be running).")
        return {"status": "not_in_queue", "run_id": run_id}

    except Exception as e:
        print(f"❌ Error removing task from Redis: {str(e)}")
        return {"status": "error", "message": str(e)}
