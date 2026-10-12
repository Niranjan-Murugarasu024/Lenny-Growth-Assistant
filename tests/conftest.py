from __future__ import annotations

import os
from collections.abc import Generator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.database import Base, create_db_engine, create_session_factory
from backend.app.models import (
    ChatMessage,
    ChatSession,
    Episode,
    IngestionRun,
    TranscriptChunk,
    WritingArtifact,
    WritingArtifactVersion,
    WritingJob,
)



def get_test_settings() -> Settings:
    """Return Settings configured to connect to the dedicated test database."""
    base_settings = get_settings()
    test_db_url = os.environ.get("TEST_DATABASE_URL")
    if not test_db_url:
        # Derive test database url by targeting lenny_growth_test
        test_db_url = base_settings.database_url.replace("/lenny_growth", "/lenny_growth_test")
    return Settings(
        database_url=test_db_url,
        embedding_model=base_settings.embedding_model,
        embedding_dimensions=base_settings.embedding_dimensions,
        chunk_target_tokens=base_settings.chunk_target_tokens,
        chunk_overlap_tokens=base_settings.chunk_overlap_tokens,
        embed_batch_size=base_settings.embed_batch_size,
        ollama_base_url=base_settings.ollama_base_url,
        chat_provider=base_settings.chat_provider,
        ollama_chat_model=base_settings.ollama_chat_model,
        chat_timeout_seconds=base_settings.chat_timeout_seconds,
        retrieval_top_k=base_settings.retrieval_top_k,
        retrieval_max_cosine_distance=base_settings.retrieval_max_cosine_distance,
        chat_max_history_messages=base_settings.chat_max_history_messages,
    )


@pytest.fixture(scope="session")
def test_engine():
    """Session-scoped engine bound strictly to the dedicated test database."""
    ts = get_test_settings()
    engine = create_db_engine(settings=ts)

    # Ensure vector extension and tables exist on test database
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(engine)

    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def test_db_session_factory(test_engine) -> sessionmaker[Session]:
    """Session-scoped sessionmaker bound strictly to the dedicated test database."""
    return create_session_factory(engine=test_engine)


@pytest.fixture
def db_session_factory(test_db_session_factory) -> Generator[sessionmaker[Session], None, None]:
    """
    Test-scoped fixture that provides a session factory pointing to the test database
    and automatically cleans up test records afterwards to ensure strict isolation between tests.
    """
    yield test_db_session_factory

    # Clean up test database records after each test
    with test_db_session_factory() as session:
        session.query(WritingJob).delete()
        session.query(WritingArtifactVersion).delete()
        session.query(WritingArtifact).delete()
        session.query(ChatMessage).delete()
        session.query(ChatSession).delete()
        session.query(TranscriptChunk).delete()
        session.query(Episode).delete()
        session.query(IngestionRun).delete()
        session.commit()



@pytest.fixture
def api_client(db_session_factory) -> Generator[Any, None, None]:
    """TestClient wired strictly to the test database lenny_growth_test."""
    from fastapi.testclient import TestClient
    from backend.app.api.deps import get_app_settings, get_db, get_session_factory
    from backend.app.api.main import app

    ts = get_test_settings()

    app.dependency_overrides[get_app_settings] = lambda: ts
    app.dependency_overrides[get_session_factory] = lambda: db_session_factory

    def _override_db():
        with db_session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _isolate_active_settings_between_tests():
    """Ensure global active settings are always reset between tests."""
    from backend.app.config import reset_active_settings

    reset_active_settings()
    yield
    reset_active_settings()

