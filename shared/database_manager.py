import os
import json
from sqlalchemy import create_engine, text
from dateutil.relativedelta import relativedelta
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from shared.registry_V2 import ValidationState

class ContextDB:
    _instance = None
    _engine = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(ContextDB, cls).__new__(cls)
            cls._instance._init_engine()
        return cls._instance

    def _init_engine(self):
        """Initializes the SQLAlchemy engine strictly once as a singleton with safe pool bounds."""
        if ContextDB._engine is None:
            db_url = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/piper_db")
            ContextDB._engine = create_engine(
                db_url,
                pool_size=5,          # Maximum permanent connections maintained in pool
                max_overflow=10,      # Extra connections allowed during peak traffic spikes
                pool_timeout=30,      # Seconds to wait for a connection before throwing an error
                pool_recycle=300,     # Recycle connections every 5 minutes to prevent stale drops
                pool_pre_ping=True    # Test connection liveness before checking out from pool
            )
        self.engine = ContextDB._engine

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
                    return json.loads(result[0]) if isinstance(result[0], str) else result[0]
                return None
        except Exception as e:
            print(f"❌ Error fetching cleanup schema: {e}")
            return None

    def remove_service_from_vault(self, client_name: str, service_key: str):
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
        query = text("""
            SELECT task_id, pipeline_data, on_complete, on_error, on_success 
            FROM pipeline_storage 
            WHERE client_id = :c_id
        """)
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"c_id": client_id}).fetchone()
                if result:
                    return {
                        "task_id": result[0], 
                        "pipeline_data": result[1],
                        "on_complete": result[2],
                        "on_error": result[3],
                        "on_success": result[4]
                    }
                return None
        except Exception as e:
            print(f"❌ Error checking existing pipeline: {e}")
            return None
        
    def reset_pipeline_storage(self):
        queries = [
            "DROP TABLE IF EXISTS pipeline_storage;",
            """
            CREATE TABLE pipeline_storage (
                id SERIAL PRIMARY KEY,
                client_id VARCHAR(255) UNIQUE,
                dsl_name VARCHAR(255),
                task_id VARCHAR(255),
                pipeline_data JSONB,
                on_complete JSONB,
                on_error JSONB,
                on_success JSONB,
                UNIQUE(client_id, task_id)
            );
            """
        ]
        with self.engine.connect() as conn:
            for q in queries:
                conn.execute(text(q))
            conn.commit()

    def update_pipeline(self, client_id: str, task_id: str, pipeline_data: dict):
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
        queries = [
            """
            CREATE TABLE IF NOT EXISTS context_manager (
                id SERIAL PRIMARY KEY,
                event_id VARCHAR(255) UNIQUE,
                client_id VARCHAR(255) NOT NULL,
                task_id VARCHAR(255) NOT NULL,
                context JSONB DEFAULT '{}'::jsonb,
                last_updated TIMESTAMP DEFAULT NOW()
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS webhook_registry (
                webhook_token VARCHAR(255) PRIMARY KEY,
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
                on_complete JSONB,
                on_error JSONB,
                on_success JSONB,
                UNIQUE(client_id, task_id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS scheduler (
                id SERIAL PRIMARY KEY,
                client_id VARCHAR(255),
                task_id VARCHAR(255),
                scheduled_time TIMESTAMP,
                intervals VARCHAR(255),
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
                CONSTRAINT idx_client_task UNIQUE (client_id, task_id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS auth_interventions (
                id SERIAL PRIMARY KEY,
                client_id VARCHAR(255) NOT NULL,
                app_name VARCHAR(255) NOT NULL,
                auth_url TEXT NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
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
                status VARCHAR(50) DEFAULT 'running',
                logs JSONB DEFAULT '[]'::jsonb,
                error_message TEXT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP
            );"""
        ]
        with self.engine.connect() as conn:
            for q in queries:
                conn.execute(text(q))
            conn.commit()

    def upsert_on_complete(self, client_id, task_id, data, dsl_name=None):
        query = text("""
            INSERT INTO pipeline_storage (client_id, task_id, on_complete, dsl_name)
            VALUES (:c_id, :t_id, :data, :dsl)
            ON CONFLICT (client_id, task_id)
            DO UPDATE SET 
                on_complete = EXCLUDED.on_complete,
                dsl_name = COALESCE(EXCLUDED.dsl_name, pipeline_storage.dsl_name);
        """)
        with self.engine.connect() as conn:
            conn.execute(query, {
                "c_id": client_id, 
                "t_id": task_id, 
                "data": json.dumps(data),
                "dsl": dsl_name
            })
            conn.commit()

    def upsert_on_error(self, client_id, task_id, data, dsl_name=None):
        query = text("""
            INSERT INTO pipeline_storage (client_id, task_id, on_error, dsl_name)
            VALUES (:c_id, :t_id, :data, :dsl)
            ON CONFLICT (client_id, task_id)
            DO UPDATE SET 
                on_error = EXCLUDED.on_error,
                dsl_name = COALESCE(EXCLUDED.dsl_name, pipeline_storage.dsl_name);
        """)
        with self.engine.connect() as conn:
            conn.execute(query, {
                "c_id": client_id, 
                "t_id": task_id, 
                "data": json.dumps(data),
                "dsl": dsl_name
            })
            conn.commit()

    def upsert_on_success(self, client_id, task_id, data, dsl_name=None):
        query = text("""
            INSERT INTO pipeline_storage (client_id, task_id, on_success, dsl_name)
            VALUES (:c_id, :t_id, :data, :dsl)
            ON CONFLICT (client_id, task_id)
            DO UPDATE SET 
                on_success = EXCLUDED.on_success,
                dsl_name = COALESCE(EXCLUDED.dsl_name, pipeline_storage.dsl_name);
        """)
        with self.engine.connect() as conn:
            conn.execute(query, {
                "c_id": client_id, 
                "t_id": task_id, 
                "data": json.dumps(data),
                "dsl": dsl_name
            })
            conn.commit()

    def save_vault(self, client_name, vault_data):
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
        query = text("SELECT vault_data FROM piper_vault WHERE client_name = :name")
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"name": client_name}).fetchone()
                if result:
                    data = result[0]
                    return json.loads(data) if isinstance(data, str) else data
                return {}
        except Exception as e:
            print(f"❌ Error fetching vault for {client_name}: {e}")
            return {}

    def get_log_count(self, client_id, task_id):
        query = text("SELECT COUNT(*) FROM logs WHERE client_id = :c AND task_id = :t")
        with self.engine.connect() as conn:
            return conn.execute(query, {"c": client_id, "t": task_id}).scalar()

    def danger_drop_context_table(self):
        query = text("DROP TABLE IF EXISTS context_manager CASCADE;")
        try:
            with self.engine.connect() as conn:
                conn.execute(query)
                conn.commit()
            print("🗑️ Table 'context_manager' dropped successfully.")
        except Exception as e:
            print(f"❌ Failed to drop table: {e}")

    def save_version(self, client_id, version):
        query = text("""
            INSERT INTO version_registry (client_id, version_tag, updated_at)
            VALUES (:c_id, :v, NOW())
            ON CONFLICT (client_id) DO UPDATE SET version_tag = EXCLUDED.version_tag, updated_at = NOW();
        """)
        with self.engine.connect() as conn:
            conn.execute(query, {"c_id": client_id, "v": version})
            conn.commit()

    def get_version(self, client_id):
        query = text("SELECT version_tag FROM version_registry WHERE client_id = :c_id")
        with self.engine.connect() as conn:
            result = conn.execute(query, {"c_id": client_id}).fetchone()
            return result[0] if result else "latest"
    
    def get_context_v2(self, client_id: str, task_id: str):
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
        query = text("""
            INSERT INTO auth_interventions (client_id, app_name, auth_url, status)
            VALUES (:c_id, :app, :url, 'pending')
        """)
        with self.engine.connect() as conn:
            conn.execute(query, {"c_id": client_id, "app": app_name, "url": auth_url})
            conn.commit()

    def get_pending_interventions(self):
        query = text("""
            SELECT id, app_name, auth_url 
            FROM auth_interventions 
            WHERE status = 'pending'
            ORDER BY created_at DESC
        """)
        with self.engine.connect() as conn:
            result = conn.execute(query).fetchall()
            return [dict(row._mapping) for row in result]

    def mark_intervention_resolved(self, intervention_id):
        query = text("UPDATE auth_interventions SET status = 'resolved' WHERE id = :id")
        with self.engine.connect() as conn:
            conn.execute(query, {"id": intervention_id})
            conn.commit()

    def danger_drop_all_tables(self):
        tables_to_drop = [
            "context_manager", "webhook_registry", "piper_vault",
            "pipeline_storage", "scheduler", "version_registry",
            "pipeline_cleanup", "execution_logs", "workflow_checkpoints"
        ]
        queries = [f"DROP TABLE IF EXISTS {table} CASCADE;" for table in tables_to_drop]
        try:
            print("⚠️ Initializing complete system database purge...")
            with self.engine.connect() as conn:
                with conn.begin():
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
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (event_id, client_id, task_id, json.dumps(context_data)))
                conn.commit()
        except Exception as e:
            print(f"Error saving context: {e}")

    def save_context_v2(self, client_id: str, task_id: str, context_data: dict):
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
                    cur.execute(query, (client_id, task_id, json.dumps(context_data)))
                conn.commit()
        except Exception as e:
            print(f"Error saving context: {e}")

    def save_pipeline(self, client_id, task_id, pipeline_data, dsl_name):
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
                "c_id": client_id, "t_id": task_id, 
                "data": json.dumps(pipeline_data), "dsl": dsl_name
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
                "c_id": client_id, "t_id": task_id, "run_at": run_at, 
                "va": value, "inter": intervals, "s_id": step_id
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
                "c_id": client_id, "t_id": task_id, 
                "run_at": run_at, "va": value, "inter": intervals
            })
            conn.commit()
    
    def get_pipeline(self, client_id, task_id):
        query = text("SELECT pipeline_data, dsl_name FROM pipeline_storage WHERE client_id = :c_id AND task_id = :t_id")
        with self.engine.connect() as conn:
            result = conn.execute(query, {"c_id": client_id, "t_id": task_id}).fetchone()
            if result:
                return {
                    "pipeline_data": result[0], 
                    "on_complete": result[1],
                    "on_error": result[2],
                    "on_success": result[3],
                    "dsl_name": result[4]
                }
            return None
        
    def start_log(self, run_id, client_id, task_id, dsl_name):
        query = text("""
            INSERT INTO execution_logs (run_id, client_id, task_id, dsl_name, status, started_at)
            VALUES (:run_id, :c_id, :t_id, :dsl, 'running', CURRENT_TIMESTAMP)
        """)
        with self.engine.connect() as conn:
            conn.execute(query, {"run_id": run_id, "c_id": client_id, "t_id": task_id, "dsl": dsl_name})
            conn.commit()

    def finalize_log(self, run_id, status, logs, error_message=None):
        query = text("""
            UPDATE execution_logs 
            SET status = :status, logs = :logs, error_message = :err, finished_at = CURRENT_TIMESTAMP
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
        query_get = text("SELECT intervals, value FROM scheduler WHERE client_id = :c_id AND task_id = :t_id")
        try:
            with self.engine.connect() as conn:
                with conn.begin():
                    row = conn.execute(query_get, {"c_id": client_id, "t_id": task_id}).fetchone()
                    if not row:
                        return
                    if not row.intervals or not row.value:
                        conn.execute(
                            text("UPDATE scheduler SET status = 'completed' WHERE client_id = :c_id AND task_id = :t_id"),
                            {"c_id": client_id, "t_id": task_id}
                        )
                        return
                    unit = row.intervals.lower()
                    if not unit.endswith('s'): unit += 's'
                    delta = {unit: int(row.value)}
                    next_run = datetime.now() + relativedelta(**delta)
                    conn.execute(
                        text("UPDATE scheduler SET scheduled_time = :next_at, status = 'pending' WHERE client_id = :c_id AND task_id = :t_id"),
                        {"next_at": next_run, "c_id": client_id, "t_id": task_id}
                    )
        except Exception as e:
            print(f"❌ Critical failure in rescheduling {task_id}: {e}")
        
    def reschedule_after_completion_v3(self, client_id, task_id):
        query_get = text("SELECT intervals, value FROM scheduler WHERE client_id = :c_id AND task_id = :t_id")
        with self.engine.connect() as conn:
            with conn.begin():
                row = conn.execute(query_get, {"c_id": client_id, "t_id": task_id}).fetchone()
                if not row: return
                if not row.intervals or not row.value:
                    conn.execute(text("UPDATE scheduler SET status = 'completed' WHERE client_id = :c_id AND task_id = :t_id"), {"c_id": client_id, "t_id": task_id})
                    return
                service_map = {"second": "seconds", "minute": "minutes", "hour": "hours", "day": "days", "month": "months", "year": "years"}
                raw_unit = row.intervals.lower()
                unit = service_map.get(raw_unit, raw_unit)
                if not unit.endswith('s'): unit += 's'
                try:
                    delta = {unit: row.value}
                    next_run = datetime.now() + relativedelta(**delta)
                    conn.execute(text("UPDATE scheduler SET scheduled_time = :next_at, status = 'pending' WHERE client_id = :c_id AND task_id = :t_id"), {"next_at": next_run, "c_id": client_id, "t_id": task_id})
                except Exception as e:
                    conn.execute(text("UPDATE scheduler SET status = 'error' WHERE client_id = :c_id AND task_id = :t_id"), {"c_id": client_id, "t_id": task_id})

    def reschedule_after_completion_v2(self, client_id, task_id):
        query_get = text("SELECT intervals, value FROM scheduler WHERE client_id = :c_id AND task_id = :t_id")
        with self.engine.connect() as conn:
            row = conn.execute(query_get, {"c_id": client_id, "t_id": task_id}).fetchone()
            if not row or not row.intervals: return
            service_map = {"second": "seconds", "minute": "minutes", "hour": "hours", "day": "days", "month": "months", "year": "years"}
            unit = service_map.get(row.intervals.lower(), row.intervals.lower())
            if not unit.endswith('s'): unit += 's'
            delta = {unit: row.value}
            next_run = datetime.now() + relativedelta(**delta)
            conn.execute(text("UPDATE scheduler SET scheduled_time = :next_at, status = 'pending' WHERE client_id = :c_id AND task_id = :t_id"), {"next_at": next_run, "c_id": client_id, "t_id": task_id})
            conn.commit()
    
    def save_cleanup_schema(self, client_id, task_id, schema):
        query = text("""
            INSERT INTO pipeline_cleanup (client_id, task_id, delete_schema)
            VALUES (:c_id, :t_id, :schema)
            ON CONFLICT(task_id) DO UPDATE SET delete_schema = :schema
        """)
        with self.engine.connect() as conn:
            conn.execute(query, {"c_id": client_id, "t_id": task_id, "schema": json.dumps(schema)})
            conn.commit()

    def get_stored_ip(self):
        query = text("SELECT value FROM engine_metadata WHERE key = 'public_ip'")
        with self.engine.connect() as conn:
            result = conn.execute(query).fetchone()
            return result[0] if result else "0.0.0.0"

    def update_stored_ip(self, ip_address):
        query = text("UPDATE engine_metadata SET value = :ip WHERE key = 'public_ip'")
        with self.engine.connect() as conn:
            conn.execute(query, {"ip": ip_address})
            conn.commit()

    def get_all_active_pipelines(self):
        query = text("SELECT client_id, task_id FROM pipeline_storage")
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query).fetchall()
                return [{"client_id": row[0], "task_id": row[1]} for row in result]
        except Exception as e:
            print(f"❌ Error fetching all active pipelines: {e}")
            return []

    def get_tasks_by_client(self, client_id: str):
        query = text("SELECT task_id FROM pipeline_storage WHERE client_id = :c_id")
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"c_id": client_id}).fetchall()
                return [row[0] for row in result]
        except Exception as e:
            print(f"❌ Error fetching tasks for client {client_id}: {e}")
            return []

    def remove_pipeline_data(self, client_id: str, task_id: str):
        queries = [
            text("DELETE FROM pipeline_storage WHERE client_id = :c_id AND task_id = :t_id"),
            text("DELETE FROM scheduler WHERE client_id = :c_id AND task_id = :t_id"),
            text("DELETE FROM context_manager WHERE client_id = :c_id AND task_id = :t_id"),
            text("DELETE FROM pipeline_cleanup WHERE client_id = :c_id AND task_id = :t_id")
        ]
        try:
            with self.engine.connect() as conn:
                for query in queries:
                    conn.execute(query, {"c_id": client_id, "t_id": task_id})
                conn.commit()
                return True
        except Exception as e:
            print(f"❌ Error during pipeline data removal: {e}")
            return False

    def deactivate_schedule(self, client_id: str, task_id: str):
        query = text("UPDATE scheduler SET status = 'stopped' WHERE client_id = :c_id AND task_id = :t_id")
        try:
            with self.engine.connect() as conn:
                conn.execute(query, {"c_id": client_id, "t_id": task_id})
                conn.commit()
                return True
        except Exception as e:
            print(f"❌ Error deactivating schedule: {e}")
            return False

    def update_live_logs(self, run_id, logs):
        query = text("UPDATE execution_logs SET logs = :logs WHERE run_id = :run_id")
        try:
            with self.engine.connect() as conn:
                conn.execute(query, {"logs": json.dumps(logs) if isinstance(logs, (list, dict)) else logs, "run_id": run_id})
                conn.commit()
        except Exception as e:
            print(f"❌ Failed to update live logs for {run_id}: {e}")
    
    def save_webhook_registration(self, token, client_id, task_id, app_name, webhook_id):
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
                conn.execute(query, {"token": token, "c_id": client_id, "t_id": task_id, "w_id": webhook_id, "app": app_name})
                conn.commit()
            return True
        except Exception as e:
            print(f"❌ Failed to save webhook token: {e}")
            return False

    def resolve_webhook_token(self, token: str):
        query = text("SELECT client_id, task_id, app_name FROM webhook_registry WHERE webhook_token = :token")
        with self.engine.connect() as conn:
            result = conn.execute(query, {"token": token}).fetchone()
            if result:
                return {"client_id": result[0], "task_id": result[1], "app_name": result[2]}
            return None
        
    def get_execution_logs(self, run_id: str):
        query = text("SELECT status, logs, error_message FROM execution_logs WHERE run_id = :run_id")
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"run_id": run_id}).fetchone()
                if result:
                    return {"status": result[0], "logs": result[1], "error_message": result[2]}
                return {"status": "not_found", "logs": []}
        except Exception as e:
            return {"status": "error", "logs": []}
        
    def get_latest_logs_for_task(self, client_id: str, task_id: str):
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
                    return {"logs": result[0], "status": result[1], "error_message": result[2]}
                return {"logs": [], "status": "pending", "error_message": None}
        except Exception as e:
            return {"logs": [], "status": "error", "error_message": str(e)}

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