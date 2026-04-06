from fastapi import APIRouter

# Mounted at: /api/insights
router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("/summary", summary="GET /api/insights/summary")
def insights_summary():
    return {"summary": ""}


@router.get("/topics", summary="GET /api/insights/topics")
def insights_topics():
    return {"topics": []}
