from __future__ import annotations

from unittest.mock import MagicMock
import uuid

from fastapi import status
import pytest
from sqlalchemy import select

from backend.app.api.deps import get_rag_service
from backend.app.api.main import app
from backend.app.models import ChatMessage, ChatSession
from backend.app.rag.ollama_client import (
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaTimeoutError,
)
from backend.app.rag.service import RAGResponse, RAGService


def test_send_message_validation_empty(api_client) -> None:
    session_resp = api_client.post("/api/v1/sessions", json={"title": "Test Session"})
    session_id = session_resp.json()["id"]

    # Empty string
    resp_empty = api_client.post(f"/api/v1/sessions/{session_id}/messages", json={"message": ""})
    assert resp_empty.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Whitespace only
    resp_ws = api_client.post(f"/api/v1/sessions/{session_id}/messages", json={"message": "   "})
    assert resp_ws.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_send_message_validation_max_length(api_client) -> None:
    session_resp = api_client.post("/api/v1/sessions", json={"title": "Test Session"})
    session_id = session_resp.json()["id"]

    long_message = "a" * 4001
    resp = api_client.post(f"/api/v1/sessions/{session_id}/messages", json={"message": long_message})
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_send_message_session_not_found(api_client) -> None:
    fake_id = str(uuid.uuid4())
    resp = api_client.post(f"/api/v1/sessions/{fake_id}/messages", json={"message": "Hello"})
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    data = resp.json()
    assert data["error"]["code"] == "SESSION_NOT_FOUND"


def test_send_message_success_with_citations(api_client, db_session_factory) -> None:
    session_resp = api_client.post("/api/v1/sessions", json={"title": "Strategy"})
    session_id = session_resp.json()["id"]

    mock_rag = MagicMock(spec=RAGService)
    mock_sources = [
        {
            "citation_index": 1,
            "is_cited": True,
            "chunk_id": 42,
            "chunk_index": 5,
            "source_path": "episodes/ben-williams/transcript.md",
            "guest": "Ben Williams",
            "title": "PLG Juggernaut",
            "speaker": "Ben",
            "timestamp": "00:10:00",
            "start_time_seconds": 600.0,
            "cosine_distance": 0.2215,
            "excerpt": "Growth teams focus on the right inputs.",
            "alternate_sources": [],
        }
    ]
    mock_rag.answer_question.return_value = RAGResponse(
        content="According to Ben Williams [Source 1], effective growth teams focus on inputs.",
        provider="ollama",
        model="qwen3.5:9b",
        sources=mock_sources,
        retrieval_count=1,
        relevant_count=1,
    )

    app.dependency_overrides[get_rag_service] = lambda: mock_rag
    try:
        chat_resp = api_client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"message": "What makes growth teams effective?"},
        )
        assert chat_resp.status_code == status.HTTP_201_CREATED
        data = chat_resp.json()

        assert data["role"] == "assistant"
        assert "[Source 1]" in data["content"]
        assert data["provider"] == "ollama"
        assert data["model"] == "qwen3.5:9b"
        assert len(data["sources"]) == 1
        assert data["sources"][0]["guest"] == "Ben Williams"
        assert data["sources"][0]["chunk_id"] == 42
        assert "request_id" in data

        # Verify persistence in database
        with db_session_factory() as session:
            db_msgs = session.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == uuid.UUID(session_id))
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            ).all()
            assert len(db_msgs) == 2
            assert db_msgs[0].role == "user"
            assert db_msgs[0].content == "What makes growth teams effective?"
            assert db_msgs[1].role == "assistant"
            assert db_msgs[1].content == data["content"]
            assert len(db_msgs[1].sources) == 1

            # Verify session updated_at was refreshed
            sess = session.get(ChatSession, uuid.UUID(session_id))
            assert sess is not None
            assert sess.updated_at >= sess.created_at

    finally:
        app.dependency_overrides.pop(get_rag_service, None)


def test_chat_session_context_isolation_and_followup(api_client) -> None:
    # Create two separate sessions
    resp_a = api_client.post("/api/v1/sessions", json={"title": "Session A"})
    resp_b = api_client.post("/api/v1/sessions", json={"title": "Session B"})
    id_a = resp_a.json()["id"]
    id_b = resp_b.json()["id"]

    mock_rag = MagicMock(spec=RAGService)
    app.dependency_overrides[get_rag_service] = lambda: mock_rag

    try:
        # Turn 1 in Session A
        mock_rag.answer_question.return_value = RAGResponse(
            content="Answer 1 for Session A.",
            provider="ollama",
            model="qwen3.5:9b",
            sources=[],
            retrieval_count=1,
            relevant_count=1,
        )
        api_client.post(f"/api/v1/sessions/{id_a}/messages", json={"message": "Question 1 in A"})

        # Verify RAG was called with empty prior history
        assert mock_rag.answer_question.call_args[1]["conversation_history"] == []

        # Turn 2 in Session A (follow-up)
        mock_rag.answer_question.return_value = RAGResponse(
            content="Answer 2 for Session A.",
            provider="ollama",
            model="qwen3.5:9b",
            sources=[],
            retrieval_count=1,
            relevant_count=1,
        )
        api_client.post(f"/api/v1/sessions/{id_a}/messages", json={"message": "Follow-up in A"})

        # Verify Session A follow-up includes Turn 1 history
        called_history_a = mock_rag.answer_question.call_args[1]["conversation_history"]
        assert len(called_history_a) == 2
        assert called_history_a[0] == {"role": "user", "content": "Question 1 in A"}
        assert called_history_a[1] == {"role": "assistant", "content": "Answer 1 for Session A."}

        # Turn 1 in Session B
        mock_rag.answer_question.return_value = RAGResponse(
            content="Answer 1 for Session B.",
            provider="ollama",
            model="qwen3.5:9b",
            sources=[],
            retrieval_count=1,
            relevant_count=1,
        )
        api_client.post(f"/api/v1/sessions/{id_b}/messages", json={"message": "Question 1 in B"})

        # Verify Session B does NOT see Session A's history!
        called_history_b = mock_rag.answer_question.call_args[1]["conversation_history"]
        assert called_history_b == []

    finally:
        app.dependency_overrides.pop(get_rag_service, None)


def test_ollama_timeout_preserves_user_message(api_client, db_session_factory) -> None:
    session_resp = api_client.post("/api/v1/sessions", json={"title": "Timeout Test"})
    session_id = session_resp.json()["id"]

    mock_rag = MagicMock(spec=RAGService)
    mock_rag.answer_question.side_effect = OllamaTimeoutError("Chat generation timed out after 60s")

    app.dependency_overrides[get_rag_service] = lambda: mock_rag
    try:
        resp = api_client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"message": "Slow query that times out"},
        )
        assert resp.status_code == status.HTTP_504_GATEWAY_TIMEOUT
        data = resp.json()
        assert data["error"]["code"] == "LLM_GENERATION_TIMEOUT"
        assert "request_id" in data["error"]

        # Crucial check: User message MUST be preserved in database!
        with db_session_factory() as session:
            msgs = session.scalars(
                select(ChatMessage).where(ChatMessage.session_id == uuid.UUID(session_id))
            ).all()
            assert len(msgs) == 1
            assert msgs[0].role == "user"
            assert msgs[0].content == "Slow query that times out"

    finally:
        app.dependency_overrides.pop(get_rag_service, None)


def test_ollama_connection_error_preserves_user_message(api_client, db_session_factory) -> None:
    session_resp = api_client.post("/api/v1/sessions", json={"title": "Connection Err Test"})
    session_id = session_resp.json()["id"]

    mock_rag = MagicMock(spec=RAGService)
    mock_rag.answer_question.side_effect = OllamaConnectionError("Failed to connect to Ollama")

    app.dependency_overrides[get_rag_service] = lambda: mock_rag
    try:
        resp = api_client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"message": "Message when Ollama is down"},
        )
        assert resp.status_code == status.HTTP_502_BAD_GATEWAY
        data = resp.json()
        assert data["error"]["code"] == "LLM_SERVICE_UNAVAILABLE"

        # User message preserved
        with db_session_factory() as session:
            msgs = session.scalars(
                select(ChatMessage).where(ChatMessage.session_id == uuid.UUID(session_id))
            ).all()
            assert len(msgs) == 1
            assert msgs[0].role == "user"
            assert msgs[0].content == "Message when Ollama is down"

    finally:
        app.dependency_overrides.pop(get_rag_service, None)


def test_ollama_model_not_found_returns_clear_error(api_client) -> None:
    session_resp = api_client.post("/api/v1/sessions", json={"title": "Missing Model"})
    session_id = session_resp.json()["id"]

    mock_rag = MagicMock(spec=RAGService)
    mock_rag.answer_question.side_effect = OllamaModelNotFoundError("Model 'non-existent:model' not installed")

    app.dependency_overrides[get_rag_service] = lambda: mock_rag
    try:
        resp = api_client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"message": "Query with missing model"},
        )
        assert resp.status_code == status.HTTP_502_BAD_GATEWAY
        data = resp.json()
        assert data["error"]["code"] == "LLM_MODEL_NOT_FOUND"

    finally:
        app.dependency_overrides.pop(get_rag_service, None)


def test_search_failure_returns_controlled_rag_processing_error(api_client) -> None:
    session_resp = api_client.post("/api/v1/sessions", json={"title": "Search Failure Test"})
    session_id = session_resp.json()["id"]

    mock_rag = MagicMock(spec=RAGService)
    mock_rag.answer_question.side_effect = RuntimeError("Database vector search connection crashed")

    app.dependency_overrides[get_rag_service] = lambda: mock_rag
    try:
        resp = api_client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"message": "What is growth?"},
        )
        assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        data = resp.json()
        assert data["error"]["code"] == "RAG_PROCESSING_ERROR"
        assert "Database vector search connection crashed" in data["error"]["message"]
    finally:
        app.dependency_overrides.pop(get_rag_service, None)

