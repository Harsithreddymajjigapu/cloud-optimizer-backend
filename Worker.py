import os
import time
from celery import Celery
from dotenv import load_dotenv

from database import SessionLocal
import models

load_dotenv()

celery_app = Celery(
    "worker",
    broker=os.getenv("REDIS_URL"),
    backend=os.getenv("REDIS_URL")
)

@celery_app.task
def analyze_server_efficiency(server_id: int, cpu_usage: float):
    print(f"--- AI Worker: Processing Server {server_id} ---")
    time.sleep(10) 
    
    advice = f"Server {server_id} is using {cpu_usage}% CPU. Recommendation: Reduce instance size to save 30%."
    
    print(f"--- AI Worker: Finished! Advice: {advice} ---")
    
    # 2. NEW: Open the database and save the advice
    db = SessionLocal()
    try:
        # Find the exact server in the database
        server = db.query(models.CloudResource).filter(models.CloudResource.id == server_id).first()
        if server:
            server.ai_advice = advice  # Put the advice in the mailbox
            db.commit()                # Hit Save!
            print("--- AI Worker: Saved to Database! ---")
    finally:
        db.close() # Always close the connection

    return advice