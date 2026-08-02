import os
from sqlalchemy import create_engine, text, exc
import secrets

class ContextDB:
    def __init__(self):
        # Defaulting to a generic string; use env vars for productioN
        self.db_url = "postgresql://postgres:KyfNdoFybNKMtdNttOCgKpsNDIblknrO@postgres.railway.internal:5432/railway"
        self.engine = create_engine(self.db_url)
        self.add_api_key_column()
        self.initialize_tables()

    def add_api_key_column(self):
        """Ensures the api_key column exists in the instances table."""
        try:
            with self.engine.begin() as conn:
                conn.execute(text("ALTER TABLE instances ADD COLUMN IF NOT EXISTS api_key TEXT UNIQUE;"))
            print("Successfully verified/updated database schema: 'api_key' column exists.")
        except exc.SQLAlchemyError as e:
            print(f"Error updating schema for 'api_key': {e}")

    def check_connection(self):
        """Silently checks if the DB is reachable."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except exc.SQLAlchemyError:
            return False

    def initialize_tables(self):
        """Creates the necessary database structure."""
        queries = [
            'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";',
            """
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """,
            # In your ContextDB class, update the instances table creation
            """
            CREATE TABLE IF NOT EXISTS instances (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                user_id UUID REFERENCES users(id) ON DELETE CASCADE,
                subdomain TEXT UNIQUE NOT NULL,
                installation_type TEXT CHECK (installation_type IN ('cloud', 'local')),
                engine_installed BOOLEAN DEFAULT FALSE,
                subscription_active BOOLEAN DEFAULT FALSE,
                trial_start_date TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                api_key TEXT UNIQUE  -- ADD THIS
            );
            """
            "CREATE INDEX IF NOT EXISTS idx_instances_subdomain ON instances(subdomain);"
        ]
        
        try:
            with self.engine.begin() as conn:
                for q in queries:
                    conn.execute(text(q))
            print("Database initialized successfully.")
        except exc.SQLAlchemyError as e:
            print(f"Error initializing database: {e}")
            raise

    def get_user_by_email(self, email: str):
        """Retrieves a user by email."""
        with self.engine.connect() as conn:
            query = text("SELECT id, email, password_hash, created_at FROM users WHERE email = :email")
            result = conn.execute(query, {"email": email}).fetchone()
            return result

    def get_user_status(self, email: str):
        """Retrieves installation status, subscription status, subdomain, and trial start date."""
        with self.engine.connect() as conn:
            query = text("""
                SELECT i.engine_installed, i.subscription_active, i.subdomain, i.trial_start_date 
                FROM instances i
                JOIN users u ON i.user_id = u.id
                WHERE u.email = :email
            """)
            result = conn.execute(query, {"email": email}).fetchone()
            return result
        
    def add_user(self, email: str, password_hash: str):
        with self.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO users (email, password_hash) VALUES (:email, :pwd)"),
                {"email": email, "pwd": password_hash}
            )

    def update_user_password(self, email: str, password_hash: str):
        """Updates the user's password hash in the database."""
        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE users SET password_hash = :pwd WHERE email = :email"),
                {"email": email, "pwd": password_hash}
            )

    def assign_user_subdomain(self, user_email: str, subdomain: str):
        with self.engine.begin() as conn:
            user = self.get_user_by_email(user_email)
            if not user: raise ValueError("User not found")
            
            # Generate a high-entropy 32-character key
            secret_api_key = secrets.token_urlsafe(32)
            
            conn.execute(text("""
                INSERT INTO instances (user_id, subdomain, engine_installed, trial_start_date, api_key)
                VALUES (:user_id, :subdomain, FALSE, NOW(), :api_key)
                ON CONFLICT (subdomain) DO NOTHING;
            """), {"user_id": user.id, "subdomain": subdomain, "api_key": secret_api_key})

    def mark_engine_installed(self, user_id: str, inst_type: str):
        """Called ONLY after a successful installation using the user's UUID."""
        with self.engine.begin() as conn:
            conn.execute(text("""
                UPDATE instances 
                SET engine_installed = TRUE, 
                    installation_type = :inst_type, 
                    updated_at = NOW()
                WHERE user_id = :user_id;
            """), {"user_id": user_id, "inst_type": inst_type})

    def get_engine_config_by_identifier(self, identifier: str, is_email: bool):
        with self.engine.connect() as conn:
            if is_email:
                query = text("""
                    SELECT u.email, u.id as user_id, i.subdomain, i.api_key, i.installation_type
                    FROM instances i
                    JOIN users u ON i.user_id = u.id
                    WHERE u.email = :val
                """)
            else:
                query = text("""
                    SELECT u.email, u.id as user_id, i.subdomain, i.api_key, i.installation_type
                    FROM instances i
                    JOIN users u ON i.user_id = u.id
                    WHERE u.id = :val
                """)
            
            # Execute with the appropriate identifier
            result = conn.execute(query, {"val": identifier}).fetchone()
            return result
        
    def get_user_subdomain(self, user_email: str):
        """Retrieves the subdomain associated with a user."""
        with self.engine.connect() as conn:
            query = text("""
                SELECT i.subdomain, i.engine_installed 
                FROM instances i
                JOIN users u ON i.user_id = u.id
                WHERE u.email = :email
            """)
            result = conn.execute(query, {"email": user_email}).fetchone()
            return result

    def update_engine_installation_status(self, email: str, status: bool, inst_type: str = None):
        """
        Updates the engine installation status flag dynamically based on user email.
        Allows setting installation type if provided, or resetting it if passing False.
        """
        with self.engine.begin() as conn:
            # First look up the user's id via email
            user = self.get_user_by_email(email)
            if not user:
                raise ValueError(f"User with email '{email}' not found.")
            
            # Construct dynamic query to optionally update install type string
            if inst_type:
                query = """
                    UPDATE instances 
                    SET engine_installed = :status, 
                        installation_type = :inst_type, 
                        updated_at = NOW()
                    WHERE user_id = :user_id;
                """
                params = {"status": status, "inst_type": inst_type, "user_id": user.id}
            else:
                query = """
                    UPDATE instances 
                    SET engine_installed = :status, 
                        updated_at = NOW()
                    WHERE user_id = :user_id;
                """
                params = {"status": status, "user_id": user.id}
                
            conn.execute(text(query), params)