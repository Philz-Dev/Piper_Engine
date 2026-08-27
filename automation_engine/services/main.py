from apscheduler.schedulers.background import BackgroundScheduler
from scheduler import check_schedules
from universal_webhook.core import start_webhook_service
from shared.database_manager import ContextDB
import time
import traceback
import sys

if __name__ == "__main__":

    # Force logs to show up immediately in Docker
    print("--- SETTING UP SERVER AND SCHEDULER ---", flush=True) 

    db = ContextDB()

    # --- NEW: WAIT FOR DATABASE LOOP ---
    db_ready = False
    retries = 0
    max_retries = 10

    print("⏳ Waiting for database to be fully ready...", flush=True)
    while not db_ready and retries < max_retries:
        if db.check_connection():
            print("✅ Database is UP and accepting queries.", flush=True)
            db_ready = True
        else:
            retries += 1
            print(f"⚠️ Database still starting up... (Attempt {retries}/{max_retries})", flush=True)
            time.sleep(5) # Wait 5 seconds before trying again

    if not db_ready:
        print("💥 CRITICAL ERROR: Database never became ready. Exiting.", flush=True)
        sys.exit(1)
        
    try:
        scheduler = BackgroundScheduler()
        scheduler.add_job(check_schedules, 'interval', seconds=5, coalesce=True)
        scheduler.start()
        
        # This is likely where it dies
        start_webhook_service() 
        
    except Exception as e:
        print("\n💥 CRITICAL CRASH DETECTED 💥", flush=True)
        print(f"Error Type: {type(e).__name__}", flush=True)
        print(f"Error Message: {e}", flush=True)
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush() # Force Docker to show this
