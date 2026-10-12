from __future__ import annotations

import logging
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.api.schemas import (
    SessionCreateRequest,
    SessionListResponse,
    SessionResponse,
)
from backend.app.models import ChatSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sessions", tags=["Sessions"])


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: SessionCreateRequest | None = None,
    db: Session = Depends(get_db),
) -> SessionResponse:
    """Create a new independent persistent chat session."""
    title = payload.title.strip() if payload and payload.title else None
    user_meta = payload.user_metadata if payload else None

    session_id = uuid.uuid4()
    chat_session = ChatSession(
        id=session_id,
        title=title,
        user_metadata=user_meta,
    )
    db.add(chat_session)
    db.commit()
    db.refresh(chat_session)

    logger.info("Created chat session id=%s title=%r", chat_session.id, chat_session.title)
    return SessionResponse.model_validate(chat_session)


@router.get("", response_model=SessionListResponse)
def list_sessions(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> SessionListResponse:
    """List recent persistent chat sessions ordered by latest activity."""
    total = db.scalar(select(func.count(ChatSession.id))) or 0

    stmt = (
        select(ChatSession)
        .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    sessions = db.scalars(stmt).all()

    return SessionListResponse(
        sessions=[SessionResponse.model_validate(s) for s in sessions],
        total=total,
    )
