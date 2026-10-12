from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.app.config import Settings
from backend.app.ingestion.embedder import OllamaEmbedder
from backend.app.models import Episode, TranscriptChunk
from backend.app.rag.ollama_client import (
    OllamaChatClient,
    OllamaClientError,
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaTimeoutError,
)
from backend.app.rag.prompt import (
    SYSTEM_PROMPT,
    build_chat_messages,
    format_transcript_context,
)
from backend.app.rag.service import RAGService
from backend.app.retrieval.search import SearchResult


def test_format_transcript_context() -> None:
    chunks = [
        SearchResult(
            chunk_id=1,
            chunk_index=0,
            chunk_text="First passage content.",
            cosine_distance=0.15,
            guest="Guest One",
            title="Episode One",
            source_path="episodes/guest-1/transcript.md",
            speaker="Guest One",
            start_time_seconds=60.0,
            timestamp="00:01:00",
            embedding_model="nomic-embed-text:v1.5",
        ),
        SearchResult(
            chunk_id=2,
            chunk_index=1,
            chunk_text="Second passage content.",
            cosine_distance=0.20,
            guest="Guest Two",
            title="Episode Two",
            source_path="episodes/guest-2/transcript.md",
            speaker="Lenny",
            start_time_seconds=120.0,
            timestamp="00:02:00",
            embedding_model="nomic-embed-text:v1.5",
        ),
    ]

    formatted = format_transcript_context(chunks)
    assert "[Source 1]" in formatted
    assert "Guest: Guest One" in formatted
    assert "Episode: Episode One" in formatted
    assert "00:01:00" in formatted
    assert "First passage content." in formatted

    assert "[Source 2]" in formatted
    assert "Guest: Guest Two" in formatted
    assert "Second passage content." in formatted


def test_build_chat_messages_includes_system_and_history() -> None:
    history = [
        {"role": "user", "content": "Prior question"},
        {"role": "assistant", "content": "Prior answer"},
    ]
    messages = build_chat_messages(
        user_question="New question",
        retrieved_chunks=[],
        conversation_history=history,
    )

    assert len(messages) == 4
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert messages[1] == {"role": "user", "content": "Prior question"}
    assert messages[2] == {"role": "assistant", "content": "Prior answer"}
    assert messages[3]["role"] == "user"
    assert "New question" in messages[3]["content"]
    assert "None found" in messages[3]["content"]


def test_ollama_client_check_server_health_success() -> None:
    client = OllamaChatClient(default_model="qwen3.5:9b")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [{"name": "nomic-embed-text:v1.5"}, {"name": "qwen3.5:9b"}]
    }

    with patch("httpx.Client.get", return_value=mock_resp):
        health = client.check_server_health()
        assert health["available"] is True
        assert health["model_available"] is True
        assert "qwen3.5:9b" in health["models"]


def test_ollama_client_check_server_health_failure() -> None:
    client = OllamaChatClient(default_model="qwen3.5:9b")

    with patch("httpx.Client.get", side_effect=httpx.ConnectError("Connection refused")):
        health = client.check_server_health()
        assert health["available"] is False
        assert health["model_available"] is False
        assert health["error"] == "connection_refused"


def test_ollama_client_model_not_found_raises() -> None:
    client = OllamaChatClient(default_model="nonexistent-model")

    with patch.object(client, "check_server_health", return_value={"available": True, "models": ["other:model"]}):
        with pytest.raises(OllamaModelNotFoundError, match="is not installed"):
            client.generate_chat_response(messages=[{"role": "user", "content": "hi"}])


def test_ollama_client_timeout_raises() -> None:
    client = OllamaChatClient(default_model="qwen3.5:9b", timeout_seconds=5.0)

    with patch.object(client, "verify_model_available", return_value=True):
        with patch("httpx.Client.post", side_effect=httpx.TimeoutException("Read timeout")):
            with pytest.raises(OllamaTimeoutError, match="timed out"):
                client.generate_chat_response(messages=[{"role": "user", "content": "hi"}])


def test_rag_service_supported_query_and_citations(db_session_factory) -> None:
    # Seed database with a supported chunk
    vec = [0.3] * 768
    with db_session_factory() as session:
        ep = Episode(
            source_path="episodes/ben-williams/transcript.md",
            guest="Ben Williams",
            title="PLG at Snyk",
            source_platform="youtube",
            source_sha256="s" * 64,
            body_sha256="b" * 64,
            raw_metadata={},
        )
        session.add(ep)
        session.flush()

        chunk = TranscriptChunk(
            episode_id=ep.id,
            chunk_index=0,
            chunk_text="A growth team should focus on product metrics and experimentation.",
            chunk_sha256="c" * 64,
            token_count=50,
            character_count=65,
            speaker="Ben Williams",
            start_time_seconds=120.0,
            embedding=vec,
        )
        session.add(chunk)
        session.commit()

    mock_embedder = MagicMock(spec=OllamaEmbedder)
    mock_embedder.model = "nomic-embed-text:v1.5"
    mock_embedder.dimensions = 768
    mock_embedder.embed_query.return_value = vec  # Exact match (cosine distance ~0.0)

    mock_chat_client = MagicMock(spec=OllamaChatClient)
    mock_chat_client.generate_chat_response.return_value = {
        "content": "According to Ben Williams [Source 1], growth teams focus on product metrics.",
        "model": "qwen3.5:9b",
    }

    settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        retrieval_max_cosine_distance=0.30,
        retrieval_top_k=2,
    )

    rag = RAGService(
        settings=settings,
        session_factory=db_session_factory,
        embedder=mock_embedder,
        chat_client=mock_chat_client,
    )

    res = rag.answer_question("growth teams")
    assert res.provider == "ollama"
    assert res.model == "qwen3.5:9b"
    assert len(res.sources) == 1
    assert res.sources[0]["guest"] == "Ben Williams"
    assert res.sources[0]["chunk_index"] == 0
    assert res.sources[0]["cosine_distance"] < 0.05
    assert res.relevant_count == 1


def test_rag_service_unsupported_query_returns_empty_sources(db_session_factory) -> None:
    # Seed database with an unrelated chunk
    vec_chunk = [0.5] * 768
    vec_query = [-0.5] * 768  # Distance > 1.0, far above 0.30 threshold

    with db_session_factory() as session:
        ep = Episode(
            source_path="episodes/guest/transcript.md",
            guest="Some Guest",
            title="General Episode",
            source_platform="youtube",
            source_sha256="s" * 64,
            body_sha256="b" * 64,
            raw_metadata={},
        )
        session.add(ep)
        session.flush()

        chunk = TranscriptChunk(
            episode_id=ep.id,
            chunk_index=0,
            chunk_text="Discussion about unrelated topics.",
            chunk_sha256="c" * 64,
            token_count=50,
            character_count=35,
            embedding=vec_chunk,
        )
        session.add(chunk)
        session.commit()

    mock_embedder = MagicMock(spec=OllamaEmbedder)
    mock_embedder.model = "nomic-embed-text:v1.5"
    mock_embedder.dimensions = 768
    mock_embedder.embed_query.return_value = vec_query

    mock_chat_client = MagicMock(spec=OllamaChatClient)
    mock_chat_client.generate_chat_response.return_value = {
        "content": "I could not find sufficient evidence in Lenny's Podcast transcripts to answer this question.",
        "model": "qwen3.5:9b",
    }

    settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        retrieval_max_cosine_distance=0.30,
        retrieval_top_k=2,
    )

    rag = RAGService(
        settings=settings,
        session_factory=db_session_factory,
        embedder=mock_embedder,
        chat_client=mock_chat_client,
    )

    res = rag.answer_question("quantum error correction in superconducting qubits")
    assert res.relevant_count == 0
    assert res.sources == []  # Crucial: unsupported questions must NOT return spurious sources
    assert "evidence" in res.content.lower()

