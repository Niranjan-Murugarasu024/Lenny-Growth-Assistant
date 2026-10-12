from __future__ import annotations

from unittest.mock import MagicMock, patch
from fastapi import status
import pytest

from backend.app.api.deps import get_app_settings
from backend.app.api.main import app
from backend.app.config import Settings


def test_get_llm_settings(api_client) -> None:
    resp = api_client.get("/api/v1/settings/llm")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert "active_provider" in data
    assert "active_model" in data
    assert "active_category" in data
    assert "providers" in data
    assert len(data["providers"]) == 2

    provider_ids = [p["id"] for p in data["providers"]]
    assert "ollama" in provider_ids
    assert "nvidia" in provider_ids

    ollama_info = next(p for p in data["providers"] if p["id"] == "ollama")
    assert ollama_info["name"] == "Ollama"
    assert ollama_info["model"] == "qwen2.5:1.5b"
    assert ollama_info["category"] == "local"

    nvidia_info = next(p for p in data["providers"] if p["id"] == "nvidia")
    assert nvidia_info["name"] == "NVIDIA NIM"
    assert nvidia_info["model"] == "openai/gpt-oss-20b"
    assert nvidia_info["category"] == "cloud"


def test_update_llm_settings_to_ollama(api_client) -> None:
    resp = api_client.put(
        "/api/v1/settings/llm",
        json={"provider": "ollama", "model": "qwen2.5:1.5b"},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["active_provider"] == "ollama"
    assert data["active_model"] == "qwen2.5:1.5b"
    assert data["active_category"] == "local"


def test_update_llm_settings_to_nvidia_missing_key_rejected(api_client) -> None:
    test_settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        nvidia_api_key="",
    )
    app.dependency_overrides[get_app_settings] = lambda: test_settings
    try:
        resp = api_client.put(
            "/api/v1/settings/llm",
            json={"provider": "nvidia"},
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        err = resp.json()
        assert "NVIDIA_API_KEY is not configured" in err["error"]["message"]
    finally:
        app.dependency_overrides.pop(get_app_settings, None)


def test_update_llm_settings_to_nvidia_with_key_succeeds(api_client) -> None:
    test_settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        nvidia_api_key="nvapi-valid-test-key",
        nvidia_model="openai/gpt-oss-20b",
    )
    app.dependency_overrides[get_app_settings] = lambda: test_settings
    try:
        resp = api_client.put(
            "/api/v1/settings/llm",
            json={"provider": "nvidia"},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["active_provider"] == "nvidia"
        assert data["active_model"] == "openai/gpt-oss-20b"
        assert data["active_category"] == "cloud"
    finally:
        app.dependency_overrides.pop(get_app_settings, None)
        # Restore to ollama for subsequent tests
        api_client.put("/api/v1/settings/llm", json={"provider": "ollama"})


def test_update_llm_settings_invalid_provider_rejected(api_client) -> None:
    resp = api_client.put(
        "/api/v1/settings/llm",
        json={"provider": "unknown_ai_provider"},
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    err = resp.json()
    assert "unsupported provider" in err["error"]["message"].lower()


def test_test_llm_connection_ollama(api_client) -> None:
    resp = api_client.post(
        "/api/v1/settings/llm/test",
        json={"provider": "ollama"},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["provider"] == "ollama"
    assert data["model"] == "qwen2.5:1.5b"
    assert "connected" in data
    assert "status" in data


def test_test_llm_connection_nvidia_unconfigured(api_client) -> None:
    test_settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        nvidia_api_key="",
    )
    app.dependency_overrides[get_app_settings] = lambda: test_settings
    try:
        resp = api_client.post(
            "/api/v1/settings/llm/test",
            json={"provider": "nvidia"},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["provider"] == "nvidia"
        assert data["connected"] is False
        assert data["status"] == "not_configured"
        assert "NVIDIA_API_KEY is not configured" in data["message"]
    finally:
        app.dependency_overrides.pop(get_app_settings, None)


def test_test_llm_connection_nvidia_live_mocked(api_client) -> None:
    test_settings = Settings(
        database_url="postgresql+psycopg://dummy/test",
        nvidia_api_key="nvapi-test-key",
    )
    app.dependency_overrides[get_app_settings] = lambda: test_settings
    try:
        with patch("backend.app.rag.nvidia_client.NvidiaChatClient.test_connection") as mock_test:
            mock_test.return_value = {
                "connected": True,
                "status": "connected",
                "elapsed_seconds": 0.42,
                "message": "NVIDIA NIM model 'openai/gpt-oss-20b' successfully connected.",
            }
            resp = api_client.post(
                "/api/v1/settings/llm/test",
                json={"provider": "nvidia"},
            )
            assert resp.status_code == status.HTTP_200_OK
            data = resp.json()
            assert data["connected"] is True
            assert data["status"] == "connected"
            assert data["elapsed_seconds"] == 0.42
    finally:
        app.dependency_overrides.pop(get_app_settings, None)
