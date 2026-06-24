import os
from celery import Celery
import logging
from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient

# Import your database and models
from database import SessionLocal
import models

# Setup logging to watch the terminal output
logger = logging.getLogger(__name__)

# Initialize the Celery App (Connecting to Redis Broker)
# This assumes your Redis container is accessible at redis://redis:6379/0
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
celery_app = Celery("tasks", broker=CELERY_BROKER_URL)


@celery_app.task(name="tasks.analyze_server_efficiency")
def analyze_server_efficiency(vm_id, cpu_usage, resource_id, resource_type, cost_per_hour):
    """
    WORKER 2: The AI Analyst.
    This task is triggered by Redis. It takes the raw server data, 
    sends it to Google Gemini, and saves the optimization alert.
    """
    logger.info(f"AI Worker woken up! Analyzing server: {resource_id}")
    db = SessionLocal()
    
    try:
        # [Your existing Gemini AI Logic goes here]
        # Example prompt: "I have an Azure VM running at {cpu_usage}% CPU costing {cost_per_hour}/hr. How can I optimize this?"
        
        # Mocked AI Response generation for context:
        ai_recommendation = f"Downsize {resource_type} to B1s tier. You are only using {cpu_usage}% CPU."
        estimated_savings = 12.00 
        
        # Save the alert to the database
        new_alert = models.Alert(
            resource_id=vm_id,
            recommendation=ai_recommendation,
            estimated_monthly_savings=estimated_savings,
            is_resolved=False
        )
        db.add(new_alert)
        db.commit()
        
        logger.info(f"Successfully generated AI alert for VM ID: {vm_id}")
        
    except Exception as e:
        logger.error(f"Error during AI analysis: {e}")
        db.rollback()
    finally:
        db.close()


@celery_app.task(bind=True, name="tasks.fetch_azure_vms_for_user")
def fetch_azure_vms_for_user(self, user_id: int):
    """
    WORKER 1: The Azure Fetcher.
    Logs into Microsoft Azure, downloads the VMs, saves them to PostgreSQL,
    and then immediately triggers the Gemini AI worker.
    """
    logger.info(f"Task received! Fetching Azure VMs for user {user_id}...")
    db = SessionLocal()

    try:
        # 1. Grab the fresh Azure keys from the database
        account = db.query(models.CloudAccount).filter(models.CloudAccount.user_id == user_id).first()
        if not account:
            logger.error("No Azure account linked for this user.")
            return
            
        logger.info("Real subscription detected. Connecting to Microsoft Azure...")

        # 2. Authenticate with Azure using the secret value (not ID!)
        credential = ClientSecretCredential(
            tenant_id=account.tenant_id,
            client_id=account.client_id,
            client_secret=account.client_secret
        )
        
        compute_client = ComputeManagementClient(
            credential=credential, 
            subscription_id=account.subscription_id
        )

        # 3. Fetch the servers from Azure
        vms = compute_client.virtual_machines.list_all()
        synced_count = 0

        for vm in vms:
            # Check if we already saved this VM
            existing_vm = db.query(models.Resource).filter(
                models.Resource.resource_id == vm.id
            ).first()

            if not existing_vm:
                # Mocking CPU and Cost for the example (usually pulled from Azure Monitor)
                avg_cpu = 45 
                cost_hr = 0.02 
                
                # Save the new VM to PostgreSQL
                new_vm = models.Resource(
                    owner_id=user_id,
                    resource_id=vm.id,
                    resource_type="Azure Virtual Machine",
                    allocated_cpu_cores=1,  # You can dynamically parse vm.hardware_profile.vm_size
                    average_cpu_usage_percent=avg_cpu,
                    cost_per_hour=cost_hr
                )
                
                db.add(new_vm)
                db.commit()
                db.refresh(new_vm)
                synced_count += 1

                # 👇 THE EVENT TRIGGER: Hand the baton to the AI Analyst 👇
                try:
                    analyze_server_efficiency.delay(
                        new_vm.id,
                        new_vm.average_cpu_usage_percent,
                        new_vm.resource_id,
                        new_vm.resource_type,
                        new_vm.cost_per_hour
                    )
                    logger.info(f"Published AI analysis event for server: {new_vm.resource_id}")
                except Exception as trigger_error:
                    logger.warning(f"Failed to publish event to Redis: {trigger_error}")
                # 👆 END OF EVENT TRIGGER 👆
                
        logger.info(f"Successfully synced {synced_count} REAL Azure VMs!")
        
    except Exception as e:
        logger.error(f"Failed to fetch from Azure: {e}")
        db.rollback()
    finally:
        db.close()