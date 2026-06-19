from worker import celery_app
from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from sqlalchemy.orm import Session
import models
from database import SessionLocal 
import logging                     

logger = logging.getLogger(__name__)
@celery_app.task
def fetch_azure_vms_for_user(user_id: int):
    db = SessionLocal()
    try:
        account = db.query(models.CloudAccount).filter(models.CloudAccount.user_id == user_id).first()
        if not account:
            logger.error(f"No Azure account linked for user {user_id}")
            return

        logger.info(f"Logging into Azure for {account.company_name}...")

        if account.subscription_id == "mock-sub-000":
            logger.info("Mock credentials detected. Injecting test servers...")
            mock_servers = [
                {"id": "vm-prod-01-xyz", "name": "Production API Server"},
                {"id": "vm-db-02-abc", "name": "PostgreSQL Database"}
            ]
            
            for vm in mock_servers:
                existing = db.query(models.CloudResource).filter(models.CloudResource.resource_id == vm["id"]).first()
                if not existing:
                    new_resource = models.CloudResource(
                        resource_id=vm["id"],
                        resource_type="Azure Virtual Machine",
                        allocated_cpu_cores=4,
                        average_cpu_usage_percent=85.0,
                        cost_per_hour=0.15,
                        owner_id=user_id
                    )
                    db.add(new_resource)
                    logger.info(f"Saved mock Azure VM: {vm['name']}")
                    
            db.commit()
            logger.info("Successfully synced mock VMs!")
            return

        credential = ClientSecretCredential(
            tenant_id=account.tenant_id,
            client_id=account.client_id,
            client_secret=account.client_secret
        )
        compute_client = ComputeManagementClient(credential, account.subscription_id)

    except Exception as e:
        logger.error(f"Failed to fetch from Azure: {e}")
        db.rollback()
    finally:
        db.close()