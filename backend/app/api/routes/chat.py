from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Annotated
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import (
    get_app_settings,
    get_db,
    get_pi_agent_client,
    get_rag_service,
)
from backend.app.api.schemas import (
    ChatMessageRequest,
    ChatMessageResponse,
    SessionMessagesResponse,
)
from backend.app.config import Settings
from backend.app.models import ChatMessage, ChatSession, Episode, TranscriptChunk
from backend.app.rag.pi_client import PiAgentClient
from backend.app.rag.provider_base import (
    ProviderAuthenticationError,
    ProviderConfigError,
    ProviderConnectionError,
    ProviderError,
    ProviderModelNotFoundError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from backend.app.rag.service import RAGResponse, RAGService
from backend.app.retrieval.search import SearchResult, format_seconds_to_timestamp

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sessions", tags=["Chat"])


@router.get("/{session_id}/messages", response_model=SessionMessagesResponse)
def get_session_messages(
    session_id: UUID,
    db: Session = Depends(get_db),
) -> SessionMessagesResponse:
    """Retrieve all chronological messages and validated citations for a session."""
    chat_session = db.get(ChatSession, session_id)
    if chat_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "SESSION_NOT_FOUND",
                "message": f"Chat session '{session_id}' does not exist.",
            },
        )

    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
    )
    messages = db.scalars(stmt).all()

    return SessionMessagesResponse(
        session_id=session_id,
        messages=[ChatMessageResponse.model_validate(m) for m in messages],
    )


@router.post("/{session_id}/messages", response_model=ChatMessageResponse, status_code=status.HTTP_201_CREATED)
def send_chat_message(
    session_id: UUID,
    payload: ChatMessageRequest,
    db: Session = Depends(get_db),
    rag_service: RAGService = Depends(get_rag_service),
    settings: Settings = Depends(get_app_settings),
    pi_client: PiAgentClient = Depends(get_pi_agent_client),
) -> ChatMessageResponse:
    """
    Submit a user question, retrieve grounded evidence from transcript archives,
    generate an answer (via local RAG or Pi Agent orchestrator), and persist validated citations.

    Enforces session isolation, atomic user-message persistence, and graceful error handling.
    """
    # 1. Verify session exists
    chat_session = db.get(ChatSession, session_id)
    if chat_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "SESSION_NOT_FOUND",
                "message": f"Chat session '{session_id}' does not exist.",
            },
        )

    user_text = payload.message.strip()
    request_id = f"req_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)

    # 2. Persist user message immediately in DB so it is preserved even if generation fails
    user_msg = ChatMessage(
        session_id=session_id,
        role="user",
        content=user_text,
        request_id=request_id,
        created_at=now,
    )
    db.add(user_msg)
    chat_session.updated_at = now
    db.commit()
    db.refresh(user_msg)

    logger.info("Persisted user message id=%d in session=%s request_id=%s", user_msg.id, session_id, request_id)

    # 3. Load prior message history for this session (excluding current user message)
    prior_stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id, ChatMessage.id != user_msg.id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
    )
    prior_messages = db.scalars(prior_stmt).all()
    history_turns = [
        {"role": m.role, "content": m.content}
        for m in prior_messages
    ]

    # 4. Generate answer outside database transaction using configured orchestrator
    active_orchestrator = payload.orchestrator or settings.chat_orchestrator
    try:
        if active_orchestrator == "pi":
            agent_result = pi_client.run_agent(
                question=user_text,
                conversation_history=history_turns,
                request_id=request_id,
            )
            raw_content = agent_result.get("content", "")
            raw_sources = agent_result.get("sources", [])
            raw_chunk_ids = [
                c["chunk_id"] for c in raw_sources if isinstance(c, dict) and "chunk_id" in c
            ]

            ordered_search_results: list[SearchResult] = []
            if raw_chunk_ids:
                stmt_chunks = (
                    select(TranscriptChunk, Episode)
                    .join(Episode, TranscriptChunk.episode_id == Episode.id)
                    .where(TranscriptChunk.id.in_(raw_chunk_ids))
                )
                chunk_map = {chunk.id: (chunk, ep) for chunk, ep in db.execute(stmt_chunks).all()}
                for c in raw_sources:
                    cid = c.get("chunk_id")
                    if cid in chunk_map:
                        chunk, ep = chunk_map[cid]
                        dist_val = float(c.get("cosine_distance")) if c.get("cosine_distance") is not None else 0.0
                        ordered_search_results.append(
                            SearchResult(
                                chunk_id=chunk.id,
                                chunk_index=chunk.chunk_index,
                                chunk_text=chunk.chunk_text,
                                cosine_distance=dist_val,
                                guest=ep.guest,
                                title=ep.title,
                                source_path=ep.source_path,
                                speaker=chunk.speaker,
                                start_time_seconds=chunk.start_time_seconds,
                                timestamp=format_seconds_to_timestamp(chunk.start_time_seconds),
                                embedding_model=chunk.embedding_model,
                                alternate_sources=[],
                            )
                        )

            validated_sources = rag_service._build_validated_sources(
                relevant_chunks=ordered_search_results,
                generated_text=raw_content,
            )

            rag_response = RAGResponse(
                content=raw_content,
                provider=agent_result.get("provider", f"pi-agent-{settings.pi_agent_model_provider}"),
                model=agent_result.get("model", settings.pi_agent_model_id),
                sources=validated_sources,
                retrieval_count=len(ordered_search_results),
                relevant_count=len(validated_sources),
            )
        else:
            rag_response = rag_service.answer_question(
                user_question=user_text,
                conversation_history=history_turns,
            )
    except ProviderTimeoutError as exc:
        logger.error("Inference timed out for request_id=%s: %s", request_id, exc)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "code": "LLM_GENERATION_TIMEOUT",
                "message": "Model generation timed out. The user message has been preserved.",
                "request_id": request_id,
            },
        ) from exc
    except ProviderConnectionError as exc:
        logger.error("Could not connect to model provider for request_id=%s: %s", request_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "LLM_SERVICE_UNAVAILABLE",
                "message": "Model provider service is unavailable. The user message has been preserved.",
                "request_id": request_id,
            },
        ) from exc
    except ProviderModelNotFoundError as exc:
        logger.error("Configured model not found for request_id=%s: %s", request_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "LLM_MODEL_NOT_FOUND",
                "message": str(exc),
                "request_id": request_id,
            },
        ) from exc
    except ProviderAuthenticationError as exc:
        logger.error("Provider authentication failed for request_id=%s: %s", request_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "LLM_AUTHENTICATION_ERROR",
                "message": "Authentication failed with the configured model provider.",
                "request_id": request_id,
            },
        ) from exc
    except ProviderRateLimitError as exc:
        logger.error("Provider rate limit exceeded for request_id=%s: %s", request_id, exc)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "LLM_RATE_LIMIT_EXCEEDED",
                "message": "Provider rate limit or quota exceeded. Please try again later.",
                "request_id": request_id,
            },
        ) from exc
    except ProviderConfigError as exc:
        logger.error("Provider configuration error for request_id=%s: %s", request_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "LLM_CONFIGURATION_ERROR",
                "message": str(exc),
                "request_id": request_id,
            },
        ) from exc
    except ProviderError as exc:
        logger.error("Model inference error for request_id=%s: %s", request_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "LLM_INFERENCE_ERROR",
                "message": str(exc),
                "request_id": request_id,
            },
        ) from exc
    except Exception as exc:
        logger.error("Unexpected RAG error for request_id=%s: %s", request_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "RAG_PROCESSING_ERROR",
                "message": f"RAG processing failed: {exc}",
                "request_id": request_id,
            },
        ) from exc

    # 5. Persist assistant response with validated citations
    now_asst = datetime.now(timezone.utc)
    asst_msg = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=rag_response.content,
        provider=rag_response.provider,
        model=rag_response.model,
        sources=rag_response.sources,
        request_id=request_id,
        created_at=now_asst,
    )
    db.add(asst_msg)
    chat_session.updated_at = now_asst
    db.commit()
    db.refresh(asst_msg)

    logger.info(
        "Persisted assistant response id=%d (sources=%d) in session=%s request_id=%s",
        asst_msg.id,
        len(asst_msg.sources or []),
        session_id,
        request_id,
    )

    return ChatMessageResponse.model_validate(asst_msg)
