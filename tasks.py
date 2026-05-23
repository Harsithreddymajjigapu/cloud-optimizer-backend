from Worker import celery_app, analyze_server_efficiency
from database import SessionLocal
import models
import logging

logger = logging.getLogger(__name__)


@celery_app.task
def scan_all_servers():
    """
    Every hour, go through every registered server
    and queue a fresh AI analysis for each one.
    """
    db = SessionLocal()
    try:
        servers = db.query(models.CloudResource).all()

        if not servers:
            logger.info("[Scheduled] No servers found to scan.")
            return

        logger.info(f"[Scheduled] Scanning {len(servers)} servers...")

        for server in servers:
            analyze_server_efficiency.delay(
                server.id,
                server.average_cpu_usage_percent,
                server.resource_id,
                server.resource_type,
                server.cost_per_hour
            )
            logger.info(f"[Scheduled] Queued analysis for server: {server.resource_id}")

        logger.info(f"[Scheduled] All {len(servers)} servers queued successfully.")

    except Exception as e:
        logger.error(f"[Scheduled] Error during scan_all_servers: {e}")

    finally:
        db.close()

celery_app.conf.beat_schedule = {
    "scan-all-servers-every-hour": {
        "task": "tasks.scan_all_servers",
        "schedule": 3600.0,                
    },
}

celery_app.conf.timezone = "UTC"