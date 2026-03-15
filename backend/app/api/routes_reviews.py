from fastapi import APIRouter

router = APIRouter()


@router.get("")
def list_reviews():
    return {"items": []}


@router.post("/ingest")
def ingest_reviews():
    return {"status": "queued"}

