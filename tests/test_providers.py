from __future__ import annotations

from unittest.mock import MagicMock, patch
import uuid

from fastapi import status
import pytest

from backend.app.api.deps import get_chat_provider_dep, get_embedder_dep
from backend.app.api.main import app
from backend.app.config import Settings
from backend.app.rag.factory import get_chat_provider
from backend.app.rag.litellm_client import LiteLLMChatClient
from backend.app.rag.ollama_client import OllamaChatClient
from backend.app.rag.provider_base import (
    ChatProvider,
    ProviderAuthenticationError,
    ProviderConfigError,
    ProviderConnectionError,
    ProviderModelNotFoundError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from backend.app.rag.service import RAGService
from backend.app.retrieval.search import SearchResult


# ============================================================================
# 1. Factory & Configuration Tests
# ============================================================================

def test_default_provider_is_ollama() -> None:
    settings = Settings(database_url="postgresql+psycopg://dummy/test")
    assert settings.chat_provider == "ollama"

    provider = get_chat_provider(settings)
    assert isinstance(provider, OllamaChatClient)
    assert provider.name == "ollama"
    assert provider.model_name in ("qwen2.5:1.5b", "qwen3.5:9b")


def test_factory_selects_correct_provider() -> None:
    # Ollama
    s_ollama = Settings(database_url="postgresql+psycopg://dummy/test", chat_provider="ollama")
    p_ollama = get_chat_provider(s_ollama)
    assert isinstance(p_ollama, OllamaChatClient)

    # LiteLLM
    s_litellm = Settings(
        database_url="postgresql+psycopg://dummy/test",
        chat_provider="litellm",
        litellm_model="openai/gpt-4o",
        litellm_api_key="sk-test",
    )
    p_litellm = get_chat_provider(s_litellm)
    assert isinstance(p_litellm, LiteLLMChatClient)
    assert p_litellm.name == "litellm"
    assert p_litellm.model_name == "openai/gpt-4o"

    # Cloud alias
    s_cloud = Settings(
        database_url="postgresql+psycopg://dummy/test",
        chat_provider="cloud",
        litellm_model="anthropic/claude-3-5-sonnet",
        litellm_api_key="sk-ant",
    )
    p_cloud = get_chat_provider(s_cloud)
    assert isinstance(p_cloud, LiteLLMChatClient)

    # Unsupported provider raises ProviderConfigError
    s_bad = Settings(database_url="postgresql+psycopg://dummy/test", chat_provider="unknown_provider")
    with pytest.raises(ProviderConfigError) as exc_info:
        get_chat_provider(s_bad)
    assert "Unsupported chat provider" in str(exc_info.value)


def test_settings_masks_litellm_api_key() -> None:
    secret = "sk-proj-supersecretkey12345678"
    settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        litellm_api_key=secret,
        litellm_model="openai/gpt-4o",
    )
    # The raw secret must not appear in string representation
    repr_str = repr(settings)
    assert secret not in repr_str
    assert "***" in repr_str

    sanitized = settings.sanitized_litellm_api_key()
    assert sanitized is not None
    assert secret not in sanitized
    assert "..." in sanitized


# ============================================================================
# 2. LiteLLM Provider Unit Tests
# ============================================================================

def test_litellm_missing_model_raises_config_error() -> None:
    client = LiteLLMChatClient(model="", api_key="sk-test")
    # Health check
    health = client.check_health()
    assert health["available"] is False
    assert health["status"] == "misconfigured"
    assert "LITELLM_MODEL is not configured" in health["error"]

    # Generation attempt
    with pytest.raises(ProviderConfigError) as exc:
        client.generate_chat_response([{"role": "user", "content": "hello"}])
    assert "LITELLM_MODEL is not configured" in str(exc.value)


def test_litellm_missing_credentials_raises_config_error() -> None:
    client = LiteLLMChatClient(model="openai/gpt-4o", api_key="", api_base="")
    # Health check
    health = client.check_health()
    assert health["available"] is False
    assert health["status"] == "misconfigured"
    assert "LITELLM_API_KEY is missing" in health["error"]

    # Generation attempt
    with pytest.raises(ProviderConfigError) as exc:
        client.generate_chat_response([{"role": "user", "content": "hello"}])
    assert "LITELLM_API_KEY is not configured" in str(exc.value)


def test_litellm_health_check_configured_without_billable_call() -> None:
    client = LiteLLMChatClient(model="openai/gpt-4o", api_key="sk-validkey")
    health = client.check_health()
    assert health["available"] is True
    assert health["status"] == "configured"
    assert health["model"] == "openai/gpt-4o"
    assert health["model_available"] is True


def test_litellm_normalizes_response_correctly() -> None:
    client = LiteLLMChatClient(model="openai/gpt-4o", api_key="sk-test")

    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "   Grounded answer with evidence.   "
    mock_resp.choices = [mock_choice]
    mock_resp.model = "gpt-4o-2024-08-06"
    mock_resp.usage.prompt_tokens = 15
    mock_resp.usage.completion_tokens = 25
    mock_resp.usage.total_tokens = 40

    with patch("litellm.completion", return_value=mock_resp):
        res = client.generate_chat_response([{"role": "user", "content": "test"}])

    assert res["content"] == "Grounded answer with evidence."
    assert res["model"] == "gpt-4o-2024-08-06"
    assert res["usage"]["total_tokens"] == 40


def test_litellm_empty_response_raises_response_error() -> None:
    client = LiteLLMChatClient(model="openai/gpt-4o", api_key="sk-test")

    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "   "
    mock_resp.choices = [mock_choice]

    with patch("litellm.completion", return_value=mock_resp):
        with pytest.raises(ProviderResponseError) as exc:
            client.generate_chat_response([{"role": "user", "content": "test"}])
    assert "empty message content" in str(exc.value)


def test_litellm_timeout_raises_provider_timeout() -> None:
    import litellm.exceptions

    client = LiteLLMChatClient(model="openai/gpt-4o", api_key="sk-test", timeout_seconds=10.0)

    with patch(
        "litellm.completion",
        side_effect=litellm.exceptions.Timeout(
            message="Request timed out",
            model="openai/gpt-4o",
            llm_provider="openai",
        ),
    ):
        with pytest.raises(ProviderTimeoutError) as exc:
            client.generate_chat_response([{"role": "user", "content": "test"}])
    assert "timed out after 10.0s" in str(exc.value)


def test_litellm_auth_error_does_not_leak_key() -> None:
    import litellm.exceptions

    secret_key = "sk-supersecretkey123"
    client = LiteLLMChatClient(model="openai/gpt-4o", api_key=secret_key)

    with patch(
        "litellm.completion",
        side_effect=litellm.exceptions.AuthenticationError(
            message=f"Invalid API key: {secret_key}",
            model="openai/gpt-4o",
            llm_provider="openai",
        ),
    ):
        with pytest.raises(ProviderAuthenticationError) as exc:
            client.generate_chat_response([{"role": "user", "content": "test"}])

    # The exception message presented upward must not leak the raw secret
    assert secret_key not in str(exc.value)
    assert "Authentication failed" in str(exc.value)


def test_litellm_rate_limit_error_raises_rate_limit() -> None:
    import litellm.exceptions

    client = LiteLLMChatClient(model="openai/gpt-4o", api_key="sk-test")

    with patch(
        "litellm.completion",
        side_effect=litellm.exceptions.RateLimitError(
            message="Rate limit exceeded",
            model="openai/gpt-4o",
            llm_provider="openai",
        ),
    ):
        with pytest.raises(ProviderRateLimitError) as exc:
            client.generate_chat_response([{"role": "user", "content": "test"}])
    assert "Rate limit or quota exceeded" in str(exc.value)


def test_litellm_connection_error_raises_connection() -> None:
    import litellm.exceptions

    client = LiteLLMChatClient(model="openai/gpt-4o", api_key="sk-test")

    with patch(
        "litellm.completion",
        side_effect=litellm.exceptions.APIConnectionError(
            message="Connection failed",
            model="openai/gpt-4o",
            llm_provider="openai",
        ),
    ):
        with pytest.raises(ProviderConnectionError) as exc:
            client.generate_chat_response([{"role": "user", "content": "test"}])
    assert "Failed to connect" in str(exc.value)


# ============================================================================
# 3. API Integration & Error Translation Tests
# ============================================================================

def _make_mock_chunks() -> list[SearchResult]:
    """Provide deterministic, valid transcript chunk records for isolated provider tests."""
    return [
        SearchResult(
            chunk_id=101,
            chunk_index=0,
            chunk_text="Product strategy is the connective tissue between company vision and roadmap execution.",
            cosine_distance=0.15,
            guest="Lenny Rachitsky",
            title="Product Strategy Fundamentals",
            source_path="transcripts/lenny_product_strategy.json",
            speaker="Lenny Rachitsky",
            start_time_seconds=120.0,
            timestamp="00:02:00",
            embedding_model="nomic-embed-text:v1.5",
            youtube_video_id="abc123xyz",
        )
    ]


def test_api_chat_with_litellm_provider_success(api_client) -> None:
    session_resp = api_client.post("/api/v1/sessions", json={"title": "Cloud RAG"})
    session_id = session_resp.json()["id"]

    mock_provider = MagicMock(spec=ChatProvider)
    mock_provider.name = "litellm"
    mock_provider.model_name = "openai/gpt-4o"
    mock_provider.generate_chat_response.return_value = {
        "content": "According to Lenny [Source 1], product strategy is key.",
        "model": "openai/gpt-4o",
    }

    mock_chunks = _make_mock_chunks()
    app.dependency_overrides[get_chat_provider_dep] = lambda: mock_provider
    try:
        with patch("backend.app.rag.service.search_similar_chunks", return_value=mock_chunks) as mock_search:
            with patch("httpx.Client.post", side_effect=AssertionError("Isolated test made unexpected external HTTP POST call!")) as mock_http:
                resp = api_client.post(
                    f"/api/v1/sessions/{session_id}/messages",
                    json={"message": "What is product strategy?"},
                )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["role"] == "assistant"
        assert data["provider"] == "litellm"
        assert data["model"] == "openai/gpt-4o"
        assert "product strategy" in data["content"]
        assert len(data["sources"]) == 1
        assert data["sources"][0]["chunk_id"] == 101
        assert data["sources"][0]["guest"] == "Lenny Rachitsky"
        assert mock_http.call_count == 0
        assert mock_search.called
    finally:
        app.dependency_overrides.pop(get_chat_provider_dep, None)


def test_api_chat_with_litellm_auth_failure_returns_502(api_client) -> None:
    session_resp = api_client.post("/api/v1/sessions", json={"title": "Cloud Auth Failure"})
    session_id = session_resp.json()["id"]

    mock_provider = MagicMock(spec=ChatProvider)
    mock_provider.name = "litellm"
    mock_provider.model_name = "openai/gpt-4o"
    mock_provider.generate_chat_response.side_effect = ProviderAuthenticationError(
        "Authentication failed for cloud provider model 'openai/gpt-4o'."
    )

    mock_chunks = _make_mock_chunks()
    app.dependency_overrides[get_chat_provider_dep] = lambda: mock_provider
    try:
        with patch("backend.app.rag.service.search_similar_chunks", return_value=mock_chunks):
            with patch("httpx.Client.post", side_effect=AssertionError("Isolated test made unexpected external HTTP POST call!")) as mock_http:
                resp = api_client.post(
                    f"/api/v1/sessions/{session_id}/messages",
                    json={"message": "What is product strategy?"},
                )
        assert resp.status_code == status.HTTP_502_BAD_GATEWAY
        err = resp.json()
        assert err["error"]["code"] == "LLM_AUTHENTICATION_ERROR"
        assert "Authentication failed" in err["error"]["message"]
        assert "request_id" in err["error"]
        assert mock_http.call_count == 0
    finally:
        app.dependency_overrides.pop(get_chat_provider_dep, None)


def test_api_chat_with_litellm_rate_limit_returns_429(api_client) -> None:
    session_resp = api_client.post("/api/v1/sessions", json={"title": "Cloud Rate Limit"})
    session_id = session_resp.json()["id"]

    mock_provider = MagicMock(spec=ChatProvider)
    mock_provider.name = "litellm"
    mock_provider.model_name = "openai/gpt-4o"
    mock_provider.generate_chat_response.side_effect = ProviderRateLimitError(
        "Rate limit or quota exceeded for cloud model 'openai/gpt-4o'."
    )

    mock_chunks = _make_mock_chunks()
    app.dependency_overrides[get_chat_provider_dep] = lambda: mock_provider
    try:
        with patch("backend.app.rag.service.search_similar_chunks", return_value=mock_chunks):
            with patch("httpx.Client.post", side_effect=AssertionError("Isolated test made unexpected external HTTP POST call!")) as mock_http:
                resp = api_client.post(
                    f"/api/v1/sessions/{session_id}/messages",
                    json={"message": "What is product strategy?"},
                )
        assert resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        err = resp.json()
        assert err["error"]["code"] == "LLM_RATE_LIMIT_EXCEEDED"
        assert "rate limit" in err["error"]["message"].lower()
        assert mock_http.call_count == 0
    finally:
        app.dependency_overrides.pop(get_chat_provider_dep, None)


def test_mocked_provider_api_makes_no_network_calls_to_ollama(api_client) -> None:
    """Regression test ensuring mocked-provider API tests make zero network calls to Ollama."""
    session_resp = api_client.post("/api/v1/sessions", json={"title": "No Network Ollama Test"})
    session_id = session_resp.json()["id"]

    mock_provider = MagicMock(spec=ChatProvider)
    mock_provider.name = "litellm"
    mock_provider.model_name = "openai/gpt-4o"
    mock_provider.generate_chat_response.return_value = {
        "content": "Zero network calls made.",
        "model": "openai/gpt-4o",
    }

    mock_chunks = _make_mock_chunks()
    app.dependency_overrides[get_chat_provider_dep] = lambda: mock_provider
    try:
        with patch("backend.app.rag.service.search_similar_chunks", return_value=mock_chunks):
            with patch("httpx.Client.post", side_effect=AssertionError("Real network call to Ollama/external service detected!")) as mock_post, \
                 patch("httpx.Client.send", side_effect=AssertionError("Real network send detected!")) as mock_send:
                resp = api_client.post(
                    f"/api/v1/sessions/{session_id}/messages",
                    json={"message": "Is network isolated?"},
                )
            assert resp.status_code == status.HTTP_201_CREATED
            assert mock_post.call_count == 0
            assert mock_send.call_count == 0
    finally:
        app.dependency_overrides.pop(get_chat_provider_dep, None)


def test_api_health_ready_with_litellm_configured(api_client) -> None:
    mock_provider = MagicMock(spec=ChatProvider)
    mock_provider.name = "litellm"
    mock_provider.model_name = "openai/gpt-4o"
    mock_provider.check_health.return_value = {
        "available": True,
        "status": "configured",
        "model": "openai/gpt-4o",
        "model_available": True,
    }

    app.dependency_overrides[get_chat_provider_dep] = lambda: mock_provider
    try:
        resp = api_client.get("/health/ready")
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["status"] == "ready"
        assert data["inference"]["provider"] == "litellm"
        assert data["inference"]["status"] == "configured"
        assert data["inference"]["configured_model"] == "openai/gpt-4o"
        assert data["inference"]["model_available"] is True
    finally:
        app.dependency_overrides.pop(get_chat_provider_dep, None)
