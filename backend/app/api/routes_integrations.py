from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.review_schema import IngestRequest
from app.services.serpapi_service import PlaceResult, SerpApiService

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workers.celery_app import celery_app  # noqa: E402
from workers.tasks import ingest_platform, process_unprocessed_reviews  # noqa: E402

# Mounted at: /api/integrations
router = APIRouter(prefix="/api/integrations", tags=["integrations"])


@router.get(
    "/google/search",
    response_model=list[PlaceResult],
    summary="GET /api/integrations/google/search",
)
def search_google_places(
    q: str = Query(..., description="Business name to search"),
    country: str = Query("us", description="Two-letter country code, e.g. vn, au, us"),
):
    """Search Google Maps for a business and return candidates with their data_id.

    Use the returned data_id as params.data_id when triggering ingestion.
    """
    try:
        return SerpApiService().search_places(query=q, country=country)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc


@router.get("/tasks/{task_id}", summary="GET /api/integrations/tasks/{task_id}")
def get_task_status(task_id: str):
    result = celery_app.AsyncResult(task_id)
    response: dict = {"task_id": task_id, "status": result.state}
    if result.state == "PROGRESS":
        response["progress"] = (
            result.info
        )  # {stage, total, processed, skipped, rate_limited}
    elif result.state == "SUCCESS":
        response["result"] = result.result
    elif result.state == "FAILURE":
        response["error"] = str(result.info)
    return response


@router.post("/reprocess", summary="POST /api/integrations/reprocess")
def reprocess_unprocessed(limit: int = 100):
    """Retry sentiment analysis + embedding for reviews stranded by rate limits."""
    task = process_unprocessed_reviews.delay(limit=limit)
    return {"status": "queued", "task_id": task.id}


def _derive_business_id(place_id: str | None, data_id: str | None) -> str:
    """Derive a stable business_id from Google Maps identifiers.

    place_id (ChIJ...) is Google's canonical stable ID and is preferred.
    data_id (0x3177...) is always returned by SerpAPI and is used as fallback —
    both encode the same underlying Google Maps CID.

    Raises ValueError if neither is available.
    """
    bid = place_id or data_id
    if not bid:
        raise ValueError("Cannot derive business_id: params must include place_id or data_id.")
    return bid


@router.post("/{platform}", summary="POST /api/integrations/{platform}")
def trigger_ingestion(platform: str, payload: IngestRequest):
    try:
        business_id = _derive_business_id(
            place_id=payload.business_id or payload.params.get("place_id"),
            data_id=payload.params.get("data_id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    task = ingest_platform.delay(payload.platform.value, business_id, payload.params)
    return {"status": "queued", "task_id": task.id}
