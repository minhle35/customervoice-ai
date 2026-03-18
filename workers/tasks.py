from __future__ import annotations

from pipelines.orchestration.pipeline_runner import ingest, process_unprocessed
from workers.celery_app import celery_app


@celery_app.task(
    name="ingest_platform",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def ingest_platform(platform: str, business_id: str, params: dict | None = None):
    return ingest(platform=platform, business_id=business_id, params=params or {})


@celery_app.task(
    name="process_unprocessed_reviews",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def process_unprocessed_reviews(limit: int = 100):
    return process_unprocessed(limit=limit)
