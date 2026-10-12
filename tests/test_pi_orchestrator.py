from __future__ import annotations

from unittest.mock import MagicMock
import uuid
from fastapi import status
import httpx
import pytest

from backend.app.api.deps import get_app_settings, get_pi_agent_client, get_rag_service
from backend.app.api.main import app
from backend.app.config import load_settings
from backend.app.models import ChatMessage, ChatSession, Episode, TranscriptChunk
from backend.app.rag.pi_client import PiAgentClient
from backend.app.rag.provider_base import (
    ProviderConnectionError,
    ProviderError,
    ProviderTimeoutError,
)
from backend.app.rag.service import RAGResponse, RAGService


def test_pi_agent_client_check_health_success(monkeypatch) -> None:
    settings = load_settings(
        database_url="postgresql+psycopg://user:pass@localhost:5432/db",
        pi_agent_host="127.0.0.1",
        pi_agent_port=3000,
    )
    client = PiAgentClient(settings=settings)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "ok", "service": "lenny-pi-agent"}

    monkeypatch.setattr(httpx.Client, "get", lambda self, url: mock_resp)
    health = client.check_health()
    assert health["status"] == "ok"


def test_pi_agent_client_connection_error(monkeypatch) -> None:
    settings = load_settings(
        database_url="postgresql+psycopg://user:pass@localhost:5432/db",
        pi_agent_host="127.0.0.1",
        pi_agent_port=3000,
    )
    client = PiAgentClient(settings=settings)

    def mock_get(self, url):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx.Client, "get", mock_get)
    with pytest.raises(ProviderConnectionError, match="Failed to connect"):
        client.check_health()


def test_pi_orchestrator_chat_endpoint_success(api_client, db_session_factory) -> None:
    # 1. Create session and seed DB with real episode and chunk
    with db_session_factory() as session:
        ep = Episode(
            source_path="episodes/brian-chesky/transcript.md",
            guest="Brian Chesky",
            title="Leading Through Crisis",
            source_sha256="sha1111111",
            body_sha256="sha2222222",
        )
        session.add(ep)
        session.commit()
        session.refresh(ep)

        chunk = TranscriptChunk(
            episode_id=ep.id,
            chunk_index=3,
            chunk_text="You have to design the 11-star experience.",
            chunk_sha256="chunk_sha_33333",
            token_count=12,
            character_count=42,
            speaker="Brian",
            start_time_seconds=180.0,
        )
        session.add(chunk)
        session.commit()
        session.refresh(chunk)
        chunk_id = chunk.id

    session_resp = api_client.post("/api/v1/sessions", json={"title": "Design Talk"})
    session_id = session_resp.json()["id"]

    # 2. Configure app settings with chat_orchestrator="pi"
    pi_settings = load_settings(
        database_url="postgresql+psycopg://user:pass@localhost:5432/db",
        chat_orchestrator="pi",
        pi_agent_model_provider="ollama",
        pi_agent_model_id="qwen3.5:9b",
    )

    mock_pi_client = MagicMock(spec=PiAgentClient)
    mock_pi_client.run_agent.return_value = {
        "content": "Brian Chesky advocates for designing an 11-star experience [Source 1].",
        "provider": "pi-agent-ollama",
        "model": "qwen3.5:9b",
        "sources": [
            {
                "chunk_id": chunk_id,
                "cosine_distance": 0.12,
            }
        ],
        "retrieval_count": 1,
        "relevant_count": 1,
        "elapsed_seconds": 1.25,
        "request_id": "req_test_123",
    }

    app.dependency_overrides[get_app_settings] = lambda: pi_settings
    app.dependency_overrides[get_pi_agent_client] = lambda: mock_pi_client

    try:
        resp = api_client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"message": "What is the 11-star experience?"},
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()

        assert data["role"] == "assistant"
        assert "11-star experience" in data["content"]
        assert data["provider"] == "pi-agent-ollama"
        assert data["model"] == "qwen3.5:9b"
        assert len(data["sources"]) == 1
        assert data["sources"][0]["chunk_id"] == chunk_id
        assert data["sources"][0]["guest"] == "Brian Chesky"
        assert data["sources"][0]["is_cited"] is True

        # Verify DB persistence
        with db_session_factory() as session:
            msgs = session.query(ChatMessage).filter_by(session_id=uuid.UUID(session_id)).all()
            assert len(msgs) == 2
            assert msgs[0].role == "user"
            assert msgs[1].role == "assistant"
            assert msgs[1].provider == "pi-agent-ollama"
    finally:
        app.dependency_overrides.pop(get_app_settings, None)
        app.dependency_overrides.pop(get_pi_agent_client, None)


def test_pi_orchestrator_handles_agent_timeout(api_client) -> None:
    session_resp = api_client.post("/api/v1/sessions", json={"title": "Timeout Test"})
    session_id = session_resp.json()["id"]

    pi_settings = load_settings(
        database_url="postgresql+psycopg://user:pass@localhost:5432/db",
        chat_orchestrator="pi",
    )
    mock_pi_client = MagicMock(spec=PiAgentClient)
    mock_pi_client.run_agent.side_effect = ProviderTimeoutError("Inference timed out")

    app.dependency_overrides[get_app_settings] = lambda: pi_settings
    app.dependency_overrides[get_pi_agent_client] = lambda: mock_pi_client

    try:
        resp = api_client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"message": "Slow request question"},
        )
        assert resp.status_code == status.HTTP_504_GATEWAY_TIMEOUT
        assert resp.json()["error"]["code"] == "LLM_GENERATION_TIMEOUT"
    finally:
        app.dependency_overrides.pop(get_app_settings, None)
        app.dependency_overrides.pop(get_pi_agent_client, None)


def test_default_orchestrator_remains_rag(api_client) -> None:
    session_resp = api_client.post("/api/v1/sessions", json={"title": "Default RAG"})
    session_id = session_resp.json()["id"]

    mock_rag = MagicMock(spec=RAGService)
    mock_rag.answer_question.return_value = RAGResponse(
        content="Standard RAG answer.",
        provider="ollama",
        model="qwen3.5:9b",
        sources=[],
        retrieval_count=0,
        relevant_count=0,
    )

    mock_pi_client = MagicMock(spec=PiAgentClient)

    app.dependency_overrides[get_rag_service] = lambda: mock_rag
    app.dependency_overrides[get_pi_agent_client] = lambda: mock_pi_client

    try:
        resp = api_client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"message": "Direct question"},
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()["content"] == "Standard RAG answer."
        # Crucial invariant: Pi client should NOT be called when CHAT_ORCHESTRATOR=rag
        mock_pi_client.run_agent.assert_not_called()
        mock_rag.answer_question.assert_called_once()
    finally:
        app.dependency_overrides.pop(get_rag_service, None)
        app.dependency_overrides.pop(get_pi_agent_client, None)


def test_pi_orchestrator_rejects_fabricated_sources(api_client, db_session_factory) -> None:
    session_resp = api_client.post("/api/v1/sessions", json={"title": "Fabrication Test"})
    session_id = session_resp.json()["id"]

    pi_settings = load_settings(
        database_url="postgresql+psycopg://user:pass@localhost:5432/db",
        chat_orchestrator="pi",
    )
    mock_pi_client = MagicMock(spec=PiAgentClient)
    # Return a fake/fabricated chunk ID that does not exist in the database
    mock_pi_client.run_agent.return_value = {
        "content": "Fabricated statement claiming something false [Source 1].",
        "provider": "pi-agent-ollama",
        "model": "qwen3.5:9b",
        "sources": [{"chunk_id": 9999999, "cosine_distance": 0.05}],
        "retrieval_count": 1,
        "relevant_count": 1,
        "elapsed_seconds": 0.5,
        "request_id": "req_fab_1",
    }

    app.dependency_overrides[get_app_settings] = lambda: pi_settings
    app.dependency_overrides[get_pi_agent_client] = lambda: mock_pi_client

    try:
        resp = api_client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"message": "Tell me a secret"},
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        # Fabricated chunk ID 9999999 MUST be rejected by backend
        assert data["sources"] == []

        with db_session_factory() as session:
            asst_msg = (
                session.query(ChatMessage)
                .filter_by(session_id=uuid.UUID(session_id), role="assistant")
                .first()
            )
            assert asst_msg is not None
            assert asst_msg.sources == []
    finally:
        app.dependency_overrides.pop(get_app_settings, None)
        app.dependency_overrides.pop(get_pi_agent_client, None)


def test_pi_orchestrator_connection_error_preserves_user_message(api_client, db_session_factory) -> None:
    session_resp = api_client.post("/api/v1/sessions", json={"title": "Error Preservation Test"})
    session_id = session_resp.json()["id"]

    pi_settings = load_settings(
        database_url="postgresql+psycopg://user:pass@localhost:5432/db",
        chat_orchestrator="pi",
    )
    mock_pi_client = MagicMock(spec=PiAgentClient)
    mock_pi_client.run_agent.side_effect = ProviderConnectionError("Pi service unreachable")

    app.dependency_overrides[get_app_settings] = lambda: pi_settings
    app.dependency_overrides[get_pi_agent_client] = lambda: mock_pi_client

    try:
        resp = api_client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"message": "Will this fail gracefully?"},
        )
        assert resp.status_code == status.HTTP_502_BAD_GATEWAY
        assert resp.json()["error"]["code"] == "LLM_SERVICE_UNAVAILABLE"

        # Invariant: User message MUST be preserved, but NO assistant message was created
        with db_session_factory() as session:
            msgs = (
                session.query(ChatMessage)
                .filter_by(session_id=uuid.UUID(session_id))
                .order_by(ChatMessage.created_at.asc())
                .all()
            )
            assert len(msgs) == 1
            assert msgs[0].role == "user"
            assert msgs[0].content == "Will this fail gracefully?"
    finally:
        app.dependency_overrides.pop(get_app_settings, None)
        app.dependency_overrides.pop(get_pi_agent_client, None)

