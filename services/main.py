from apscheduler.schedulers.background import BackgroundScheduler
from scheduler import check_schedules
from universal_webhook.core import start_webhook_service

if __name__ == "__main__":
    print("--- SETTING UP SERVER AND SCHEDULER ---")
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_schedules, 'interval', minutes=1)
    scheduler.start()
    start_webhook_service()
    
