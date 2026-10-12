from __future__ import annotations

from unittest.mock import MagicMock
from fastapi import status
import pytest

from backend.app.api.deps import get_app_settings
from backend.app.api.main import app
from backend.app.api.routes.internal import get_embedder
from backend.app.config import load_settings
from backend.app.models import Episode, TranscriptChunk
from backend.app.retrieval.search import SearchResult


def test_internal_endpoints_auth_required(api_client) -> None:
    # Missing token -> 401
    resp1 = api_client.post("/internal/v1/transcripts/search", json={"query": "test"})
    assert resp1.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp1.json()["error"]["code"] == "UNAUTHORIZED_INTERNAL_ACCESS"

    # Wrong token -> 401
    resp2 = api_client.post(
        "/internal/v1/transcripts/search",
        json={"query": "test"},
        headers={"X-Internal-Token": "wrong-token"},
    )
    assert resp2.status_code == status.HTTP_401_UNAUTHORIZED


def test_internal_search_success_and_filtering(api_client, monkeypatch) -> None:
    headers = {"X-Internal-Token": "lenny-agent-internal-secret-token"}

    mock_search = MagicMock()
    mock_search.return_value = [
        SearchResult(
            chunk_id=101,
            chunk_index=0,
            chunk_text="Finding product market fit requires talking to customers.",
            cosine_distance=0.15,
            guest="Brian Chesky",
            title="Building Airbnb",
            source_path="airbnb.txt",
            speaker="Brian Chesky",
            start_time_seconds=65.0,
            timestamp="00:01:05",
            embedding_model="nomic-embed-text:v1.5",
        ),
        SearchResult(
            chunk_id=102,
            chunk_index=1,
            chunk_text="Irrelevant discussion about weather.",
            cosine_distance=0.45,
            guest="Brian Chesky",
            title="Building Airbnb",
            source_path="airbnb.txt",
            speaker="Brian Chesky",
            start_time_seconds=120.0,
            timestamp="00:02:00",
            embedding_model="nomic-embed-text:v1.5",
        ),
    ]

    monkeypatch.setattr(
        "backend.app.api.routes.internal.search_similar_chunks",
        mock_search,
    )

    # Search with max_distance = 0.30 -> only chunk 101 should be returned
    resp = api_client.post(
        "/internal/v1/transcripts/search",
        json={"query": "product market fit", "top_k": 5, "max_distance": 0.30},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["query"] == "product market fit"
    assert data["count"] == 1
    assert data["chunks"][0]["chunk_id"] == 101
    assert data["chunks"][0]["cosine_distance"] == 0.15
    assert data["chunks"][0]["timestamp"] == "00:01:05"


def test_internal_context_retrieval(api_client, db_session_factory) -> None:
    # Insert test episode with 3 chunks
    with db_session_factory() as test_db:
        ep = Episode(
            source_path="test_internal/sample.txt",
            guest="Shreyas Doshi",
            title="Product Leadership",
            source_sha256="aabbcc1122334455",
            body_sha256="ddeeff1122334455",
        )
        test_db.add(ep)
        test_db.commit()
        test_db.refresh(ep)
        ep_id = ep.id

        c0 = TranscriptChunk(
            episode_id=ep_id,
            chunk_index=0,
            chunk_text="Before chunk context.",
            chunk_sha256="chunk0hash",
            token_count=10,
            character_count=21,
            speaker="Lenny",
            start_time_seconds=0.0,
        )
        c1 = TranscriptChunk(
            episode_id=ep_id,
            chunk_index=1,
            chunk_text="Target chunk text.",
            chunk_sha256="chunk1hash",
            token_count=10,
            character_count=18,
            speaker="Shreyas",
            start_time_seconds=60.0,
        )
        c2 = TranscriptChunk(
            episode_id=ep_id,
            chunk_index=2,
            chunk_text="After chunk context.",
            chunk_sha256="chunk2hash",
            token_count=10,
            character_count=20,
            speaker="Shreyas",
            start_time_seconds=120.0,
        )
        test_db.add_all([c0, c1, c2])
        test_db.commit()
        test_db.refresh(c1)
        c1_id = c1.id

    headers = {"Authorization": "Bearer lenny-agent-internal-secret-token"}

    # Request context around c1 with before=1, after=1
    resp = api_client.post(
        "/internal/v1/transcripts/context",
        json={"chunk_id": c1_id, "before": 1, "after": 1},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["target_chunk_id"] == c1_id
    assert data["episode_id"] == ep_id
    assert data["count"] == 3
    indices = [c["chunk_index"] for c in data["chunks"]]
    assert indices == [0, 1, 2]


def test_internal_context_not_found(api_client) -> None:
    headers = {"X-Internal-Token": "lenny-agent-internal-secret-token"}
    resp = api_client.post(
        "/internal/v1/transcripts/context",
        json={"chunk_id": 9999999, "before": 1, "after": 1},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["error"]["code"] == "CHUNK_NOT_FOUND"
