import os
import json
from sqlalchemy import create_engine, text
from dateutil.relativedelta import relativedelta
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from shared.registry_V2 import ValidationState

class ContextDB:
    def __init__(self):
        # Defaulting to a generic string, but Docker will override this via Env Var
        self.db_url = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/piper_db")
        self.engine = create_engine(self.db_url)

    def check_connection(self):
        """Silently checks if the DB is reachable."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
        
    def get_cleanup_schema(self, client_id, task_id):
        """Retrieves the delete/cleanup schema for a specific task."""
        query = text("SELECT delete_schema FROM pipeline_cleanup WHERE client_id = :c_id AND task_id = :t_id")
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"c_id": client_id, "t_id": task_id}).fetchone()
                if result:
                    # Parse the JSON string back into a dict
                    return json.loads(result[0]) if isinstance(result[0], str) else result[0]
                return None
        except Exception as e:
            print(f"❌ Error fetching cleanup schema: {e}")
            return None

    def remove_service_from_vault(self, client_name: str, service_key: str):
        """
        Surgically removes a specific service (like 'Typeform') from a client's vault
        without deleting the entire vault record.
        """
        # The '#-' operator deletes the key from the JSONB object
        query = text("""
            UPDATE piper_vault 
            SET vault_data = vault_data - :service,
                updated_at = NOW()
            WHERE client_name = :name
        """)
        try:
            with self.engine.connect() as conn:
                conn.execute(query, {
                    "name": client_name,
                    "service": service_key
                })
                conn.commit()
            print(f"✂️ Removed {service_key} from {client_name}'s vault.")
            return True
        except Exception as e:
            print(f"❌ Failed to remove {service_key} for {client_name}: {e}")
            return False
    
    def get_connection(self):
        """Bridge for raw psycopg2 connections when using cursors."""
        return self.engine.raw_connection()
    
    def get_pipeline_by_client(self, client_id: str):
        """Checks if a pipeline exists for a client and returns the record."""
        query = text("SELECT task_id, pipeline_data FROM pipeline_storage WHERE client_id = :c_id")
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"c_id": client_id}).fetchone()
                if result:
                    # Returning a dict so your script can access ["task_id"]
                    return {"task_id": result[0], "pipeline_data": result[1]}
                return None
        except Exception as e:
            print(f"❌ Error checking existing pipeline: {e}")
            return None
        
    def reset_pipeline_storage(self):
        """Surgical strike to fix the UNIQUE constraint issue."""
        queries = [
            "DROP TABLE IF EXISTS pipeline_storage;",
            """
            CREATE TABLE pipeline_storage (
                id SERIAL PRIMARY KEY,
                client_id VARCHAR(255) UNIQUE, -- The critical constraint
                dsl_name VARCHAR(255),
                task_id VARCHAR(255),
                pipeline_data JSONB,
                UNIQUE(client_id, task_id)
            );
            """
        ]
        with self.engine.connect() as conn:
            for q in queries:
                conn.execute(text(q))
            conn.commit()

    def update_pipeline(self, client_id: str, task_id: str, pipeline_data: dict):
        """Updates an existing pipeline while keeping the task_id stable."""
        query = text("""
            UPDATE pipeline_storage 
            SET pipeline_data = :data 
            WHERE client_id = :c_id AND task_id = :t_id
        """)
        try:
            with self.engine.connect() as conn:
                conn.execute(query, {
                    "c_id": client_id, 
                    "t_id": task_id, 
                    "data": json.dumps(pipeline_data)
                })
                conn.commit()
        except Exception as e:
            print(f"❌ Error updating pipeline: {e}")
    
    def upsert_pipeline(self, client_id, new_task_id, pipeline_data, dsl_name):
        """
        If client exists, updates the pipeline and returns the OLD task_id.
        If client is new, saves it and returns the NEW task_id.
        """
        # We look for client_id only to see if they already have a configuration
        query = text("""
            INSERT INTO pipeline_storage (client_id, task_id, pipeline_data, dsl_name)
            VALUES (:c_id, :t_id, :data, :dsl)
            ON CONFLICT (client_id, task_id)
            DO UPDATE SET 
                pipeline_data = EXCLUDED.pipeline_data,
                dsl_name = EXCLUDED.dsl_name
            RETURNING task_id;
        """)
        
        with self.engine.connect() as conn:
            # We need to ensure the table has a UNIQUE constraint on client_id alone
            # for this specific 'per-client' logic to work.
            result = conn.execute(query, {
                "c_id": client_id, 
                "t_id": new_task_id, 
                "data": json.dumps(pipeline_data),
                "dsl": dsl_name
            })
            conn.commit()
            row = result.fetchone()
            return row[0] if row else new_task_id

    def initialize_tables(self):
        """Creates the necessary database structure silently."""
        # Table 1: Context Manager (Original)
        # Table 2: Pipeline Storage (Stores the 'all_cont' blueprint)
        # Table 3: Scheduler (Stores when things should execute)
        queries = [
            """
            CREATE TABLE IF NOT EXISTS context_manager (
                id SERIAL PRIMARY KEY,
                event_id VARCHAR(255) UNIQUE, -- Add this!
                client_id VARCHAR(255) NOT NULL,
                task_id VARCHAR(255) NOT NULL,
                context JSONB DEFAULT '{}'::jsonb,
                last_updated TIMESTAMP DEFAULT NOW()
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS webhook_registry (
                webhook_token VARCHAR(255) PRIMARY KEY, -- The unique key in the URL
                client_id VARCHAR(255) NOT NULL,
                task_id VARCHAR(255) NOT NULL,
                app_name VARCHAR(255),
                webhook_id VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS piper_vault (
                id SERIAL PRIMARY KEY,
                client_name VARCHAR(255) UNIQUE NOT NULL,
                vault_data JSONB DEFAULT '{}'::jsonb,
                updated_at TIMESTAMP DEFAULT NOW()
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS pipeline_storage (
                id SERIAL PRIMARY KEY,
                client_id VARCHAR(255),
                dsl_name VARCHAR(255),
                task_id VARCHAR(255),
                pipeline_data JSONB,
                UNIQUE(client_id, task_id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS scheduler (
                id SERIAL PRIMARY KEY,
                client_id VARCHAR(255),
                task_id VARCHAR(255),
                scheduled_time TIMESTAMP,
                intervals VARCHAR(255),  -- Added missing comma
                value INT,
                step_id VARCHAR(255),
                status VARCHAR(50) DEFAULT 'pending', 
                UNIQUE(client_id, task_id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS engine_metadata (
                meta_key VARCHAR(255) PRIMARY KEY,
                meta_value JSONB NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW()
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS version_registry (
                client_id VARCHAR(255) PRIMARY KEY,
                version_tag VARCHAR(50) DEFAULT 'latest',
                updated_at TIMESTAMP DEFAULT NOW()
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS pipeline_cleanup (
                id SERIAL PRIMARY KEY,
                client_id VARCHAR(255),
                task_id VARCHAR(255) UNIQUE, 
                delete_schema JSONB,
                UNIQUE(client_id, task_id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS validation_history (
                id SERIAL PRIMARY KEY,
                client_id VARCHAR(255) NOT NULL,
                task_id VARCHAR(255) NOT NULL,
                logs JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                -- Indexing for speed when you open the drawer
                CONSTRAINT idx_client_task UNIQUE (client_id, task_id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS auth_interventions (
                id SERIAL PRIMARY KEY,
                client_id VARCHAR(255) NOT NULL,
                app_name VARCHAR(255) NOT NULL,
                auth_url TEXT NOT NULL,
                status VARCHAR(50) DEFAULT 'pending', -- pending, resolved
                created_at TIMESTAMP DEFAULT NOW()
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                run_id VARCHAR(255) PRIMARY KEY,
                state JSONB NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW()
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS execution_logs (
                id SERIAL PRIMARY KEY,
                run_id VARCHAR(255) UNIQUE NOT NULL,
                client_id VARCHAR(255) NOT NULL,
                task_id VARCHAR(255) NOT NULL,
                dsl_name VARCHAR(255),
                status VARCHAR(50) DEFAULT 'running', -- running, success, failed
                logs JSONB DEFAULT '[]'::jsonb,        -- Array of step results
                error_message TEXT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP
            );"""
        ]
        with self.engine.connect() as conn:
            for q in queries:
                conn.execute(text(q))
            conn.commit()

    def save_vault(self, client_name, vault_data):
        """
        Saves or updates the encrypted API keys for a specific client.
        vault_data: dict containing keys like {"Hubspot": "...", "API_KEY": "..."}
        """
        query = text("""
            INSERT INTO piper_vault (client_name, vault_data, updated_at)
            VALUES (:name, :data, NOW())
            ON CONFLICT (client_name) 
            DO UPDATE SET 
                vault_data = EXCLUDED.vault_data,
                updated_at = NOW();
        """)
        try:
            with self.engine.connect() as conn:
                conn.execute(query, {
                    "name": client_name,
                    "data": json.dumps(vault_data)
                })
                conn.commit()
            return True
        except Exception as e:
            print(f"❌ Failed to save vault for {client_name}: {e}")
            return False

    def get_vault(self, client_name):
        """
        Retrieves the encrypted vault for a specific client.
        """
        query = text("SELECT vault_data FROM piper_vault WHERE client_name = :name")
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"name": client_name}).fetchone()
                if result:
                    # SQLAlchemy might return it as a dict already if using JSONB, 
                    # but we handle the string fallback just in case.
                    data = result[0]
                    return json.loads(data) if isinstance(data, str) else data
                return {}
        except Exception as e:
            print(f"❌ Error fetching vault for {client_name}: {e}")
            return {}

    # Add this to your database_manager.py
    def get_log_count(self, client_id, task_id):
        query = text("SELECT COUNT(*) FROM logs WHERE client_id = :c AND task_id = :t")
        with self.engine.connect() as conn:
            return conn.execute(query, {"c": client_id, "t": task_id}).scalar()

    def danger_drop_context_table(self):
        """Permanently deletes the context_manager table."""
        query = text("DROP TABLE IF EXISTS context_manager CASCADE;")
        try:
            with self.engine.connect() as conn:
                conn.execute(query)
                conn.commit()
            print("🗑️ Table 'context_manager' dropped successfully.")
        except Exception as e:
            print(f"❌ Failed to drop table: {e}")

    def save_version(self, client_id, version):
        """Saves only the version tag for a client."""
        query = text("""
            INSERT INTO version_registry (client_id, version_tag, updated_at)
            VALUES (:c_id, :v, NOW())
            ON CONFLICT (client_id) DO UPDATE SET version_tag = EXCLUDED.version_tag, updated_at = NOW();
        """)
        with self.engine.connect() as conn:
            conn.execute(query, {"c_id": client_id, "v": version})
            conn.commit()

    def get_version(self, client_id):
        """Retrieves the version tag for a client."""
        query = text("SELECT version_tag FROM version_registry WHERE client_id = :c_id")
        with self.engine.connect() as conn:
            result = conn.execute(query, {"c_id": client_id}).fetchone()
            return result[0] if result else "latest"
    
    def get_context_v2(self, client_id: str, task_id: str):
        # Fixed table name to context_manager and column to context
        query = "SELECT context FROM context_manager WHERE client_id = %s AND task_id = %s;"
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(query, (client_id, task_id))
                    result = cur.fetchone()
                    return result['context'] if result else {}
        except Exception as e:
            print(f"Error fetching context: {e}")
            return {}
        
    def get_context(self, client_id: str, task_id: str, event_id: str = None):
        # If event_id is provided, get only that event's data.
        # Otherwise, fallback to the old behavior.
        if event_id:
            query = "SELECT context FROM context_manager WHERE event_id = %s;"
            params = (event_id,)
        else:
            query = "SELECT context FROM context_manager WHERE client_id = %s AND task_id = %s;"
            params = (client_id, task_id)
            
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(query, params)
                    result = cur.fetchone()
                    return result['context'] if result else {}
        except Exception as e:
            print(f"Error fetching context: {e}")
            return {}
        
    def create_intervention(self, client_id, app_name, auth_url):
        """Engine calls this when it hits an Auth wall."""
        query = text("""
            INSERT INTO auth_interventions (client_id, app_name, auth_url, status)
            VALUES (:c_id, :app, :url, 'pending')
        """)
        with self.engine.connect() as conn:
            conn.execute(query, {"c_id": client_id, "app": app_name, "url": auth_url})
            conn.commit()

    def get_pending_interventions(self):
        """
        API/Websocket calls this to check for ANY pending interventions 
        globally, regardless of the client.
        """
        query = text("""
            SELECT id, app_name, auth_url 
            FROM auth_interventions 
            WHERE status = 'pending'
            ORDER BY created_at DESC
        """)
        with self.engine.connect() as conn:
            # No parameters needed anymore
            result = conn.execute(query).fetchall()
            return [dict(row._mapping) for row in result]

    def mark_intervention_resolved(self, intervention_id):
        """UI calls this after the OAuth popup closes."""
        query = text("UPDATE auth_interventions SET status = 'resolved' WHERE id = :id")
        with self.engine.connect() as conn:
            conn.execute(query, {"id": intervention_id})
            conn.commit()

    def danger_drop_all_tables(self):
        """
        🚨 DANGER ZONE 🚨
        Permanently drops EVERY single schema table within the piper application database.
        Wipes out context logs, vault credentials, schedules, and active workflows.
        """
        tables_to_drop = [
            "context_manager",
            "webhook_registry",
            "piper_vault",
            "pipeline_storage",
            "scheduler",
            "version_registry",
            "pipeline_cleanup",
            "execution_logs",
            "workflow_checkpoints"
        ]
        
        # Build raw drop commands with CASCADE to clear any lingering constraints
        queries = [f"DROP TABLE IF EXISTS {table} CASCADE;" for table in tables_to_drop]
        
        try:
            print("⚠️ Initializing complete system database purge...")
            with self.engine.connect() as conn:
                with conn.begin(): # Wraps execution inside an atomic SQL transaction
                    for q in queries:
                        conn.execute(text(q))
            print("💥 Success: All piper tables dropped. Database is completely empty.")
            return True
        except Exception as e:
            print(f"❌ Critical failure during database purge: {e}")
            return False

    def save_context(self, client_id: str, task_id: str, context_data: dict, event_id: str):
        query = """
            INSERT INTO context_manager (event_id, client_id, task_id, context, last_updated)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (event_id) 
            DO UPDATE SET 
                context = EXCLUDED.context,
                last_updated = NOW();
        """
        conn = self.get_connection() # Get from pool
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (event_id, client_id, task_id, json.dumps(context_data)))
                conn.commit()
        except Exception as e:
            print(f"Error saving context: {e}")

    def save_context_v2(self, client_id: str, task_id: str, context_data: dict):
        # Explicitly using 'context' as the column name
        query = """
            INSERT INTO context_manager (client_id, task_id, context, last_updated)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (client_id, task_id) 
            DO UPDATE SET 
                context = EXCLUDED.context,
                last_updated = NOW();
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    # We dump context_data into the 'context' column
                    cur.execute(query, (client_id, task_id, json.dumps(context_data)))
                conn.commit()
        except Exception as e:
            print(f"Error saving context: {e}")

    def save_pipeline(self, client_id, task_id, pipeline_data, dsl_name):
        """Saves the full pipeline blueprint for later reference."""
        query = text("""
            INSERT INTO pipeline_storage (client_id, task_id, pipeline_data, dsl_name)
            VALUES (:c_id, :t_id, :data, :dsl)
            ON CONFLICT (client_id, task_id) 
            DO UPDATE SET 
                pipeline_data = EXCLUDED.pipeline_data,
                dsl_name = EXCLUDED.dsl_name;
        """)
        with self.engine.connect() as conn:
            conn.execute(query, {
                "c_id": client_id, 
                "t_id": task_id, 
                "data": json.dumps(pipeline_data),
                "dsl": dsl_name
            })
            conn.commit()

    def schedule_task(self, client_id, step_id, task_id, run_at, value, intervals):
        query = text("""
            INSERT INTO scheduler (client_id, task_id, scheduled_time, value, intervals, status, step_id)
            VALUES (:c_id, :t_id, :run_at, :va, :inter, 'pending', :s_id)
            ON CONFLICT (client_id, task_id) 
            DO UPDATE SET 
                scheduled_time = EXCLUDED.scheduled_time, 
                value = EXCLUDED.value, 
                intervals = EXCLUDED.intervals, 
                status = 'pending',
                step_id = EXCLUDED.step_id;
                     
        """)
        with self.engine.connect() as conn:
            conn.execute(query, {
                "c_id": client_id, 
                "t_id": task_id, 
                "run_at": run_at, 
                "va": value, 
                "inter": intervals,
                "s_id": step_id
            })
            conn.commit()

    def schedule_task_v2(self, client_id, task_id, run_at, value, intervals):
        query = text("""
            INSERT INTO scheduler (client_id, task_id, scheduled_time, value, intervals)
            VALUES (:c_id, :t_id, :run_at, :va, :inter)
            ON CONFLICT (client_id, task_id) 
            DO UPDATE SET 
                scheduled_time = :run_at, 
                value = :va, 
                intervals = :inter, 
                status = 'pending';
        """)
        with self.engine.connect() as conn:
            conn.execute(query, {
                "c_id": client_id, 
                "t_id": task_id, 
                "run_at": run_at, 
                "va": value,     # Matches :va
                "inter": intervals # Matches :inter
            })
            conn.commit()
    
    def get_pipeline(self, client_id, task_id):
        query = text("SELECT pipeline_data, dsl_name FROM pipeline_storage WHERE client_id = :c_id AND task_id = :t_id")
        with self.engine.connect() as conn:
            result = conn.execute(query, {"c_id": client_id, "t_id": task_id}).fetchone()
            if result:
                return {"pipeline_data": result[0], "dsl_name": result[1]}
            return None
        
    def start_log(self, run_id, client_id, task_id, dsl_name):
        """Initializes an execution log entry."""
        query = text("""
            INSERT INTO execution_logs (run_id, client_id, task_id, dsl_name, status, started_at)
            VALUES (:run_id, :c_id, :t_id, :dsl, 'running', CURRENT_TIMESTAMP)
        """)
        with self.engine.connect() as conn:
            conn.execute(query, {
                "run_id": run_id,
                "c_id": client_id,
                "t_id": task_id,
                "dsl": dsl_name
            })
            conn.commit()

    def finalize_log(self, run_id, status, logs, error_message=None):
        """Updates the log with final status, step results, and errors."""
        query = text("""
            UPDATE execution_logs 
            SET status = :status, 
                logs = :logs, 
                error_message = :err, 
                finished_at = CURRENT_TIMESTAMP
            WHERE run_id = :run_id
        """)
        with self.engine.connect() as conn:
            conn.execute(query, {
                "status": status,
                "logs": json.dumps(logs) if isinstance(logs, (list, dict)) else logs,
                "err": error_message,
                "run_id": run_id
            })
            conn.commit()

    def reschedule_after_completion(self, client_id, task_id):
        """Calculates next run time for recurring tasks or marks one-time tasks as completed."""
        query_get = text("""
            SELECT intervals, value FROM scheduler 
            WHERE client_id = :c_id AND task_id = :t_id
        """)
        
        try:
            with self.engine.connect() as conn:
                with conn.begin(): # Transaction ensures atomic update
                    row = conn.execute(query_get, {"c_id": client_id, "t_id": task_id}).fetchone()
                    
                    if not row:
                        return

                    # 1. Handle One-Time Tasks (No interval or value)
                    if not row.intervals or not row.value:
                        conn.execute(
                            text("UPDATE scheduler SET status = 'completed' WHERE client_id = :c_id AND task_id = :t_id"),
                            {"c_id": client_id, "t_id": task_id}
                        )
                        print(f"✅ Task {task_id} marked as completed.")
                        return

                    # 2. Handle Recurring Tasks
                    unit = row.intervals.lower()
                    # Mapping for relativedelta compatibility (pluralize)
                    if not unit.endswith('s'): 
                        unit += 's'
                    
                    # relativedelta(months=1), relativedelta(days=5), etc.
                    delta = {unit: int(row.value)}
                    next_run = datetime.now() + relativedelta(**delta)
                    
                    query_update = text("""
                        UPDATE scheduler 
                        SET scheduled_time = :next_at, status = 'pending'
                        WHERE client_id = :c_id AND task_id = :t_id
                    """)
                    
                    conn.execute(query_update, {
                        "next_at": next_run, 
                        "c_id": client_id, 
                        "t_id": task_id
                    })
                    print(f"🔄 Task {task_id} rescheduled for {next_run}")

        except Exception as e:
            print(f"❌ Critical failure in rescheduling {task_id}: {e}")
            # Optional: Set status to 'error' so it doesn't stay 'executing' 
            # and block future manual runs.
        
    def reschedule_after_completion_v3(self, client_id, task_id):
        """Calculates next run time for recurring tasks or marks one-time tasks as completed."""
        query_get = text("""
            SELECT intervals, value FROM scheduler 
            WHERE client_id = :c_id AND task_id = :t_id
        """)
        
        with self.engine.connect() as conn:
            with conn.begin():  # Start transaction
                row = conn.execute(query_get, {"c_id": client_id, "t_id": task_id}).fetchone()
                
                # If task doesn't exist, just exit
                if not row:
                    return

                # HANDLE ONE-TIME TASKS
                if not row.intervals or not row.value:
                    conn.execute(
                        text("UPDATE scheduler SET status = 'completed' WHERE client_id = :c_id AND task_id = :t_id"),
                        {"c_id": client_id, "t_id": task_id}
                    )
                    print(f"✅ One-time task {task_id} marked as completed.")
                    return
                    
                # HANDLE RECURRING TASKS
                service_map = {
                    "second": "seconds", "minute": "minutes", "hour": "hours", 
                    "day": "days", "month": "months", "year": "years"
                }
                
                raw_unit = row.intervals.lower()
                unit = service_map.get(raw_unit, raw_unit)
                if not unit.endswith('s'): unit += 's'
                
                try:
                    delta = {unit: row.value}
                    next_run = datetime.now() + relativedelta(**delta)
                    
                    query_update = text("""
                        UPDATE scheduler 
                        SET scheduled_time = :next_at, status = 'pending'
                        WHERE client_id = :c_id AND task_id = :t_id
                    """)
                    conn.execute(query_update, {"next_at": next_run, "c_id": client_id, "t_id": task_id})
                    print(f"🔄 Task {task_id} rescheduled for {next_run}")
                except Exception as e:
                    print(f"❌ Failed to calculate next run for {task_id}: {e}")
                    # Fallback: mark as failed so it doesn't stay in 'executing'
                    conn.execute(
                        text("UPDATE scheduler SET status = 'error' WHERE client_id = :c_id AND task_id = :t_id"),
                        {"c_id": client_id, "t_id": task_id}
                    )

    def reschedule_after_completion_v2(self, client_id, task_id):
        """Calculates the next run time based on stored intervals and resets status."""
        # 1. Get the current interval settings
        query_get = text("""
            SELECT intervals, value FROM scheduler 
            WHERE client_id = :c_id AND task_id = :t_id
        """)
        
        with self.engine.connect() as conn:
            row = conn.execute(query_get, {"c_id": client_id, "t_id": task_id}).fetchone()
            
            if not row or not row.intervals:
                return # Not a recurring task
                
            # 2. Calculate next date (e.g., now + 1 month)
            # Mapping for relativedelta compatibility
            service_map = {"second": "seconds", "minute": "minutes", "hour": "hours", 
                        "day": "days", "month": "months", "year": "years"}
            
            unit = service_map.get(row.intervals.lower(), row.intervals.lower())
            if not unit.endswith('s'): unit += 's' # Ensure plural
            
            delta = {unit: row.value}
            next_run = datetime.now() + relativedelta(**delta)
            
            # 3. Update the DB for the next round
            query_update = text("""
                UPDATE scheduler 
                SET scheduled_time = :next_at, status = 'pending'
                WHERE client_id = :c_id AND task_id = :t_id
            """)
            conn.execute(query_update, {"next_at": next_run, "c_id": client_id, "t_id": task_id})
            conn.commit()
            print(f"🔄 Task {task_id} rescheduled for {next_run}")
    
    def save_cleanup_schema(self, client_id, task_id, schema):
        query = text("""
            INSERT INTO pipeline_cleanup (client_id, task_id, delete_schema)
            VALUES (:c_id, :t_id, :schema)
            ON CONFLICT(task_id) DO UPDATE SET delete_schema = :schema
        """)
        with self.engine.connect() as conn:
            conn.execute(query, {
                "c_id": client_id, 
                "t_id": task_id, 
                "schema": json.dumps(schema)
            })
            conn.commit()

    def get_stored_ip(self):
        """Retrieves the last known IP from the database."""
        query = text("SELECT value FROM engine_metadata WHERE key = 'public_ip'")
        with self.engine.connect() as conn:
            result = conn.execute(query).fetchone()
            return result[0] if result else "0.0.0.0"

    def update_stored_ip(self, ip_address):
        """Updates the IP in the database."""
        query = text("UPDATE engine_metadata SET value = :ip WHERE key = 'public_ip'")
        with self.engine.connect() as conn:
            conn.execute(query, {"ip": ip_address})
            conn.commit()

    def get_all_active_pipelines(self):
        """
        Retrieves all unique client and task combinations currently in storage.
        Used for a global system shutdown.
        """
        query = text("SELECT client_id, task_id FROM pipeline_storage")
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query).fetchall()
                # Returns a list of dicts for the loop in execute_piper_stop
                return [{"client_id": row[0], "task_id": row[1]} for row in result]
        except Exception as e:
            print(f"❌ Error fetching all active pipelines: {e}")
            return []

    def get_tasks_by_client(self, client_id: str):
        """
        Retrieves all task IDs associated with a specific client from the pipeline storage.
        """
        # We query pipeline_storage to find every task registered to this client
        query = text("SELECT task_id FROM pipeline_storage WHERE client_id = :c_id")
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"c_id": client_id}).fetchall()
                # Returns a list of strings: ['waterfall', 'task_1', ...]
                return [row[0] for row in result]
        except Exception as e:
            print(f"❌ Error fetching tasks for client {client_id}: {e}")
            return []

    def remove_pipeline_data(self, client_id: str, task_id: str):
        """
        Permanently deletes the stored pipeline blueprint and its schedule.
        """
        # We delete from both storage and scheduler to ensure the engine 
        # 'forgets' this task entirely.
        queries = [
            text("DELETE FROM pipeline_storage WHERE client_id = :c_id AND task_id = :t_id"),
            text("DELETE FROM scheduler WHERE client_id = :c_id AND task_id = :t_id"),
            text("DELETE FROM context_manager WHERE client_id = :c_id AND task_id = :t_id"),
            text("DELETE FROM pipeline_cleanup WHERE client_id = :c_id AND task_id = :t_id") # Add this!
        ]
        
        try:
            with self.engine.connect() as conn:
                for query in queries:
                    conn.execute(query, {"c_id": client_id, "t_id": task_id})
                conn.commit()
                print(f"🗑️ Successfully purged pipeline and schedule for {task_id}")
                return True
        except Exception as e:
            print(f"❌ Error during pipeline data removal: {e}")
            return False

    def deactivate_schedule(self, client_id: str, task_id: str):
        """
        Optional: Instead of deleting, just set the status to 'stopped'.
        Useful if you want to keep the data but prevent execution.
        """
        query = text("""
            UPDATE scheduler 
            SET status = 'stopped' 
            WHERE client_id = :c_id AND task_id = :t_id
        """)
        try:
            with self.engine.connect() as conn:
                conn.execute(query, {"c_id": client_id, "t_id": task_id})
                conn.commit()
                return True
        except Exception as e:
            print(f"❌ Error deactivating schedule: {e}")
            return False

    def update_live_logs(self, run_id, logs):
        """Updates the log array in real-time while the status remains 'running'."""
        query = text("""
            UPDATE execution_logs 
            SET logs = :logs 
            WHERE run_id = :run_id
        """)
        try:
            with self.engine.connect() as conn:
                conn.execute(query, {
                    "logs": json.dumps(logs) if isinstance(logs, (list, dict)) else logs,
                    "run_id": run_id
                })
                conn.commit()
        except Exception as e:
            print(f"❌ Failed to update live logs for {run_id}: {e}")
    
    def save_webhook_registration(self, token, client_id, task_id, app_name, webhook_id):
        """Persists the webhook token and associated metadata."""
        query = text("""
            INSERT INTO webhook_registry (webhook_token, client_id, task_id, webhook_id, app_name, created_at)
            VALUES (:token, :c_id, :t_id, :w_id, :app, NOW())
            ON CONFLICT (webhook_token) DO UPDATE SET
                client_id = EXCLUDED.client_id,
                task_id = EXCLUDED.task_id,
                webhook_id = EXCLUDED.webhook_id,
                app_name = EXCLUDED.app_name;
        """)
        try:
            with self.engine.connect() as conn:
                conn.execute(query, {
                    "token": token,
                    "c_id": client_id,
                    "t_id": task_id,
                    "w_id": webhook_id,
                    "app": app_name
                })
                conn.commit()
            return True
        except Exception as e:
            print(f"❌ Failed to save webhook token: {e}")
            return False

    def resolve_webhook_token(self, token: str):
        """Retrieves metadata associated with a secret webhook token."""
        query = text("""
            SELECT client_id, task_id, app_name 
            FROM webhook_registry 
            WHERE webhook_token = :token
        """)
        with self.engine.connect() as conn:
            result = conn.execute(query, {"token": token}).fetchone()
            if result:
                return {
                    "client_id": result[0],
                    "task_id": result[1],
                    "app_name": result[2]
                }
            return None
        
    def get_execution_logs(self, run_id: str):
        """
        Retrieves status and logs for a specific run_id.
        Perfect for sending via WebSocket to the app drawer.
        """
        query = text("""
            SELECT status, logs, error_message 
            FROM execution_logs 
            WHERE run_id = :run_id
        """)
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"run_id": run_id}).fetchone()
                
                if result:
                    # Return as a clean dictionary for the WebSocket
                    return {
                        "status": result[0],
                        "logs": result[1],
                        "error_message": result[2]
                    }
                return {"status": "not_found", "logs": []}
                
        except Exception as e:
            print(f"❌ Error fetching logs for {run_id}: {e}")
            return {"status": "error", "logs": []}
        
    def get_latest_logs_for_task(self, client_id: str, task_id: str):
        """
        Fetches the most recent log entry for a specific pipeline task.
        """
        query = text("""
            SELECT logs, status, error_message 
            FROM execution_logs 
            WHERE client_id = :c_id AND task_id = :t_id 
            ORDER BY id DESC LIMIT 1
        """)
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"c_id": client_id, "t_id": task_id}).fetchone()
                if result:
                    return {
                        "logs": result[0],
                        "status": result[1],
                        "error_message": result[2]
                    }
                return {"logs": [], "status": "pending", "error_message": None}
        except Exception as e:
            print(f"❌ Error fetching initial logs: {e}")
            return {"logs": [], "status": "error", "error_message": str(e)}

    # In shared/database_manager.py

    def save_validation_logs(self, client_id, task_id, logs_json):
        query = text("""
            INSERT INTO validation_history (client_id, task_id, logs, created_at)
            VALUES (:c_id, :t_id, :logs, NOW())
            ON CONFLICT (client_id, task_id) 
            DO UPDATE SET logs = EXCLUDED.logs, created_at = NOW();
        """)
        with self.engine.begin() as conn:
            conn.execute(query, {"c_id": client_id, "t_id": task_id, "logs": json.dumps(logs_json)})

    def get_validation_logs(self, client_id, task_id):
        query = text("""
            SELECT logs FROM validation_history 
            WHERE client_id = :c_id AND task_id = :t_id
            ORDER BY created_at DESC LIMIT 1;
        """)
        with self.engine.connect() as conn:
            result = conn.execute(query, {"c_id": client_id, "t_id": task_id}).fetchone()
            return result[0] if result else []
        
    def save_checkpoint(self, run_id, state_data):
        query = text("""
            INSERT INTO workflow_checkpoints (run_id, state, updated_at)
            VALUES (:r_id, :data, NOW())
            ON CONFLICT (run_id) 
            DO UPDATE SET state = EXCLUDED.state, updated_at = NOW();
        """)
        with self.engine.connect() as conn:
            conn.execute(query, {"r_id": run_id, "data": json.dumps(state_data)})
            conn.commit()

    def get_checkpoint(self, run_id):
        query = text("SELECT state FROM workflow_checkpoints WHERE run_id = :r_id")
        with self.engine.connect() as conn:
            result = conn.execute(query, {"r_id": run_id}).fetchone()
            return json.loads(result[0]) if result else None