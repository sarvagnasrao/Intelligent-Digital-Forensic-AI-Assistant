"""Persistence helpers for case-scoped AI conversations."""
from __future__ import annotations

import json

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.models import AIChatMessage


class AIChatService:
    def __init__(self, session: Session):
        self.session = session

    def list_messages(self, case_id: int) -> list[dict]:
        statement = (
            select(AIChatMessage)
            .where(AIChatMessage.case_id == case_id)
            .order_by(AIChatMessage.id)
        )
        return [
            {
                "id": message.id,
                "role": message.role,
                "mode": message.mode,
                "content": message.content,
                "citations": json.loads(message.citations_json or "[]"),
            }
            for message in self.session.execute(statement).scalars()
        ]

    def add_message(
        self,
        case_id: int,
        role: str,
        content: str,
        *,
        mode: str = "analysis",
        citations: list[dict] | None = None,
    ) -> None:
        if role not in {"user", "assistant"}:
            raise ValueError(f"Unsupported chat role: {role}")
        message = AIChatMessage(
            case_id=case_id,
            role=role,
            mode=mode,
            content=content,
            citations_json=json.dumps(citations or [], ensure_ascii=False),
        )
        self.session.add(message)
        self.session.commit()

    def clear(self, case_id: int) -> None:
        self.session.execute(
            delete(AIChatMessage).where(AIChatMessage.case_id == case_id)
        )
        self.session.commit()
