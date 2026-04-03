"""POST /api/chat — RAG-powered Q&A over customer reviews."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.schemas.insight_schema import ChatRequest, ChatResponse
from app.services.rag_service import run_rag_pipeline

router = APIRouter()


@router.post("", response_model=ChatResponse)
def chat(request: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    """Answer a business question grounded in customer review data.

    - Embeds the latest user message with `query:` prefix (multilingual-e5-base)
    - Retrieves top-20 semantically similar reviews from pgvector HNSW index
    - Re-ranks with cross-encoder (ms-marco-MiniLM-L-6-v2) → keeps top-5
    - Builds token-budgeted context with [1][2][3] citation markers
    - Generates a grounded answer via LangChain → OpenRouter (Llama 3.3 70B)
    """
    # Use the most recent user message as the retrieval query
    user_messages = [m for m in request.messages if m.role == "user"]
    if not user_messages:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Request must contain at least one user message.",
        )

    question = user_messages[-1].content

    try:
        answer, source_ids = run_rag_pipeline(
            db=db,
            question=question,
            business_id=request.business_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"RAG pipeline error: {exc}",
        ) from exc

    return ChatResponse(answer=answer, sources=source_ids)
