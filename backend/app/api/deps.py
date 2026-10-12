from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.database import create_session_factory
from backend.app.ingestion.embedder import OllamaEmbedder
from backend.app.rag.factory import get_chat_provider
from backend.app.rag.ollama_client import OllamaChatClient
from backend.app.rag.provider_base import ChatProvider
from backend.app.rag.service import RAGService


def get_app_settings() -> Settings:
    """Dependency provider for cached application settings."""
    return get_settings()


def get_session_factory(
    settings: Annotated[Settings, Depends(get_app_settings)]
) -> sessionmaker[Session]:
    """Dependency provider for SQLAlchemy sessionmaker."""
    return create_session_factory(settings=settings)


def get_db(
    factory: Annotated[sessionmaker[Session], Depends(get_session_factory)]
) -> Generator[Session, None, None]:
    """Yield a database session and safely close it after request completion."""
    with factory() as session:
        yield session


def get_embedder_dep(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> OllamaEmbedder:
    """Dependency provider for OllamaEmbedder instance."""
    return OllamaEmbedder(
        base_url=settings.ollama_base_url,
        model=settings.embedding_model,
    )


def get_chat_provider_dep(
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Session, Depends(get_db)],
    ollama_client: Annotated[OllamaChatClient, Depends(get_ollama_client)],
) -> ChatProvider:
    """Dependency provider for the configured ChatProvider (Ollama or NVIDIA)."""
    import dataclasses
    from backend.app.database import get_db_setting

    active_prov = get_db_setting(db, "active_chat_provider", settings.chat_provider)
    if (active_prov or "ollama").lower().strip() == "ollama":
        return ollama_client

    active_model = get_db_setting(db, "active_chat_model", settings.nvidia_model or "openai/gpt-oss-20b")
    effective_settings = dataclasses.replace(
        settings,
        chat_provider=active_prov,
        nvidia_model=active_model,
    )
    return get_chat_provider(settings=effective_settings)


def get_ollama_client(
    settings: Annotated[Settings, Depends(get_app_settings)]
) -> OllamaChatClient:
    """Dependency provider for OllamaChatClient (preserved for backward compatibility)."""
    return OllamaChatClient(settings=settings)


def get_rag_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    provider: Annotated[ChatProvider, Depends(get_chat_provider_dep)],
    embedder: Annotated[OllamaEmbedder, Depends(get_embedder_dep)],
) -> RAGService:
    """Dependency provider for RAGService with configured ChatProvider and Embedder."""
    return RAGService(
        settings=settings,
        session_factory=factory,
        chat_client=provider,
        embedder=embedder,
    )


def verify_internal_token(
    settings: Annotated[Settings, Depends(get_app_settings)],
    x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> None:
    """Verify shared secret token for internal microservice communication."""
    provided_token = x_internal_token
    if not provided_token and authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            provided_token = parts[1]
        elif len(parts) == 1:
            provided_token = parts[0]

    expected = settings.agent_internal_token.strip()
    if not provided_token or provided_token.strip() != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "UNAUTHORIZED_INTERNAL_ACCESS",
                "message": "Invalid or missing internal service authentication token.",
            },
        )


def get_pi_agent_client(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> PiAgentClient:
    """Dependency provider for PiAgentClient."""
    from backend.app.rag.pi_client import PiAgentClient

    return PiAgentClient(settings=settings)
