import os
import time
from celery import Celery
from dotenv import load_dotenv

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
    return advice