import os
from worker import celery_app
from google import genai
from pydantic import BaseModel, Field
from database import SessionLocal  
import models
import logging

logger = logging.getLogger(__name__)

# Initialize Gemini
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

class AIServerAnalysis(BaseModel):
    recommendation: str = Field(description="A concise 1-sentence assessment of the server's health.")
    potential_savings: float = Field(description="Estimated monthly cost savings if downsized, otherwise 0.0.")
    action_required: str = Field(description="The exact cloud CLI command (AWS/Azure) to optimize or scale this instance.")

@celery_app.task(name="tasks.fetch_azure_vms_for_user")
def fetch_azure_vms_for_user(user_id: int):
    """Syncs Virtual Machines from Azure (with mock bypass for testing)."""
    db = SessionLocal()
    try:
        account = db.query(models.CloudAccount).filter(models.CloudAccount.user_id == user_id).first()
        if not account:
            return

        logger.info(f"Logging into Azure for {account.company_name}...")

        # MOCK BYPASS FOR TESTING
        if account.subscription_id == "mock-sub-000":
            logger.info("Mock credentials detected. Injecting test servers...")
            mock_servers = [
                {"id": "vm-prod-01-xyz", "name": "Production API Server", "cpu": 12.5},
                {"id": "vm-db-02-abc", "name": "PostgreSQL Database", "cpu": 85.0}
            ]
            
            for vm in mock_servers:
                existing = db.query(models.CloudResource).filter(models.CloudResource.resource_id == vm["id"]).first()
                if not existing:
                    new_resource = models.CloudResource(
                        resource_id=vm["id"],
                        resource_type="Azure Virtual Machine",
                        allocated_cpu_cores=4,
                        average_cpu_usage_percent=vm["cpu"],
                        cost_per_hour=0.15,
                        owner_id=user_id
                    )
                    db.add(new_resource)
            db.commit()
            logger.info("Successfully synced mock VMs!")
            return

    except Exception as e:
        logger.error(f"Failed to fetch from Azure: {e}")
        db.rollback()
    finally:
        db.close()


@celery_app.task(name="tasks.analyze_server_efficiency")
def analyze_server_efficiency(server_id: int, cpu_usage: float, resource_id: str, resource_type: str, cost: float):
    """Feeds server telemetry to Gemini AI for FinOps optimization."""
    logger.info(f"[Celery Worker] Received AI task for Server ID {server_id}")
    
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
        logger.info(f"[Gemini AI] Successfully generated structured output!")

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
            logger.info(f"[PostgreSQL] Alert safely written to database for Server ID {server_id}.")
        except Exception as db_err:
            db.rollback()
            logger.error(f"[PostgreSQL Error] Database write failed: {db_err}")
        finally:
            db.close()

    except Exception as ai_err:
        logger.error(f"[Gemini API Error] Failed to fetch or parse response: {ai_err}")