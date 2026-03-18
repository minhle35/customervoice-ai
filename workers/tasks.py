from __future__ import annotations

from openai import RateLimitError

from pipelines.orchestration.pipeline_runner import ingest, process_unprocessed
from workers.celery_app import celery_app

# Never auto-retry on rate limits — the task would just hammer the API again.
# RateLimitError should be handled with a longer backoff at the OpenAI client level.
_RETRYABLE = (Exception,)
_NO_RETRY = (RateLimitError,)


@celery_app.task(
    name="ingest_platform",
    autoretry_for=_RETRYABLE,
    dont_autoretry_for=_NO_RETRY,
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def ingest_platform(platform: str, business_id: str, params: dict | None = None):
    return ingest(platform=platform, business_id=business_id, params=params or {})


@celery_app.task(
    name="process_unprocessed_reviews",
    autoretry_for=_RETRYABLE,
    dont_autoretry_for=_NO_RETRY,
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def process_unprocessed_reviews(limit: int = 100):
    return process_unprocessed(limit=limit)
