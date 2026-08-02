import os
import random
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from passlib.context import CryptContext
import uvicorn
from database_manager import ContextDB
from ssh_manager import SSHManager
from dns_manager import DNSManager
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import bcrypt
import types
import requests as http_requests
from signaling import sio, connected_workers
import socketio

if not hasattr(bcrypt, "__about__"):
    bcrypt.__about__ = types.SimpleNamespace(__version__=bcrypt.__version__)

# Compatibility patch for passlib and modern bcrypt versions
# 1. Setup

app = FastAPI()

# Add CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://www.stretis.com",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


socket_app = socketio.ASGIApp(
    sio,
    other_asgi_app=app
)


db_manager = ContextDB()

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__truncate_error=False,
)

# Temporary store for pending signups: {email: {"code": str, "password_hash": str, "expires": datetime}}
pending_signups = {}
# Temporary store for pending password resets: {email: {"code": str, "expires": datetime}}
pending_resets = {}

def send_verification_email(to_email: str, code: str):
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_user = os.getenv("SMTP_USER", "thanoswiths@gmail.com")
    smtp_pass = os.getenv("SMTP_PASS", "qbqptvkkxyuziyka")
    
    if not smtp_user or not smtp_pass:
        print(f"[DEV] Verification code for {to_email}: {code}")
        return
        
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"Piper Engine <{smtp_user}>"
        msg["To"] = to_email
        msg["Subject"] = "Your Piper Engine Verification Code"
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="gmail.com")
        
        text_content = f"Hello,\n\nYour verification code for Piper Engine is: {code}\n\nThis code will expire in 10 minutes.\n\nIf you did not request this, please ignore this email."
        html_content = f"""
        <div style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
            <h2 style="color: #2563eb;">Piper Engine Verification</h2>
            <p>Hello,</p>
            <p>Your verification code is:</p>
            <div style="font-size: 24px; font-weight: bold; background: #f3f4f6; padding: 12px 20px; border-radius: 8px; display: inline-block; letter-spacing: 4px; color: #1e3a8a;">{code}</div>
            <p style="margin-top: 20px; font-size: 12px; color: #6b7280;">This code will expire in 10 minutes. If you did not request this, please ignore this email.</p>
        </div>
        """
        
        msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))
        
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls(context=context)
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
    except Exception as e:
        print(f"Failed to send email: {e}")

@app.get("/")
def read_root():
    return {"status": "Piper API is running"}

# Dependency
def get_db():
    return db_manager

class AuthSchema(BaseModel):
    email: str
    password: str

class VerifySchema(BaseModel):
    email: str
    code: str

class ForgotPasswordSchema(BaseModel):
    email: str

class ResetPasswordSchema(BaseModel):
    email: str
    code: str
    new_password: str

class GoogleAuthSchema(BaseModel):
    token: str

class InstallSchema(BaseModel):
    ip_address: str
    ssh_username: str
    ssh_key_path: str  
    command: str

class TaskPayload(BaseModel):
    task_id: str
    action: str
    params: dict = {}

@app.post("/api/v1/engine/execute")
async def trigger_task(user_id: str, task: TaskPayload):
    target_sid = connected_workers.get(user_id)
    if not target_sid:
        raise HTTPException(status_code=404, detail="Agent is offline")

    await sio.emit('execute_task', task.dict(), to=target_sid)
    return {"status": "Task sent"}

# 3. Routes
@app.post("/signup")
def signup(auth: AuthSchema, db: ContextDB = Depends(get_db)):
    print(f"[DEBUG] Signup payload: {auth.dict()}")
    user_email = auth.email.strip().lower()
    existing = db.get_user_by_email(user_email)
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")
    safe_password = auth.password[:72]
    hashed = pwd_context.hash(safe_password)
    
    code = f"{random.randint(100000, 999999)}"
    pending_signups[user_email] = {
        "code": code,
        "password_hash": hashed,
        "expires": datetime.now(timezone.utc) + timedelta(minutes=10)
    }
    
    send_verification_email(user_email, code)
    return {"message": "Verification code sent"}

@app.post("/signup/verify")
def signup_verify(verify: VerifySchema, db: ContextDB = Depends(get_db)):
    user_email = verify.email.strip().lower()
    record = pending_signups.get(user_email)
    if not record:
        raise HTTPException(status_code=400, detail="No pending signup found or code expired")
    
    if datetime.now(timezone.utc) > record["expires"]:
        del pending_signups[user_email]
        raise HTTPException(status_code=400, detail="Verification code expired")
        
    if record["code"] != verify.code:
        raise HTTPException(status_code=400, detail="Invalid verification code")
        
    db.add_user(user_email, record["password_hash"])
    subdomain = user_email.split('@')[0]
    db.assign_user_subdomain(user_email, subdomain)
    
    del pending_signups[user_email]
    return {"message": "Success"}

@app.post("/forgot-password")
def forgot_password(payload: ForgotPasswordSchema, db: ContextDB = Depends(get_db)):
    user_email = payload.email.strip().lower()
    user = db.get_user_by_email(user_email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    code = f"{random.randint(100000, 999999)}"
    pending_resets[user_email] = {
        "code": code,
        "expires": datetime.now(timezone.utc) + timedelta(minutes=10)
    }
    
    send_verification_email(user_email, code)
    return {"message": "Password reset code sent"}

@app.post("/reset-password")
def reset_password(payload: ResetPasswordSchema, db: ContextDB = Depends(get_db)):
    user_email = payload.email.strip().lower()
    record = pending_resets.get(user_email)
    if not record:
        raise HTTPException(status_code=400, detail="No pending password reset found or code expired")
    
    if datetime.now(timezone.utc) > record["expires"]:
        del pending_resets[user_email]
        raise HTTPException(status_code=400, detail="Verification code expired")
        
    if record["code"] != payload.code:
        raise HTTPException(status_code=400, detail="Invalid verification code")
        
    safe_password = payload.new_password[:72]
    hashed = pwd_context.hash(safe_password)
    
    if hasattr(db, "update_user_password"):
        db.update_user_password(user_email, hashed)
    elif hasattr(db, "update_password"):
        db.update_password(user_email, hashed)
    else:
        db.update_user_password(user_email, hashed)
        
    del pending_resets[user_email]
    return {"message": "Password reset successfully"}

@app.post("/login")
def login(auth: AuthSchema, db: ContextDB = Depends(get_db)):
    user_email = auth.email.strip().lower()
    
    user = db.get_user_by_email(user_email)
    if not user or not pwd_context.verify(auth.password[:72], user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {
        "message": "Authenticated", 
        "email": user_email,
        "id": str(user.id) # Include ID as well, you'll need it
    }

@app.post("/auth/google")
def auth_google(auth: GoogleAuthSchema, db: ContextDB = Depends(get_db)):
    try:
        # Query Google's userinfo API using the access token
        google_res = http_requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {auth.token}"}
        )
        
        if google_res.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid access token from Google")
            
        idinfo = google_res.json()
        raw_email = idinfo.get("email")
        
        if not raw_email:
            raise HTTPException(status_code=400, detail="Google token missing email")
            
        user_email = raw_email.strip().lower()
        user = db.get_user_by_email(user_email)
        
        if not user:
            safe_password = "google_oauth_secure_placeholder"[:72]
            hashed = pwd_context.hash(safe_password)
            db.add_user(user_email, hashed)
            subdomain = user_email.split('@')[0]
            db.assign_user_subdomain(user_email, subdomain)
            
        return {"message": "Google Authenticated", "email": user_email}
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {str(e)}")
    
@app.get("/api/v1/engine/command/{email}")
def get_engine_command_by_email(email: str, db: ContextDB = Depends(get_db)):
    """
    Retrieves the user ID through email from the db, attaches it to the setup command, and returns it to the UI.
    """
    user_email = email.strip().lower()
    user = db.get_user_by_email(user_email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    user_id = str(user.id)
    github_repo = os.getenv("GITHUB_REPO", "piper_install")
    command = f"curl -sSL https://raw.githubusercontent.com/philz-dev/{github_repo}/main/setup.sh | bash -s -- {user_id}"
    
    return {
        "user_id": user_id,
        "command": command
    }
    
@app.get("/api/v1/engine/config/{identifier}")
def get_engine_config_by_id(identifier: str, db: ContextDB = Depends(get_db)):
    # 1. Detect if the identifier is an email (contains @)
    is_email = "@" in identifier
    
    # 2. Call the database
    # We will modify the database manager to handle both
    res = db.get_engine_config_by_identifier(identifier, is_email=is_email)
    
    if not res:
        raise HTTPException(status_code=404, detail="User instance not found")
        
    return {
        "user_id": str(res.user_id), # Ensure it returns the UUID
        "email": res.email,
        "domain": f"{res.subdomain}.yourdomain.com",
        "install_token": res.api_key,
        "installation_type": res.installation_type
    }

@app.post("/auth/google/id")
def auth_google_id(auth: GoogleAuthSchema, db: ContextDB = Depends(get_db)):
    try:
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        try:
            idinfo = id_token.verify_oauth2_token(auth.token, google_requests.Request(), client_id)
        except Exception:
            idinfo = id_token.verify_oauth2_token(auth.token, google_requests.Request())
        
        raw_email = idinfo.get("email")
        if not raw_email:
            raise HTTPException(status_code=400, detail="Google token missing email")
        user_email = raw_email.strip().lower()
        
        user = db.get_user_by_email(user_email)
        if not user:
            safe_password = "google_oauth_secure_placeholder"[:72]
            hashed = pwd_context.hash(safe_password)
            db.add_user(user_email, hashed)
            subdomain = user_email.split('@')[0]
            db.assign_user_subdomain(user_email, subdomain)
            
        return {"message": "Google Authenticated", "email": user_email}
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {str(e)}")

async def perform_installation(ssh_details: InstallSchema, user_email: str, send_log):
    await send_log("🚀 Starting installation...")
    
    ssh = SSHManager(
        hostname=ssh_details.ip_address,
        username=ssh_details.ssh_username,
        key_path=ssh_details.ssh_key_path
    )
    
    import asyncio
    
    def log_wrapper(line):
        asyncio.run_coroutine_threadsafe(send_log(line), asyncio.get_event_loop())

    exit_status = ssh.execute_and_stream(ssh_details.command, log_wrapper)
    
    if exit_status == 0:
        await send_log("✅ Installation complete. Configuring DNS...")
        
        dns = DNSManager(os.getenv("ZONE_ID"), os.getenv("API_TOKEN"))
        subdomain = user_email.split('@')[0] 
        dns.create_subdomain(subdomain, ssh_details.ip_address)
        
        rec = db_manager.get_user_by_email(user_email)
        user_id = rec.id

        db_manager.mark_engine_installed(user_id, 'cloud')

        await send_log("🌍 DNS successfully updated.")
        await send_log("INSTALLATION_COMPLETE")
    else:
        await send_log("❌ Installation failed.")

class ConnectionManager:
    def __init__(self):
        self.active_connections = {}

    async def connect(self, email: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[email.strip().lower()] = websocket

    def disconnect(self, email: str):
        user_email = email.strip().lower()
        if user_email in self.active_connections:
            del self.active_connections[user_email]

    async def send_message(self, email: str, message: str):
        user_email = email.strip().lower()
        if user_email in self.active_connections:
            await self.active_connections[user_email].send_text(message)

manager = ConnectionManager()

@app.websocket("/ws/install/{email}")
async def websocket_install(websocket: WebSocket, email: str):
    user_email = email.strip().lower()
    await manager.connect(user_email, websocket)
    try:
        data_json = await websocket.receive_json()
        data = InstallSchema(**data_json)
        
        async def send_log(msg):
            await manager.send_message(user_email, msg)
            
        await perform_installation(data, user_email, send_log)
        
    except WebSocketDisconnect:
        manager.disconnect(user_email)

@app.get("/get-domain/{email}")
def get_domain(email: str, db: ContextDB = Depends(get_db)):
    """
    Called by the VPS bootstrap script to retrieve the assigned subdomain.
    """
    user_email = email.strip().lower()
    instance = db.get_user_subdomain(user_email)
    if not instance:
        raise HTTPException(status_code=404, detail="Subdomain not found for this user")
    
    return {"subdomain": instance.subdomain}

@app.get("/api/check-access/{email}")
def check_access(email: str, db: ContextDB = Depends(get_db)):
    """
    Called by the frontend to determine if the user is 
    installed, subscribed, or operating within a 7-day trial period.
    """
    user_email = email.strip().lower()
    instance = db.get_user_status(user_email)
    
    if not instance:
        return {
            "is_installed": False,
            "is_subscribed": False,
            "is_trial_active": False,
            "days_remaining": 0
        }
        
    trial_duration_days = 7
    now = datetime.now(timezone.utc)
    trial_start = instance.trial_start_date
    
    if trial_start:
        if trial_start.tzinfo is None:
            trial_start = trial_start.replace(tzinfo=timezone.utc)
        days_elapsed = (now - trial_start).days
        days_remaining = trial_duration_days - days_elapsed
    else:
        days_remaining = 0

    is_trial_active = days_remaining > 0 and not instance.subscription_active
    
    return {
        "is_installed": instance.engine_installed,
        "is_subscribed": instance.subscription_active,
        "is_trial_active": is_trial_active,
        "days_remaining": max(0, days_remaining)
    }

@app.post("/api/v1/engine/update-status/{user_id}")
def update_status(
    user_id: str, 
    installation_type: str = "local", 
    status: bool = Query(True, description="Target installation state flag"),
    db: ContextDB = Depends(get_db)
    ):
    """
    Called by the bootstrap script or configuration engine to dynamically toggle 
    the installation state (True/False) using the user's UUID record.
    """
    # 1. Resolve internal metrics using the user ID
    res = db.get_engine_config_by_id(user_id)
    if not res:
        raise HTTPException(status_code=404, detail="User instance not found")
    
    # Extract email from the named tuple/tuple return profile (email, subdomain)
    user_email = res[0]
    
    try:
        # 2. Update the system state using the universal status function
        db.update_engine_installation_status(
            email=user_email, 
            status=status, 
            inst_type=installation_type if status else None
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return {
        "message": "Status updated successfully",
        "email": user_email,
        "engine_installed": status,
        "installation_type": installation_type if status else None
    }

def start_server():
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(socket_app, host="0.0.0.0", port=port)