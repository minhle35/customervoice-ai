from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage


class ChatService:
    def __init__(self, db: Session):
        self.db = db

    def save_turn(
        self,
        business_id: str,
        user_content: str,
        assistant_content: str,
        source_ids: Optional[list[uuid.UUID]] = None,
    ) -> None:
        """Persist a user+assistant turn as two rows."""
        source_str = ",".join(str(s) for s in source_ids) if source_ids else None

        self.db.add(ChatMessage(
            id=uuid.uuid4(),
            business_id=business_id,
            role="user",
            content=user_content,
        ))
        self.db.add(ChatMessage(
            id=uuid.uuid4(),
            business_id=business_id,
            role="assistant",
            content=assistant_content,
            source_review_ids=source_str,
        ))
        self.db.commit()

    def get_history(
        self, business_id: str, limit: int = 100
    ) -> list[ChatMessage]:
        """Return messages for a business ordered oldest-first."""
        return list(
            self.db.execute(
                select(ChatMessage)
                .where(ChatMessage.business_id == business_id)
                .order_by(ChatMessage.created_at.asc())
                .limit(limit)
            ).scalars().all()
        )
