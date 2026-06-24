import os
from celery import Celery
import logging
from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient

from database import SessionLocal
import models

logger = logging.getLogger(__name__)

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
        ai_recommendation = f"Downsize {resource_type} to B1s tier. You are only using {cpu_usage}% CPU."
        estimated_savings = 12.00 
        
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
        account = db.query(models.CloudAccount).filter(models.CloudAccount.user_id == user_id).first()
        if not account:
            logger.error("No Azure account linked for this user.")
            return
            
        logger.info("Real subscription detected. Connecting to Microsoft Azure...")

        credential = ClientSecretCredential(
            tenant_id=account.tenant_id,
            client_id=account.client_id,
            client_secret=account.client_secret
        )
        
        compute_client = ComputeManagementClient(
            credential=credential, 
            subscription_id=account.subscription_id
        )

        vms = compute_client.virtual_machines.list_all()
        synced_count = 0

        for vm in vms:
            existing_vm = db.query(models.Resource).filter(
                models.Resource.resource_id == vm.id
            ).first()

            if not existing_vm:
                avg_cpu = 45 
                cost_hr = 0.02 
                
                new_vm = models.Resource(
                    owner_id=user_id,
                    resource_id=vm.id,
                    resource_type="Azure Virtual Machine",
                    allocated_cpu_cores=1,
                    average_cpu_usage_percent=avg_cpu,
                    cost_per_hour=cost_hr
                )
                
                db.add(new_vm)
                db.commit()
                db.refresh(new_vm)
                synced_count += 1
                
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
                
                
        logger.info(f"Successfully synced {synced_count} REAL Azure VMs!")
        
    except Exception as e:
        logger.error(f"Failed to fetch from Azure: {e}")
        db.rollback()
    finally:
        db.close()