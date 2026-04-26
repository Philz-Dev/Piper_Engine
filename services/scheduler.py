from shared.database_manager import ContextDB
from shared.redis_queuer import add_to_redis
from sqlalchemy import text

db = ContextDB() 

def check_schedules():
    print("⏰ Scheduler: Checking for due tasks...")
    
    # 1. Use 'FOR UPDATE' to lock the rows so two workers don't grab the same task
    query = text("""
        SELECT client_id, task_id FROM scheduler 
        WHERE scheduled_time <= CURRENT_TIMESTAMP AND status = 'pending'
        FOR UPDATE SKIP LOCKED
    """)
    
    with db.engine.connect() as conn:
        # Start a transaction
        with conn.begin():
            due_tasks = conn.execute(query).fetchall()
            
            for task in due_tasks:
                c_id, t_id = task.client_id, task.task_id
                
                # 2. Get the blueprint
                pipeline = db.get_pipeline(c_id, t_id)
                
                if pipeline:
                    # 3. Push to Redis
                    add_to_redis(dsl_name=c_id, agency_id=t_id, pipeline=pipeline, is_schedule=True)
                    
                    # 4. Mark as scheduled
                    conn.execute(
                        text("UPDATE scheduler SET status = 'scheduled' WHERE task_id = :tid"), 
                        {"tid": t_id}
                    )
                    print(f"✅ Task {t_id} moved to Redis queue.")