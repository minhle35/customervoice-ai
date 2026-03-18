from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.review import Platform
from app.schemas.review_schema import ReviewListOut, ReviewOut
from app.services.review_service import ReviewService

router = APIRouter()


@router.get("", response_model=ReviewListOut)
def list_reviews(
    business_id: Optional[str] = Query(None),
    platform: Optional[Platform] = Query(None),
    is_processed: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List reviews with optional filters and pagination."""
    total, items = ReviewService(db).get_reviews(
        business_id=business_id,
        platform=platform,
        is_processed=is_processed,
        limit=limit,
        offset=offset,
    )
    return ReviewListOut(total=total, items=items)


@router.get("/{review_id}", response_model=ReviewOut)
def get_review(review_id: uuid.UUID, db: Session = Depends(get_db)):
    """Fetch a single review by ID."""
    review = ReviewService(db).get_by_id(review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    return review
