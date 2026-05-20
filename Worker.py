import os
from celery import Celery
from google import genai
from pydantic import BaseModel, Field
from database import SessionLocal  
import models

# --- NEW IMPORTS FOR AZURE ---
from azure.identity import DefaultAzureCredential
from azure.mgmt.monitor import MonitorManagementClient
from datetime import timedelta, datetime, timezone

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

def fetch_real_cpu_from_azure(resource_uri):
    """Securely fetches real-time CPU data from Azure Monitor."""
    try:
        print(f"🔍 [Azure] Logging into Microsoft Entra...")
        credential = DefaultAzureCredential() 
        subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")
        
        monitor_client = MonitorManagementClient(credential, subscription_id)
        
        print(f"📊 [Azure] Fetching telemetry for the target VM...")
        # Use UTC time to ask Azure for the last hour of metrics
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=1)
        
        metrics_data = monitor_client.metrics.list(
            resource_uri,
            timespan=f"{start_time}/{end_time}",
            interval='PT1M', 
            metricnames='Percentage CPU',
            aggregation='Average'
        )

        for metric in metrics_data.value:
            for timeseries in metric.timeseries:
                averages = [data.average for data in timeseries.data if data.average is not None]
                if averages:
                    real_cpu = sum(averages) / len(averages)
                    print(f"✅ [Azure] Real CPU Usage found: {round(real_cpu, 2)}%")
                    return round(real_cpu, 2)
                    
        print("⚠️ [Azure] No CPU data found yet. Defaulting to 0.0%")
        return 0.0 

    except Exception as e:
        print(f"❌ [Azure Error] Failed to fetch metrics: {e}")
        return None

@celery_app.task(name="worker.analyze_server_efficiency")
def analyze_server_efficiency(server_id: int, cpu_usage: float, resource_id: str, resource_type: str, cost: float):
    print(f"📦 [Celery Worker] Received task for Server ID {server_id}")
    
    # --- THE AUTOMATION UPGRADE ---
    # If the user passed a real Azure ID, ignore the manual Swagger CPU and fetch the real one!
    real_cpu = cpu_usage 
    if "/subscriptions/" in resource_id:
        fetched_cpu = fetch_real_cpu_from_azure(resource_id)
        if fetched_cpu is not None:
            real_cpu = fetched_cpu
            print(f"🔄 [Engine] Overriding manual CPU ({cpu_usage}%) with real Azure data ({real_cpu}%)")
    
    prompt = (
        f"You are an elite Enterprise Cloud FinOps Architect.\n"
        f"Analyze this infrastructure resource:\n"
        f"- ID: {resource_id}\n"
        f"- Type: {resource_type}\n"
        f"- Current Average CPU Usage: {real_cpu}%\n"
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
        print(f"🤖 [Gemini AI] Successfully generated structured output!")

        db = SessionLocal()
        try:
            new_alert = models.OptimizationAlert(
                resource_id=server_id,  
                ai_recommendation=ai_result.recommendation,
                estimated_monthly_savings=ai_result.potential_savings,
                cli_command_to_fix=ai_result.action_required
            )
            db.add(new_alert)
            db.commit()
            print(f" [PostgreSQL] Alert safely written to database for Server ID {server_id}.")
        except Exception as db_err:
            db.rollback()
            print(f" [PostgreSQL Error] Database write failed: {db_err}")
        finally:
            db.close()

    except Exception as ai_err:
        print(f"[Gemini API Error] Failed to fetch or parse response: {ai_err}")