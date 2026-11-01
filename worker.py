"""
Entry point for the Celery worker and the beat scheduler.

    celery -A worker worker   → consumes tasks
    celery -A worker beat     → publishes the scheduled sync

This file deliberately does NOT create a Celery app. There used to be two: one
here and one in tasks.py, configured from two different environment variables.

That was a latent outage. Celery reads CELERY_BROKER_URL from the environment
itself, and that value overrides the `broker=` argument passed to the
constructor — so this file's `broker=os.getenv("REDIS_URL")` had never had any
effect at all. The system only worked because CELERY_BROKER_URL happened to be
set and both halves therefore landed on the same Redis by accident. Unset it and
the API would publish to one broker while the worker listened on another: every
task silently discarded, no error anywhere, the sync endpoint still returning
202.

One app, imported from one place, configured from one variable.
"""

import logging
import os

from tasks import celery_app


# ── logging ───────────────────────────────────────────────────────────────
# The Azure SDK logs every HTTP request and response, header by header, at
# INFO. A single sync produces hundreds of lines and buries the handful that
# say what actually happened. WARNING keeps real failures and drops the noise.
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(
    logging.WARNING
)


# ── configuration ─────────────────────────────────────────────────────────
SYNC_INTERVAL_MINUTES = int(os.getenv("SYNC_INTERVAL_MINUTES", "60"))
CONCURRENCY = int(os.getenv("CELERY_CONCURRENCY", "4"))

celery_app.conf.update(
    # What the beat container runs. It was empty, so the beat service had been
    # running since June scheduling nothing — every sync this project has ever
    # done was a manual API call.
    beat_schedule={
        "sync-every-linked-subscription": {
            "task": "tasks.sync_all_accounts",
            "schedule": SYNC_INTERVAL_MINUTES * 60.0,
        },
    },
    timezone="UTC",

    # 'solo' runs one task at a time in the main process: with ten linked
    # subscriptions, the tenth waits for the first nine. The work is almost
    # entirely waiting on Azure and Gemini, so concurrency costs little and
    # helps a lot.
    worker_concurrency=CONCURRENCY,

    # Upstash closes idle connections, which surfaced as
    # 'redis.exceptions.ConnectionError: Connection closed by server'. Celery
    # reconnected on its own, so it was noise rather than a fault — but a
    # keepalive and a periodic health check stop it happening.
    broker_transport_options={
        "socket_keepalive": True,
        "health_check_interval": 25,
    },
    broker_connection_retry_on_startup=True,

    # Results are only used to tell whether a task finished; keeping them for a
    # week fills Redis for no benefit.
    result_expires=3600,
)