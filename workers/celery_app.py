"""
This module sets up the Celery app for asynchronous task processing.
It is a background job runner - a separate process from the FastAPI app that handles long-running tasks like review ingestion and processing.
The Celery app is configured to use the broker and backend specified in the settings, and it includes the tasks defined in workers/tasks.py.

celery_app: configures the Celery instance with broker and backend URLs (broker=Redis, backend=Redis)
workers/tasks.py: defines the actual tasks that can be run asynchronously, such as ingest_platform and process_unprocessed_reviews

1. User hits POST /api/integrations/google
2.FastAPI route triggers route_integrations.py
-> ingest_platform.delay() is called, which pushes the job onto Redis queue, and returns immediately with a task ID
-> returns {"status": "queued", "task_id": <id>} to the user
3. Celery worker picks up the job from the Redis queue and executes the ingest_platform function in workers/tasks.py
pipeline_runner.ingest() is called
-> fetch from SerpAPI
-> clean text
-> sentiment + topics (OpenAI)
-> generate embedding (OpenAI)
-> store in database (PostgreSQL)

# Start Redis first (required)
docker compose up redis -d

# Start Celery worker (in project root)
uv run celery -A workers.celery_app.celery_app worker --loglevel=info

How to use:
1. Trigger ingestion via API:
curl -X POST "http://localhost:8000/api/integrations/google" \
        -H "Content-Type: application/json" \
        -d '{"platform": "google",
        "business_id": "some_business_id",
        "params": {
            "data_id": "[some_data_id_from_serpapi_0x12345:0x67890],
            "place_name": "Some Place Name"}}'
"""

from __future__ import annotations

import sys
from pathlib import Path

from celery import Celery
from celery.signals import worker_init

from app.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


celery_app = Celery(
    "customer_voice_ai",
    broker=get_settings().celery.broker_url,
    backend=get_settings().celery.result_backend,
    include=["workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)


@worker_init.connect
def init_worker_database(**kwargs):
    """Initialise DB connection pool when the Celery worker process starts."""
    from app.database.database import init_db
    init_db()
