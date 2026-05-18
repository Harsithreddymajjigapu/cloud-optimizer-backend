import os
from celery import Celery
from google import genai
from pydantic import BaseModel, Field
from database import SessionLocal  
import models

celery_app = Celery(
    "worker",
    broker=os.getenv("REDIS_URL"),
    backend=os.getenv("REDIS_URL")
)
celery_app.conf.update(worker_pool='solo')

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

class AIServerAnalysis(BaseModel):
    recommendation: str = Field(description="A concise 1-sentence assessment of the server's health.")
    potential_savings: float = Field(description="Estimated monthly cost savings if downsized, otherwise 0.0.")
    action_required: str = Field(description="The exact cloud CLI command (AWS/Azure) to optimize or scale this instance.")

@celery_app.task(name="worker.analyze_server_efficiency")
def analyze_server_efficiency(server_id: int, cpu_usage: float, resource_id: str, resource_type: str, cost: float):
    print(f"📦 [Celery Worker] Received task for Server ID {server_id} ({resource_id})")
    
    prompt = (
        f"You are an elite Enterprise Cloud FinOps Architect.\n"
        f"Analyze this infrastructure resource:\n"
        f"- ID: {resource_id}\n"
        f"- Type: {resource_type}\n"
        f"- Current Average CPU Usage: {cpu_usage}%\n"
        f"- Current Hourly Cost: ${cost}/hr\n\n"
        f"Provide a clear recommendation, estimate potential savings, and generate the exact shell CLI command needed to action this fix."
    )
    
    try:
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config={
                'response_mime_type': 'application/json',
                'response_schema': AIServerAnalysis,
            },
        )
        
        
        ai_result: AIServerAnalysis = response.parsed
        print(f"🤖 [Gemini AI] Successfully generated structured output for {resource_id}!")

        db = SessionLocal()
        try:
            
            new_alert = models.OptimizationAlert(
                server_id=server_id,
                recommendation=ai_result.recommendation,
                potential_savings=ai_result.potential_savings,
                action_required=ai_result.action_required
            )
            db.add(new_alert)
            db.commit()
            print(f" [PostgreSQL] Alert safely written to database for Server ID {server_id}.")
        except Exception as db_err:
            db.rollback()
            print(f"❌ [PostgreSQL Error] Database write failed: {db_err}")
        finally:
            db.close()

    except Exception as ai_err:
        print(f"❌ [Gemini API Error] Failed to fetch or parse response: {ai_err}")