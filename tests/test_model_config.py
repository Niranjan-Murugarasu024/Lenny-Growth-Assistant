from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import status
import pytest

from backend.app.api.deps import get_app_settings, get_chat_provider_dep
from backend.app.api.main import app
from backend.app.config import Settings
from backend.app.rag.provider_base import ChatProvider, ProviderConnectionError
from backend.app.rag.service import RAGResponse, RAGService
from backend.app.retrieval.search import SearchResult


def test_get_model_config_endpoint(api_client) -> None:
    resp = api_client.get("/api/v1/config/models")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert "active_provider" in data
    assert "active_model" in data
    assert "displayed_label" in data
    assert "models" in data
    assert len(data["models"]) >= 2
    for m in data["models"]:
        assert "id" in m
        assert "provider" in m
        assert "model" in m
        assert "label" in m
        assert "status" in m
        assert "is_active" in m


def test_switch_model_to_ollama(api_client) -> None:
    resp = api_client.post(
        "/api/v1/config/models/switch",
        json={"provider": "ollama", "model": "qwen2.5:1.5b"},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["active_provider"] == "ollama"
    assert data["active_model"] == "qwen2.5:1.5b"
    assert "qwen2.5:1.5b" in data["displayed_label"]


def test_switch_model_litellm_without_credentials_rejected(api_client) -> None:
    # Ensure settings has no litellm_api_key
    test_settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        litellm_api_key="",
        litellm_api_base="",
    )
    app.dependency_overrides[get_app_settings] = lambda: test_settings
    try:
        resp = api_client.post(
            "/api/v1/config/models/switch",
            json={"provider": "litellm", "model": "openai/gpt-oss-20b"},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        err = resp.json()
        assert err["error"]["code"] == "MISSING_CLOUD_CREDENTIALS"
    finally:
        app.dependency_overrides.pop(get_app_settings, None)


def test_switch_model_litellm_with_credentials_accepted(api_client) -> None:
    test_settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        litellm_api_key="sk-test-key",
        litellm_model="openai/gpt-oss-20b",
    )
    app.dependency_overrides[get_app_settings] = lambda: test_settings
    try:
        resp = api_client.post(
            "/api/v1/config/models/switch",
            json={"provider": "litellm", "model": "openai/gpt-oss-20b"},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["active_provider"] == "litellm"
        assert data["active_model"] == "openai/gpt-oss-20b"
    finally:
        app.dependency_overrides.pop(get_app_settings, None)


def test_fallback_policy_disabled_raises_error(db_session_factory) -> None:
    settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        fallback_to_ollama=False,
    )
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.1] * 768

    mock_chat = MagicMock(spec=ChatProvider)
    mock_chat.name = "litellm"
    mock_chat.generate_chat_response.side_effect = ProviderConnectionError("Cloud down")

    rag = RAGService(
        settings=settings,
        session_factory=db_session_factory,
        embedder=mock_embedder,
        chat_client=mock_chat,
    )
    with patch("backend.app.rag.service.search_similar_chunks", return_value=[]):
        with pytest.raises(ProviderConnectionError):
            rag.answer_question("test question")


def test_fallback_policy_enabled_executes_fallback(db_session_factory) -> None:
    settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        fallback_to_ollama=True,
    )
    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.1] * 768

    mock_chat = MagicMock(spec=ChatProvider)
    mock_chat.name = "litellm"
    mock_chat.generate_chat_response.side_effect = ProviderConnectionError("Cloud down")

    mock_fallback_chat = MagicMock(spec=ChatProvider)
    mock_fallback_chat.name = "ollama"
    mock_fallback_chat.generate_chat_response.return_value = {
        "content": "Answer from local Ollama fallback.",
        "model": "qwen2.5:1.5b",
    }

    rag = RAGService(
        settings=settings,
        session_factory=db_session_factory,
        embedder=mock_embedder,
        chat_client=mock_chat,
    )
    with patch("backend.app.rag.service.search_similar_chunks", return_value=[]), \
         patch("backend.app.rag.ollama_client.OllamaChatClient.generate_chat_response", return_value={"content": "Answer from local Ollama fallback.", "model": "qwen2.5:1.5b"}):
        res = rag.answer_question("test question")
        assert res.provider == "ollama (fallback)"
        assert res.model == "qwen2.5:1.5b"
        assert "fallback" in res.content
