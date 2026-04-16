import uuid

from fastapi import APIRouter, HTTPException, status

from app.database import SessionDep
from app.logger import get_logger
from app.schemas.insight_schema import ChatHistoryMessage, ChatRequest, ChatResponse
from app.services.chat_service import ChatService
from app.services.rag_service import run_rag_pipeline

logger = get_logger(__name__)

# Mounted at: /api/chat
router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.get(
    "/{business_id}/history",
    response_model=list[ChatHistoryMessage],
    summary="GET /api/chat/{business_id}/history",
)
def get_chat_history(business_id: str, db: SessionDep) -> list[ChatHistoryMessage]:
    """Return persisted chat history for a business, oldest-first."""
    messages = ChatService(db).get_history(business_id)
    return [
        ChatHistoryMessage(
            id=m.id,
            role=m.role,
            content=m.content,
            sources=[uuid.UUID(s) for s in (m.source_review_ids or "").split(",") if s],
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.post("", response_model=ChatResponse, summary="POST /api/chat")
def chat(request: ChatRequest, db: SessionDep) -> ChatResponse:
    """Answer a business question grounded in customer review data.

    - Embeds the latest user message with `query:` prefix (multilingual-e5-base)
    - Retrieves top-20 semantically similar reviews from pgvector HNSW index
    - Re-ranks with cross-encoder (ms-marco-MiniLM-L-6-v2) → keeps top-5
    - Builds token-budgeted context with [1][2][3] citation markers
    - Generates a grounded answer via LangChain → OpenRouter
    """
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
        logger.error(
            "RAG pipeline error for business_id=%s: %s",
            request.business_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate an answer. Try again later.",
        ) from exc

    ChatService(db).save_turn(
        business_id=request.business_id,
        user_content=question,
        assistant_content=answer,
        source_ids=source_ids,
    )

    return ChatResponse(answer=answer, sources=source_ids)
