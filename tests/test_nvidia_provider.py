from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from backend.app.config import Settings
from backend.app.rag.nvidia_client import NvidiaChatClient
from backend.app.rag.provider_base import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
import openai


def test_nvidia_client_init_defaults() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        nvidia_base_url="https://integrate.api.nvidia.com/v1",
        nvidia_model="openai/gpt-oss-20b",
        nvidia_api_key="nvapi-test-secret-123",
        nvidia_timeout_seconds=60.0,
    )
    client = NvidiaChatClient(settings=settings)
    assert client.name == "nvidia"
    assert client.base_url == "https://integrate.api.nvidia.com/v1"
    assert client.model == "openai/gpt-oss-20b"
    assert client.api_key == "nvapi-test-secret-123"
    assert client.timeout_seconds == 60.0


def test_nvidia_client_health_check_unconfigured() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        nvidia_api_key="",
    )
    client = NvidiaChatClient(settings=settings)
    health = client.check_health()
    assert health["configured"] is False
    assert health["status"] == "not_configured"
    assert "NVIDIA_API_KEY is not configured" in health["error"]


def test_nvidia_client_health_check_configured() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        nvidia_api_key="nvapi-some-key",
    )
    client = NvidiaChatClient(settings=settings)
    health = client.check_health()
    assert health["configured"] is True
    assert health["status"] == "configured"
    assert health["error"] is None


def test_nvidia_client_test_connection_success() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        nvidia_api_key="nvapi-test-key",
    )
    client = NvidiaChatClient(settings=settings)

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content="Hi"))
    ]

    with patch.object(client.client.chat.completions, "create", return_value=mock_response):
        res = client.test_connection()
        assert res["connected"] is True
        assert res["status"] == "connected"
        assert "successfully connected" in res["message"].lower()
        assert res["elapsed_seconds"] >= 0


def test_nvidia_client_test_connection_auth_failure() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        nvidia_api_key="nvapi-bad-key",
    )
    client = NvidiaChatClient(settings=settings)

    mock_err_resp = MagicMock(status_code=401, headers={})
    auth_err = openai.AuthenticationError(
        message="Invalid API Key",
        response=mock_err_resp,
        body={"error": {"message": "Invalid API Key"}},
    )

    with patch.object(client.client.chat.completions, "create", side_effect=auth_err):
        res = client.test_connection()
        assert res["connected"] is False
        assert res["status"] == "unavailable"
        assert "authentication failed" in res["message"].lower()


def test_nvidia_client_generate_response_success() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        nvidia_api_key="nvapi-test-key",
    )
    client = NvidiaChatClient(settings=settings)

    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message = MagicMock(content="Lenny says product market fit is when retention curves flatten.")
    mock_choice.finish_reason = "stop"
    mock_response.choices = [mock_choice]
    mock_response.model = "openai/gpt-oss-20b"
    mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=30, total_tokens=130)

    with patch.object(client.client.chat.completions, "create", return_value=mock_response):
        res = client.generate_chat_response([{"role": "user", "content": "What is PMF?"}])
        assert "retention curves flatten" in res["content"]
        assert res["model"] == "openai/gpt-oss-20b"
        assert res["usage"]["total_tokens"] == 130


def test_nvidia_client_rate_limit_mapping() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        nvidia_api_key="nvapi-test-key",
    )
    client = NvidiaChatClient(settings=settings)

    mock_err_resp = MagicMock(status_code=429, headers={})
    rl_err = openai.RateLimitError(
        message="Rate limit exceeded",
        response=mock_err_resp,
        body={"error": {"message": "Rate limit exceeded"}},
    )

    with patch.object(client.client.chat.completions, "create", side_effect=rl_err):
        with pytest.raises(ProviderRateLimitError) as exc_info:
            client.generate_chat_response([{"role": "user", "content": "Hi"}])
        assert "rate limit or quota exceeded" in str(exc_info.value).lower()


def test_nvidia_client_timeout_mapping() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        nvidia_api_key="nvapi-test-key",
    )
    client = NvidiaChatClient(settings=settings)

    req = MagicMock()
    to_err = openai.APITimeoutError(request=req)

    with patch.object(client.client.chat.completions, "create", side_effect=to_err):
        with pytest.raises(ProviderTimeoutError) as exc_info:
            client.generate_chat_response([{"role": "user", "content": "Hi"}])
        assert "timed out" in str(exc_info.value).lower()


def test_nvidia_client_no_key_exposure_in_repr() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        nvidia_api_key="super-secret-key-12345",
    )
    client = NvidiaChatClient(settings=settings)
    r = repr(client)
    assert "super-secret-key-12345" not in r
    assert "configured=True" in r
