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
