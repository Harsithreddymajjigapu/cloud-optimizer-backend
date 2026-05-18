import os
from celery import Celery
from google import genai
from pydantic import BaseModel, Field
from database import SessionLocal  # Import your database session coordinator
import models  # Import your SQLAlchemy models file

# 1. Initialize Celery App (Reads from your Upstash cloud conveyor belt)
celery_app = Celery(
    "worker",
    broker=os.getenv("REDIS_URL"),
    backend=os.getenv("REDIS_URL")
)
# Fix for Windows Celery instances
celery_app.conf.update(worker_pool='solo')

# 2. Initialize the Free Gemini Client (Reads your new key from .env)
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# 3. Define the AI Brain Template (Strict Pydantic Enforcement)
class AIServerAnalysis(BaseModel):
    recommendation: str = Field(description="A concise 1-sentence assessment of the server's health.")
    potential_savings: float = Field(description="Estimated monthly cost savings if downsized, otherwise 0.0.")
    action_required: str = Field(description="The exact cloud CLI command (AWS/Azure) to optimize or scale this instance.")

# 4. The Upgraded Asynchronous Core Task
@celery_app.task(name="worker.analyze_server_efficiency")
def analyze_server_efficiency(server_id: int, cpu_usage: float, resource_id: str, resource_type: str, cost: float):
    print(f"📦 [Celery Worker] Received task for Server ID {server_id} ({resource_id})")
    
    # Construct a highly detailed prompt using the server's actual context
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
        # Call the live Gemini AI engine
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config={
                'response_mime_type': 'application/json',
                'response_schema': AIServerAnalysis,  # Clamps Gemini into your exact data shape
            },
        )
        
        
        ai_result: AIServerAnalysis = response.parsed
        print(f"🤖 [Gemini AI] Successfully generated structured output for {resource_id}!")

        # 5. Open a temporary door to your PostgreSQL database warehouse
        db = SessionLocal()
        try:
            # Match fields to your SQLAlchemy models.OptimizationAlert table columns
            new_alert = models.OptimizationAlert(
                server_id=server_id,
                recommendation=ai_result.recommendation,
                potential_savings=ai_result.potential_savings,
                action_required=ai_result.action_required
            )
            db.add(new_alert)
            db.commit()
            print(f"💾 [PostgreSQL] Alert safely written to database for Server ID {server_id}.")
        except Exception as db_err:
            db.rollback()
            print(f"❌ [PostgreSQL Error] Database write failed: {db_err}")
        finally:
            db.close()  # Lock the database door back up to save server resources

    except Exception as ai_err:
        print(f"❌ [Gemini API Error] Failed to fetch or parse response: {ai_err}")