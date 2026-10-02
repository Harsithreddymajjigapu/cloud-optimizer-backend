import os
import datetime
import logging

from celery import Celery
from azure.core.exceptions import HttpResponseError

from azure_client import build_clients
from database import SessionLocal
import models

logger = logging.getLogger(__name__)

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
celery_app = Celery("tasks", broker=CELERY_BROKER_URL)

METRIC_LOOKBACK_DAYS = int(os.getenv("METRIC_LOOKBACK_DAYS", "7"))
METRIC_INTERVAL = os.getenv("METRIC_INTERVAL", "PT1H")


def average_cpu_percent(monitor_client, resource_uri, lookback_days=METRIC_LOOKBACK_DAYS):
    """
    Average 'Percentage CPU' for one VM over the lookback window, from Azure Monitor.

    Returns None when Azure reports no datapoints — a deallocated VM, one created
    inside the window, or one with platform metrics unavailable. None means
    "unknown", which is different from 0.0 ("idle"), so callers must not treat a
    missing metric as an idle machine.
    """
    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(days=lookback_days)

    response = monitor_client.metrics.list(
        resource_uri=resource_uri,
        timespan=f"{start.isoformat()}/{end.isoformat()}",
        interval=METRIC_INTERVAL,
        metricnames="Percentage CPU",
        aggregation="Average",
    )

    samples = [
        point.average
        for metric in response.value
        for series in metric.timeseries
        for point in series.data
        if point.average is not None
    ]

    if not samples:
        return None

    return round(sum(samples) / len(samples), 2)


def build_vcpu_lookup(compute_client, locations):
    """
    Map VM size name -> vCPU count, e.g. {"Standard_B2s": 2}.

    Built once per sync rather than per VM: resource_skus.list is a large,
    slow call and the answer is identical for every VM of the same size.
    A failure here is not fatal — cores stay unknown and the sync continues.
    """
    lookup = {}

    for location in locations:
        if not location:
            continue
        try:
            skus = compute_client.resource_skus.list(filter=f"location eq '{location}'")
            for sku in skus:
                if sku.resource_type != "virtualMachines" or sku.name in lookup:
                    continue
                for capability in sku.capabilities or []:
                    if capability.name == "vCPUs":
                        lookup[sku.name] = int(capability.value)
                        break
        except HttpResponseError as exc:
            logger.warning("Could not load VM SKUs for %s: %s", location, exc)

    return lookup


def queue_analysis(resource):
    """Publish an analysis job. A broker outage must not fail the sync."""
    try:
        analyze_server_efficiency.delay(
            resource.id,
            resource.average_cpu_usage_percent,
            resource.resource_id,
            resource.resource_type,
            resource.cost_per_hour,
        )
        logger.info("Queued analysis for %s", resource.resource_id)
    except Exception as exc:
        logger.warning("Could not queue analysis for %s: %s", resource.resource_id, exc)


@celery_app.task(name="tasks.analyze_server_efficiency")
def analyze_server_efficiency(vm_id, cpu_usage, resource_id, resource_type, cost_per_hour):
    """
    Turn a VM's measured CPU usage into an optimization alert.

    NOTE: the recommendation text is still rule-based. Replacing it with a
    Gemini call, and populating cli_command_to_fix, is the next change.
    """
    logger.info("Analyzing %s (avg CPU %s%%)", resource_id, cpu_usage)
    db = SessionLocal()

    try:
        if cpu_usage is None:
            logger.info("No CPU data for %s; nothing to recommend.", resource_id)
            return

        recommendation = (
            f"{resource_type} averaged {cpu_usage}% CPU over the last "
            f"{METRIC_LOOKBACK_DAYS} days. Consider downsizing to a smaller SKU."
        )

        alert = models.OptimizationAlert(
            resource_id=vm_id,
            ai_recommendation=recommendation,
            estimated_monthly_savings=None,
            cli_command_to_fix=None,
        )
        db.add(alert)
        db.commit()

        logger.info("Saved alert for resource id %s", vm_id)

    except Exception as exc:
        logger.error("Error during analysis of %s: %s", resource_id, exc)
        db.rollback()
    finally:
        db.close()


@celery_app.task(
    bind=True,
    name="tasks.fetch_azure_vms_for_user",
    autoretry_for=(HttpResponseError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def fetch_azure_vms_for_user(self, user_id: int):
    """
    Sync every subscription this user has linked.

    A user may link production and staging separately, so this iterates all
    linked accounts. The previous version took only .first(), which meant extra
    subscriptions were silently never scanned.
    """
    logger.info("Starting Azure sync for user %s", user_id)
    db = SessionLocal()

    try:
        accounts = (
            db.query(models.CloudAccount)
            .filter(models.CloudAccount.user_id == user_id)
            .all()
        )
        if not accounts:
            logger.error("No Azure account linked for user %s.", user_id)
            return

        total_created = total_refreshed = 0

        for account in accounts:
            try:
                created, refreshed = sync_one_subscription(db, user_id, account)
                total_created += created
                total_refreshed += refreshed
            except HttpResponseError:
                raise
            except Exception as exc:
                logger.error(
                    "Sync failed for subscription %s: %s",
                    account.subscription_id, exc,
                )
                db.rollback()

        logger.info(
            "Azure sync complete for user %s across %s subscription(s): "
            "%s new, %s refreshed",
            user_id, len(accounts), total_created, total_refreshed,
        )

    except HttpResponseError:
        db.rollback()
        raise          # let Celery retry with backoff
    except Exception as exc:
        logger.error("Azure sync failed for user %s: %s", user_id, exc)
        db.rollback()
    finally:
        db.close()


def sync_one_subscription(db, user_id, account):
    """
    Sync a single linked subscription. Returns (created, refreshed).

    Safe to re-run: existing resources have their metrics refreshed in place
    rather than being skipped, which is what makes a scheduled run useful.
    """
    compute_client, monitor_client = build_clients(account)

    vms = list(compute_client.virtual_machines.list_all())
    vcpu_lookup = build_vcpu_lookup(compute_client, {vm.location for vm in vms})

    created = refreshed = 0

    for vm in vms:
        vm_size = vm.hardware_profile.vm_size if vm.hardware_profile else None
        cores = vcpu_lookup.get(vm_size)

        try:
            avg_cpu = average_cpu_percent(monitor_client, vm.id)
        except HttpResponseError as exc:
            logger.warning("Metrics unavailable for %s: %s", vm.id, exc)
            avg_cpu = None

        resource = (
            db.query(models.CloudResource)
            .filter(models.CloudResource.resource_id == vm.id)
            .first()
        )

        if resource is None:
            resource = models.CloudResource(
                owner_id=user_id,
                resource_id=vm.id,
                resource_type=vm_size or "Azure Virtual Machine",
                allocated_cpu_cores=cores,
                average_cpu_usage_percent=avg_cpu,
                cost_per_hour=None,
            )
            db.add(resource)
            created += 1
        else:
            resource.resource_type = vm_size or resource.resource_type
            if cores is not None:
                resource.allocated_cpu_cores = cores
            if avg_cpu is not None:
                resource.average_cpu_usage_percent = avg_cpu
            refreshed += 1

        db.commit()
        db.refresh(resource)

        if avg_cpu is not None:
            queue_analysis(resource)

    logger.info(
        "Subscription %s: %s new, %s refreshed",
        account.subscription_id, created, refreshed,
    )
    return created, refreshed