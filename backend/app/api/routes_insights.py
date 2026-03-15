from fastapi import APIRouter

router = APIRouter()


@router.get("/summary")
def insights_summary():
    return {"summary": ""}


@router.get("/topics")
def insights_topics():
    return {"topics": []}

