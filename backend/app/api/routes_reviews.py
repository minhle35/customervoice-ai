from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from app.database.database import SessionDep

from app.models.review import Platform
from app.schemas.review_schema import ReviewListOut, ReviewOut
from app.services.review_service import ReviewService

# Mounted at: /api/reviews
router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.get("/businesses", summary="GET /api/reviews/businesses")
def list_businesses(db: SessionDep) -> list[dict]:
    """Return distinct businesses that have ingested reviews."""
    return ReviewService(db).get_distinct_businesses()


@router.get("", response_model=ReviewListOut, summary="GET /api/reviews")
def list_reviews(
    db: SessionDep,
    business_id: Optional[str] = Query(None),
    platform: Optional[Platform] = Query(None),
    is_processed: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List reviews with optional filters and pagination."""
    total, items = ReviewService(db).get_reviews(
        business_id=business_id,
        platform=platform,
        is_processed=is_processed,
        limit=limit,
        offset=offset,
    )
    return ReviewListOut(
        total=total,
        items=[ReviewOut.model_validate(item, from_attributes=True) for item in items],
    )


@router.get(
    "/{review_id}", response_model=ReviewOut, summary="GET /api/reviews/{review_id}"
)
def get_review(db: SessionDep, review_id: uuid.UUID) -> ReviewOut:
    """Fetch a single review by ID."""
    review = ReviewService(db).get_by_id(review_id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review not found"
        )
    return ReviewOut.model_validate(review, from_attributes=True)
