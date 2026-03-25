import os
import json
from sqlalchemy import create_engine, text

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

    def initialize_tables(self):
        """Creates the necessary database structure silently."""
        query = text("""
            CREATE TABLE IF NOT EXISTS context_manager (
                id SERIAL PRIMARY KEY,
                client_id VARCHAR(255),
                task_id VARCHAR(255),
                context_data JSONB,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(client_id, task_id)
            );
        """)
        with self.engine.connect() as conn:
            conn.execute(query)
            conn.commit()

    def save_context(self, client_id, task_id, data):
        query = text("""
            INSERT INTO context_manager (client_id, task_id, context_data)
            VALUES (:c_id, :t_id, :data)
            ON CONFLICT (client_id, task_id) 
            DO UPDATE SET context_data = :data, updated_at = NOW();
        """)
        with self.engine.connect() as conn:
            conn.execute(query, {
                "c_id": client_id, 
                "t_id": task_id, 
                "data": json.dumps(data)
            })
            conn.commit()

    def get_context(self, client_id, task_id):
        query = text("SELECT context_data FROM context_manager WHERE client_id = :c_id AND task_id = :t_id")
        with self.engine.connect() as conn:
            result = conn.execute(query, {"c_id": client_id, "t_id": task_id}).fetchone()
            # result[0] is the context_data column
            return json.loads(result[0]) if result else None