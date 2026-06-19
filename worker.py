import os
from celery import Celery

celery_app = Celery(
    "worker",
    broker=os.getenv("REDIS_URL"),
    backend=os.getenv("REDIS_URL"),
    include=["tasks"]  # Forces Celery to load your tasks file
)

celery_app.conf.update(worker_pool='solo')