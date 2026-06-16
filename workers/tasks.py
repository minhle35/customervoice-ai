from __future__ import annotations

from openai import NotFoundError, RateLimitError

from pipelines.orchestration.pipeline_runner import ingest, process_unprocessed
from workers.celery_app import celery_app

# RateLimitError  — don't retry, let the caller use process_unprocessed_reviews later
# NotFoundError   — model endpoint missing (wrong model name or provider outage);
#                   retrying re-fetches from SerpAPI and burns quota without fixing anything
_RETRYABLE = (Exception,)
_NO_RETRY = (RateLimitError, NotFoundError)


@celery_app.task(
    name="ingest_platform",
    bind=True,
    autoretry_for=_RETRYABLE,
    dont_autoretry_for=_NO_RETRY,
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def ingest_platform(self, platform: str, business_id: str, params: dict | None = None):
    return ingest(platform=platform, business_id=business_id, params=params or {}, task=self)


@celery_app.task(
    name="process_unprocessed_reviews",
    autoretry_for=_RETRYABLE,
    dont_autoretry_for=_NO_RETRY,
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def process_unprocessed_reviews(limit: int = 100):
    return process_unprocessed(limit=limit)
