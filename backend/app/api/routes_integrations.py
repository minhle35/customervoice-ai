from fastapi import APIRouter

router = APIRouter()


@router.post("/google")
def connect_google():
    return {"status": "connected"}


@router.post("/reddit")
def connect_reddit():
    return {"status": "connected"}


@router.post("/facebook")
def connect_facebook():
    return {"status": "connected"}

