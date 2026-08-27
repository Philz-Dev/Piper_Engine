from shared.database_manager import ContextDB
from shared.redis_queuer import add_to_redis
from sqlalchemy import text
from datetime import datetime
from dateutil.relativedelta import relativedelta
import uuid
import redis
import json
import uuid
import time

db = ContextDB()


def check_schedules():
    print("⏰ Scheduler: Checking for due tasks...")
    
    # 1. Fetch only what is needed to trigger the job
    query = text("""
        SELECT client_id, task_id, step_id FROM scheduler 
        WHERE scheduled_time <= CURRENT_TIMESTAMP AND status = 'pending'
        FOR UPDATE SKIP LOCKED
    """)
    
    with db.engine.connect() as conn:
        with conn.begin():
            due_tasks = conn.execute(query).fetchall()
            
            for task in due_tasks:
                c_id = task.client_id
                t_id = task.task_id
                s_id = task.step_id
                
                # 2. Get the blueprint
                pipeline = db.get_pipeline(c_id, t_id)
                
                if pipeline:
                    # 3. Push to Redis for the worker to handle
                    event_id = f"evt_{uuid.uuid4().hex[:8]}"
                    existing_context = {}
                    existing_context["Typeform_webhook"] = {
                        "event_id": "01KMFAJ2XXFRK7CNSAJ8RQNSV1",
                        "event_type": "form_response",
                        "form_response": {
                            "form_id": "jdNx2Iob",
                            "token": "d7cwxn6xcqaxf2gjceazued7cwxnamdl",
                            "response_url": "https://admin.typeform.com/form/jdNx2Iob/results?responseId=d7cwxn6xcqaxf2gjceazued7cwxnamdl#responses",
                            "landed_at": "2026-03-24T07:04:27Z",
                            "submitted_at": "2026-03-24T07:04:48Z",
                            "definition": {
                                "id": "jdNx2Iob",
                                "title": "My new form",
                                "fields": [
                                    {
                                        "id": "ToU3ApQXwwWD",
                                        "ref": "92c8c328-654a-4815-9469-4f480b6eb072",
                                        "type": "short_text",
                                        "title": "First name",
                                        "properties": {}
                                    },
                                    {
                                        "id": "m74g5aBGlan3",
                                        "ref": "fa37b99d-d3fc-4a77-86f5-d9a4d85fc293",
                                        "type": "short_text",
                                        "title": "Last name",
                                        "properties": {}
                                    },
                                    {
                                        "id": "iHMnpHFzD5CL",
                                        "ref": "dd33b95b-30dd-4792-b4e7-febc520460c2",
                                        "type": "phone_number",
                                        "title": "Phone number",
                                        "properties": {}
                                    },
                                    {
                                        "id": "k9rAMot8t9c6",
                                        "ref": "58127ba6-a6ff-45ca-ba9e-5347132f66c9",
                                        "type": "email",
                                        "title": "Email",
                                        "properties": {}
                                    },
                                    {
                                        "id": "NrKCDabiyBxB",
                                        "ref": "de96fb54-7ed7-43ef-b327-e8cf600c99ca",
                                        "type": "short_text",
                                        "title": "Company",
                                        "properties": {}
                                    }
                                ],
                                "endings": [
                                    {
                                        "id": "DefaultTyScreen",
                                        "ref": "default_tys",
                                        "title": "Thanks for completing this typeform\nNow *create your own* \u2014 it's free, easy, & beautiful",
                                        "type": "thankyou_screen",
                                        "properties": {
                                            "button_text": "Create a *typeform*",
                                            "show_button": True,
                                            "share_icons": False,
                                            "button_mode": "default_redirect"
                                        },
                                        "attachment": {
                                            "type": "image",
                                            "href": "https://public-assets.typeform.com/public/admin/2dpnUBBkz2VN.gif"
                                        }
                                    }
                                ],
                                "settings": {
                                    "partial_responses_to_all_integrations": True
                                }
                            },
                            "answers": [
                                {
                                    "type": "text",
                                    "text": "er",
                                    "answer_url": "https://admin.typeform.com/form/jdNx2Iob/results?responseId=d7cwxn6xcqaxf2gjceazued7cwxnamdl&fieldId=ToU3ApQXwwWD#responses",
                                    "field": {
                                        "id": "ToU3ApQXwwWD",
                                        "type": "short_text",
                                        "ref": "92c8c328-654a-4815-9469-4f480b6eb072"
                                    }
                                },
                                {
                                    "type": "text",
                                    "text": "lance",
                                    "answer_url": "https://admin.typeform.com/form/jdNx2Iob/results?responseId=d7cwxn6xcqaxf2gjceazued7cwxnamdl&fieldId=m74g5aBGlan3#responses",
                                    "field": {
                                        "id": "m74g5aBGlan3",
                                        "type": "short_text",
                                        "ref": "fa37b99d-d3fc-4a77-86f5-d9a4d85fc293"
                                    }
                                },
                                {
                                    "type": "phone_number",
                                    "answer_url": "https://admin.typeform.com/form/jdNx2Iob/results?responseId=d7cwxn6xcqaxf2gjceazued7cwxnamdl&fieldId=iHMnpHFzD5CL#responses",
                                    "phone_number": "+12014536743",
                                    "field": {
                                        "id": "iHMnpHFzD5CL",
                                        "type": "phone_number",
                                        "ref": "dd33b95b-30dd-4792-b4e7-febc520460c2"
                                    }
                                },
                                {
                                    "type": "email",
                                    "answer_url": "https://admin.typeform.com/form/jdNx2Iob/results?responseId=d7cwxn6xcqaxf2gjceazued7cwxnamdl&fieldId=k9rAMot8t9c6#responses",
                                    "email": "er@gm.com",
                                    "field": {
                                        "id": "k9rAMot8t9c6",
                                        "type": "email",
                                        "ref": "58127ba6-a6ff-45ca-ba9e-5347132f66c9"
                                    }
                                },
                                {
                                    "type": "text",
                                    "text": "gm",
                                    "answer_url": "https://admin.typeform.com/form/jdNx2Iob/results?responseId=d7cwxn6xcqaxf2gjceazued7cwxnamdl&fieldId=NrKCDabiyBxB#responses",
                                    "field": {
                                        "id": "NrKCDabiyBxB",
                                        "type": "short_text",
                                        "ref": "de96fb54-7ed7-43ef-b327-e8cf600c99ca"
                                    }
                                }
                            ],
                            "ending": {
                                "id": "DefaultTyScreen",
                                "ref": "default_tys"
                            }
                        },
                    
                        "run_at": datetime.now().isoformat()
                    }
                    db.save_context(client_id=c_id, task_id=t_id, context_data=existing_context, event_id=event_id)
                    add_to_redis(
                        client_name=c_id, 
                        agency_id=t_id, 
                        pipeline=pipeline,
                        dsl_name=pipeline.get("dsl_name"),
                        is_schedule=True,
                        event_id=event_id
                    )
                    
                    # 4. Mark as 'executing' 
                    # The PipelineExecutor will handle rescheduling to 'pending' upon success
                    conn.execute(
                        text("UPDATE scheduler SET status = 'executing' WHERE task_id = :tid"), 
                        {"tid": t_id}
                    )
                    print(f"🚀 Task {t_id} handed off to Worker.")


def start_listener():
    while True:
        try:
            r = redis.Redis(host='redis-broker', port=6379, decode_responses=True)
            pubsub = r.pubsub()
            pubsub.subscribe('task_trigger_channel')
            print("👂 Listening for 'now' triggers...")
            
            for message in pubsub.listen():
                if message['type'] == 'message':
                    data = json.loads(message['data'])
                    trigger_now(data['client_id'], data['task_id'])
                    
        except redis.ConnectionError:
            print("❌ Redis connection lost, retrying in 5 seconds...")
            time.sleep(5)
        except Exception as e:
            print(f"❌ Listener error: {e}")
            time.sleep(5)

def trigger_now(client_id, task_id):
    """
    Directly triggers a task without waiting for the scheduler polling loop.
    """
    with db.engine.connect() as conn:
        with conn.begin():
            # 1. Check if the task exists and is pending
            task = conn.execute(
                text("SELECT client_id, task_id FROM scheduler WHERE task_id = :tid AND status = 'pending' FOR UPDATE"),
                {"tid": task_id}
            ).fetchone()

            if not task:
                print(f"⚠️ Task {task_id} not found or not in 'pending' status.")
                return

            # 2. Get the blueprint
            pipeline = db.get_pipeline(client_id, task_id)
            if pipeline:
                event_id = f"evt_{uuid.uuid4().hex[:8]}"
                
                # 3. Push to Redis
                add_to_redis(
                    client_name=client_id,
                    agency_id=task_id,
                    pipeline=pipeline.get("pipeline_data"),
                    dsl_name=pipeline.get("dsl_name"),
                    is_schedule=True,
                    event_id=event_id
                )

                # 4. Mark as 'executing' so the background scheduler skips it
                conn.execute(
                    text("UPDATE scheduler SET status = 'executing' WHERE task_id = :tid"),
                    {"tid": task_id}
                )
                print(f"⚡ Immediate trigger: Task {task_id} sent to Worker.")

def check_schedules_v1():
    print("⏰ Scheduler: Checking for due tasks...")
    
    # 1. Fetch due tasks. We include intervals/value to calculate the NEXT run.
    query = text("""
        SELECT client_id, task_id, intervals, value FROM scheduler 
        WHERE scheduled_time <= CURRENT_TIMESTAMP AND status = 'pending'
        FOR UPDATE SKIP LOCKED
    """)
    
    with db.engine.connect() as conn:
        with conn.begin():
            due_tasks = conn.execute(query).fetchall()
            
            for task in due_tasks:
                c_id, t_id = task.client_id, task.task_id
                interval_unit = task.intervals  # e.g., 'minute', 'day'
                interval_value = task.value     # e.g., 30, 1
                
                pipeline = db.get_pipeline(c_id, t_id)
                
                if pipeline:
                    # 2. Push to Redis
                    add_to_redis(
                        client_name=c_id, 
                        agency_id=t_id, 
                        pipeline=pipeline.get("pipeline_data"),
                        dsl_name=pipeline.get("dsl_name"),
                        is_schedule=True
                    )
                    
                    # 3. Handle Rescheduling Logic
                    if interval_unit and interval_value:
                        # Calculate next run time

                        unit = interval_unit.lower()
                        if not unit.endswith('s'): unit += 's'
                        
                        delta = {unit: interval_value}
                        next_run = datetime.now() + relativedelta(**delta)

                        # Update to NEXT time and keep status 'pending'
                        conn.execute(
                            text("""
                                UPDATE scheduler 
                                SET scheduled_time = :next_at, status = 'pending' 
                                WHERE task_id = :tid
                            """), 
                            {"next_at": next_run, "tid": t_id}
                        )
                        print(f"🔄 Task {t_id} rescheduled for {next_run}")
                    else:
                        # Non-recurring task: just mark as complete/scheduled
                        conn.execute(
                            text("UPDATE scheduler SET status = 'scheduled' WHERE task_id = :tid"), 
                            {"tid": t_id}
                        )
                        print(f"✅ One-time task {t_id} completed.")

def check_schedules_v2():
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
                    add_to_redis(
                        client_name=c_id, 
                        agency_id=t_id, 
                        pipeline=pipeline.get("pipeline_data"), # Pass the blueprint here
                        dsl_name=pipeline.get("dsl_name"),
                        is_schedule=True
                    )
                    
                    # 4. Mark as scheduled
                    conn.execute(
                        text("UPDATE scheduler SET status = 'scheduled' WHERE task_id = :tid"), 
                        {"tid": t_id}
                    )
                    print(f"✅ Task {t_id} moved to Redis queue.")