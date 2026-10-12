from __future__ import annotations

import pytest

from backend.app.config import Settings, load_settings


def test_settings_valid_configuration() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://lenny_app:secret123@127.0.0.1:5435/lenny_growth",
        embedding_model="nomic-embed-text:v1.5",
        embedding_dimensions=768,
    )
    assert settings.embedding_dimensions == 768
    assert settings.embedding_model == "nomic-embed-text:v1.5"
    assert "lenny_growth" in settings.database_url


def test_settings_normalizes_postgresql_scheme() -> None:
    settings = Settings(
        database_url="postgresql://lenny_app:secret123@127.0.0.1:5435/lenny_growth"
    )
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_settings_rejects_empty_database_url() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL must be set and non-empty"):
        Settings(database_url="")

    with pytest.raises(ValueError, match="DATABASE_URL must be set and non-empty"):
        Settings(database_url="   ")


def test_settings_rejects_invalid_scheme() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL must use 'postgresql\\+psycopg://'"):
        Settings(database_url="mysql://user:pass@localhost/db")


def test_settings_rejects_non_positive_embedding_dimensions() -> None:
    with pytest.raises(ValueError, match="EMBEDDING_DIMENSIONS must be positive"):
        Settings(
            database_url="postgresql+psycopg://user:pass@localhost/db",
            embedding_dimensions=0,
        )

    with pytest.raises(ValueError, match="EMBEDDING_DIMENSIONS must be positive"):
        Settings(
            database_url="postgresql+psycopg://user:pass@localhost/db",
            embedding_dimensions=-10,
        )


def test_settings_masks_password_in_repr_and_sanitized_url() -> None:
    raw_password = "super_secret_password_99"
    settings = Settings(
        database_url=f"postgresql+psycopg://lenny_app:{raw_password}@127.0.0.1:5435/lenny_growth"
    )

    sanitized = settings.sanitized_database_url()
    assert raw_password not in sanitized
    assert ":***@" in sanitized

    repr_str = repr(settings)
    assert raw_password not in repr_str
    assert ":***@" in repr_str


def test_load_settings_with_overrides() -> None:
    settings = load_settings(
        database_url="postgresql+psycopg://custom_user:custom_pass@localhost:5432/custom_db",
        embedding_model="custom-model",
        embedding_dimensions=1024,
        chat_orchestrator="pi",
        agent_internal_token="secret-xyz",
    )
    assert settings.embedding_model == "custom-model"
    assert settings.embedding_dimensions == 1024
    assert "custom_db" in settings.database_url
    assert settings.chat_orchestrator == "pi"
    assert settings.agent_internal_token == "secret-xyz"


def test_settings_rejects_invalid_orchestrator() -> None:
    with pytest.raises(ValueError, match="CHAT_ORCHESTRATOR must be 'rag' or 'pi'"):
        Settings(
            database_url="postgresql+psycopg://user:pass@localhost/db",
            chat_orchestrator="invalid_orchestrator",
        )


def test_provider_switching_configuration() -> None:
    from backend.app.rag.factory import get_chat_provider
    from backend.app.rag.ollama_client import OllamaChatClient
    from backend.app.rag.litellm_client import LiteLLMChatClient

    # Local Ollama with Qwen 2.5
    s_local = load_settings(
        database_url="postgresql+psycopg://user:pass@localhost/db",
        chat_provider="ollama",
        ollama_chat_model="qwen2.5:1.5b",
    )
    assert s_local.chat_provider == "ollama"
    assert s_local.ollama_chat_model == "qwen2.5:1.5b"
    prov_local = get_chat_provider(s_local)
    assert isinstance(prov_local, OllamaChatClient)
    assert prov_local.default_model == "qwen2.5:1.5b"

    # Cloud LiteLLM
    s_cloud = load_settings(
        database_url="postgresql+psycopg://user:pass@localhost/db",
        chat_provider="litellm",
        litellm_model="openai/gpt-4o-mini",
        litellm_api_key="sk-test-key",
    )
    assert s_cloud.chat_provider == "litellm"
    assert s_cloud.litellm_model == "openai/gpt-4o-mini"
    prov_cloud = get_chat_provider(s_cloud)
    assert isinstance(prov_cloud, LiteLLMChatClient)
    assert prov_cloud.model == "openai/gpt-4o-mini"

