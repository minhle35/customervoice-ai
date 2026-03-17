from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter

from app.models.review import Platform
from app.schemas.review_schema import IngestRequest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workers.tasks import ingest_platform  # noqa: E402

router = APIRouter()


@router.post("/{google}")
def trigger_ingestion(platform: Platform, payload: IngestRequest):
    if payload.platform != platform:
        raise ValueError("platform in path must match payload.platform")
    task = ingest_platform.delay(platform.value, payload.business_id, payload.params)
    return {"status": "queued", "task_id": task.id}
