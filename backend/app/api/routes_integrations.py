from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.integrations.registry import SUPPORTED_PLATFORMS, get_handler
from app.logger import get_logger
from app.schemas.review_schema import IngestRequest
from app.services.serpapi_service import PlaceResult, SerpApiService


def _get_serp_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.serp_client


SerpClientDep = Annotated[httpx.AsyncClient, Depends(_get_serp_client)]

logger = get_logger(__name__)

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
async def search_google_places(
    client: SerpClientDep,
    q: str = Query(..., description="Business name to search"),
    country: str = Query("us", description="Two-letter country code, e.g. vn, au, us"),
):
    """Search Google Maps for a business and return candidates with their data_id.

    Use the returned data_id as params.data_id when triggering ingestion.
    """
    try:
        return await SerpApiService(client=client).search_places(
            query=q, country=country
        )
    except RuntimeError as exc:
        logger.error("SerpAPI search failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to reach Google Maps search. Try again later.",
        ) from exc


@router.get("/tasks/{task_id}", summary="GET /api/integrations/tasks/{task_id}")
def get_task_status(task_id: str):
    result = celery_app.AsyncResult(task_id)
    response: dict = {"task_id": task_id, "status": result.state}
    if result.state == "PROGRESS":
        response["progress"] = result.info
    elif result.state == "SUCCESS":
        response["result"] = result.result
    elif result.state == "FAILURE":
        logger.error("Task %s failed: %s", task_id, result.info)
        response["error"] = "Task failed. Check worker logs for details."
    return response


@router.post("/reprocess", summary="POST /api/integrations/reprocess")
def reprocess_unprocessed(limit: int = 100):
    """Retry sentiment analysis + embedding for reviews stranded by rate limits."""
    task = process_unprocessed_reviews.delay(limit=limit)
    return {"status": "queued", "task_id": task.id}


@router.post("/{platform}", summary="POST /api/integrations/{platform}")
def trigger_ingestion(platform: str, payload: IngestRequest):
    if platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported platform '{platform}'. Supported: {SUPPORTED_PLATFORMS}",
        )

    try:
        handler = get_handler(platform)
        business_id = handler.derive_business_id(
            {"place_id": payload.business_id, **payload.params}
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    task = ingest_platform.delay(payload.platform.value, business_id, payload.params)
    return {"status": "queued", "task_id": task.id}
