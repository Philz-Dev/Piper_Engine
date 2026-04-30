import os
import json
from sqlalchemy import create_engine, text
from dateutil import relativedelta
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

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
    
    def upsert_pipeline(self, client_id, new_task_id, pipeline_data):
        """
        If client exists, updates the pipeline and returns the OLD task_id.
        If client is new, saves it and returns the NEW task_id.
        """
        # We look for client_id only to see if they already have a configuration
        query = text("""
            INSERT INTO pipeline_storage (client_id, task_id, pipeline_data)
            VALUES (:c_id, :t_id, :data)
            ON CONFLICT (client_id) 
            DO UPDATE SET 
                pipeline_data = EXCLUDED.pipeline_data
            RETURNING task_id;
        """)
        
        with self.engine.connect() as conn:
            # We need to ensure the table has a UNIQUE constraint on client_id alone
            # for this specific 'per-client' logic to work.
            result = conn.execute(query, {
                "c_id": client_id, 
                "t_id": new_task_id, 
                "data": json.dumps(pipeline_data)
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
                client_id VARCHAR(255) NOT NULL,
                task_id VARCHAR(255) NOT NULL,
                context JSONB DEFAULT '{}'::jsonb, -- This matches your variable name
                last_updated TIMESTAMP DEFAULT NOW(),
                UNIQUE(client_id, task_id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS pipeline_storage (
                id SERIAL PRIMARY KEY,
                client_id VARCHAR(255) UNIQUE,
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
                status VARCHAR(50) DEFAULT 'pending', 
                UNIQUE(client_id, task_id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS version_registry (
                client_id VARCHAR(255) PRIMARY KEY,
                version_tag VARCHAR(50) DEFAULT 'latest',
                updated_at TIMESTAMP DEFAULT NOW()
            );
            """
        ]
        with self.engine.connect() as conn:
            for q in queries:
                conn.execute(text(q))
            conn.commit()

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
    
    def get_context(self, client_id: str, task_id: str):
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

    def save_context(self, client_id: str, task_id: str, context_data: dict):
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

    def save_pipeline(self, client_id, task_id, pipeline_data):
        """Saves the full pipeline blueprint for later reference."""
        query = text("""
            INSERT INTO pipeline_storage (client_id, task_id, pipeline_data)
            VALUES (:c_id, :t_id, :data)
            ON CONFLICT (client_id, task_id) DO UPDATE SET pipeline_data = :data;
        """)
        with self.engine.connect() as conn:
            conn.execute(query, {"c_id": client_id, "t_id": task_id, "data": json.dumps(pipeline_data)})
            conn.commit()

    def schedule_task(self, client_id, task_id, run_at, value, intervals):
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
        query = text("SELECT pipeline_data FROM pipeline_storage WHERE client_id = :c_id AND task_id = :t_id")
        with self.engine.connect() as conn:
            result = conn.execute(query, {"c_id": client_id, "t_id": task_id}).fetchone()
            return result[0] if result else None

    def reschedule_after_completion(self, client_id, task_id):
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