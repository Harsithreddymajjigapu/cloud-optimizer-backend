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
    print(f"\n--- AI Worker: Waking up! Processing Server {server_id} ---")
    
    time.sleep(10) 
    
    if cpu_usage < 20:
        advice = f"Server is severely underutilized at {cpu_usage}%. Downgrade to save costs."
        savings = 30.00
        cli_command = "aws ec2 modify-instance-attribute --instance-type t3.micro"
    elif cpu_usage > 80:
        advice = f"Server is overloaded at {cpu_usage}%. Upgrade immediately to prevent crashes."
        savings = 0.00 
        cli_command = "aws ec2 modify-instance-attribute --instance-type t3.large"
    else:
        advice = f"Server is running efficiently at {cpu_usage}%."
        savings = 0.00
        cli_command = "None needed. Server is healthy."
        
    print(f"--- AI Worker: Finished thinking. Generating report... ---")
    
    db = SessionLocal()
    try:
        server = db.query(models.CloudResource).filter(models.CloudResource.id == server_id).first()
        
        if server:
            
            new_alert = models.OptimizationAlert(
                resource_id=server.id,
                ai_recommendation=advice,
                estimated_monthly_savings=savings,
                cli_command_to_fix=cli_command
            )
            
            db.add(new_alert)  
            db.commit()        
            
            print(f"--- AI Worker: SUCCESS! Saved new alert for Server {server_id} to the database. ---\n")
        else:
            print(f"--- AI Worker: ERROR! Could not find Server {server_id} in the database. ---\n")
            
    finally:
        db.close() 
    return advice