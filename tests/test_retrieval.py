from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from backend.app.ingestion.embedder import OllamaEmbedder
from backend.app.models import Episode, TranscriptChunk
from backend.app.retrieval.search import (
    format_seconds_to_timestamp,
    search_fulltext_chunks,
    search_hybrid_chunks,
    search_similar_chunks,
)



def _make_vector(dim: int = 768, val: float = 0.05) -> list[float]:
    return [val] * dim


def test_format_seconds_to_timestamp() -> None:
    assert format_seconds_to_timestamp(0.0) == "00:00:00"
    assert format_seconds_to_timestamp(81.0) == "00:01:21"
    assert format_seconds_to_timestamp(3665.0) == "01:01:05"
    assert format_seconds_to_timestamp(None) is None
    assert format_seconds_to_timestamp(-10.0) is None


def test_search_similar_chunks_empty_query(db_session_factory) -> None:
    results = search_similar_chunks("", session_factory=db_session_factory)
    assert results == []

    results_whitespace = search_similar_chunks("   ", session_factory=db_session_factory)
    assert results_whitespace == []


def test_search_similar_chunks_invalid_top_k(db_session_factory) -> None:
    with pytest.raises(ValueError, match="top_k must be a positive integer"):
        search_similar_chunks("test query", top_k=0, session_factory=db_session_factory)


def test_search_similar_chunks_query_vector_validation(db_session_factory) -> None:
    mock_embedder = MagicMock(spec=OllamaEmbedder)
    mock_embedder.model = "nomic-embed-text:v1.5"
    mock_embedder.dimensions = 768
    # Return vector with wrong dimension
    mock_embedder.embed_query.return_value = [0.1] * 512

    with pytest.raises(ValueError, match="dimension mismatch"):
        search_similar_chunks(
            "test query",
            session_factory=db_session_factory,
            embedder=mock_embedder,
        )


def test_search_similar_chunks_retrieval_and_ordering(db_session_factory) -> None:
    # Insert two test chunks with known vectors into test database
    vec_close = [0.5] * 768
    vec_far = [-0.5] * 768

    with db_session_factory() as session:
        ep = Episode(
            source_path="episodes/test-guest/transcript.md",
            guest="Test Speaker",
            title="Search Quality Episode",
            source_platform="youtube",
            source_sha256="1" * 64,
            body_sha256="2" * 64,
            raw_metadata={},
        )
        session.add(ep)
        session.flush()

        chunk_1 = TranscriptChunk(
            episode_id=ep.id,
            chunk_index=0,
            chunk_text="Highly relevant passage on growth loops.",
            chunk_sha256="a" * 64,
            token_count=100,
            character_count=40,
            speaker="Lenny",
            start_time_seconds=90.0,
            embedding=vec_close,
        )
        chunk_2 = TranscriptChunk(
            episode_id=ep.id,
            chunk_index=1,
            chunk_text="Opposite passage about unrelated topics.",
            chunk_sha256="b" * 64,
            token_count=100,
            character_count=41,
            speaker="Guest",
            start_time_seconds=180.0,
            embedding=vec_far,
        )
        session.add_all([chunk_1, chunk_2])
        session.commit()

    # Query vector close to vec_close
    query_vector = [0.5] * 768
    mock_embedder = MagicMock(spec=OllamaEmbedder)
    mock_embedder.model = "nomic-embed-text:v1.5"
    mock_embedder.dimensions = 768
    mock_embedder.embed_query.return_value = query_vector

    results = search_similar_chunks(
        query="growth loops",
        top_k=2,
        session_factory=db_session_factory,
        embedder=mock_embedder,
    )

    assert len(results) == 2
    mock_embedder.embed_query.assert_called_once_with("growth loops")

    # Closer vector should be ranked first
    assert results[0].chunk_text == "Highly relevant passage on growth loops."
    assert results[0].guest == "Test Speaker"
    assert results[0].title == "Search Quality Episode"
    assert results[0].timestamp == "00:01:30"
    assert results[0].start_time_seconds == 90.0
    assert results[0].cosine_distance <= results[1].cosine_distance


def test_deterministic_evaluation_supported_vs_unsupported_query(db_session_factory) -> None:
    """Test retrieval discrimination between supported topics and unsupported topics."""
    # Seed test database with a domain-specific transcript chunk
    with db_session_factory() as session:
        ep = Episode(
            source_path="episodes/andy-raskin/transcript.md",
            guest="Andy Raskin",
            title="The Greatest Sales Deck",
            source_platform="youtube",
            source_sha256="x" * 64,
            body_sha256="y" * 64,
            raw_metadata={},
        )
        session.add(ep)
        session.flush()

        chunk = TranscriptChunk(
            episode_id=ep.id,
            chunk_index=0,
            chunk_text="A strategic narrative starts with naming the old game and the new game.",
            chunk_sha256="c" * 64,
            token_count=80,
            character_count=73,
            speaker="Andy Raskin",
            start_time_seconds=30.0,
            embedding=[0.2] * 768,
        )
        session.add(chunk)
        session.commit()

    mock_embedder = MagicMock(spec=OllamaEmbedder)
    mock_embedder.model = "nomic-embed-text:v1.5"
    mock_embedder.dimensions = 768

    # Query 1: Topic with supported evidence
    mock_embedder.embed_query.return_value = [0.2] * 768
    results_supported = search_similar_chunks(
        "strategic narrative sales pitch",
        top_k=1,
        session_factory=db_session_factory,
        embedder=mock_embedder,
    )
    assert len(results_supported) == 1
    assert results_supported[0].guest == "Andy Raskin"
    assert results_supported[0].cosine_distance < 0.05

    # Query 2: Topic completely outside corpus domain (e.g. quantum physics)
    mock_embedder.embed_query.return_value = [-0.2] * 768
    results_unsupported = search_similar_chunks(
        "quantum entanglement photon teleportation",
        top_k=1,
        session_factory=db_session_factory,
        embedder=mock_embedder,
    )
    assert len(results_unsupported) == 1
    # Nearest neighbor still returned, but distance is high (near 2.0 for opposite vectors)
    assert results_unsupported[0].cosine_distance > 1.5


def test_search_similar_chunks_diversification_grouping(db_session_factory) -> None:
    """Test that diversify_duplicates=True groups identical chunks into alternate_sources."""
    identical_hash = "h" * 64
    distinct_hash = "d" * 64

    with db_session_factory() as session:
        ep1 = Episode(
            source_path="episodes/andy-raskin/transcript.md",
            guest="Andy Raskin",
            title="The Greatest Sales Deck (Original)",
            source_platform="youtube",
            source_sha256="1" * 64,
            body_sha256="b" * 64,
            raw_metadata={},
        )
        ep2 = Episode(
            source_path="episodes/andy-raskin_/transcript.md",
            guest="Andy Raskin",
            title="The Greatest Sales Deck (Duplicate)",
            source_platform="youtube",
            source_sha256="2" * 64,
            body_sha256="b" * 64,
            raw_metadata={},
        )
        ep3 = Episode(
            source_path="episodes/other-guest/transcript.md",
            guest="Other Guest",
            title="Other Episode",
            source_platform="youtube",
            source_sha256="3" * 64,
            body_sha256="o" * 64,
            raw_metadata={},
        )
        session.add_all([ep1, ep2, ep3])
        session.flush()

        # Two chunks with identical content and hash
        c1 = TranscriptChunk(
            episode_id=ep1.id,
            chunk_index=5,
            chunk_text="Duplicate identical strategic narrative chunk.",
            chunk_sha256=identical_hash,
            token_count=50,
            character_count=45,
            speaker="Andy",
            start_time_seconds=100.0,
            embedding=[0.5] * 768,
        )
        c2 = TranscriptChunk(
            episode_id=ep2.id,
            chunk_index=5,
            chunk_text="Duplicate identical strategic narrative chunk.",
            chunk_sha256=identical_hash,
            token_count=50,
            character_count=45,
            speaker="Andy",
            start_time_seconds=100.0,
            embedding=[0.5] * 768,
        )
        # Distinct chunk
        c3 = TranscriptChunk(
            episode_id=ep3.id,
            chunk_index=0,
            chunk_text="Distinct third chunk on separate topic.",
            chunk_sha256=distinct_hash,
            token_count=50,
            character_count=40,
            speaker="Other",
            start_time_seconds=200.0,
            embedding=[0.4] * 768,
        )
        session.add_all([c1, c2, c3])
        session.commit()

    mock_embedder = MagicMock(spec=OllamaEmbedder)
    mock_embedder.model = "nomic-embed-text:v1.5"
    mock_embedder.dimensions = 768
    mock_embedder.embed_query.return_value = [0.5] * 768

    # Case 1: Standard search (diversify_duplicates=False) -> both duplicate chunks returned in top 2
    res_standard = search_similar_chunks(
        "strategic narrative",
        top_k=2,
        session_factory=db_session_factory,
        embedder=mock_embedder,
        diversify_duplicates=False,
    )
    assert len(res_standard) == 2
    assert res_standard[0].chunk_text == res_standard[1].chunk_text

    # Case 2: Diversified search (diversify_duplicates=True) -> duplicate collapsed into alternate_sources
    res_diversified = search_similar_chunks(
        "strategic narrative",
        top_k=2,
        session_factory=db_session_factory,
        embedder=mock_embedder,
        diversify_duplicates=True,
    )
    assert len(res_diversified) == 2
    # First result has the alternate source recorded
    assert len(res_diversified[0].alternate_sources) == 1
    assert "episodes/andy-raskin" in res_diversified[0].source_path or "episodes/andy-raskin_" in res_diversified[0].source_path
    assert "Chunk #5" in res_diversified[0].alternate_sources[0]
    # Second result is the distinct chunk rather than the duplicate copy!
    assert res_diversified[1].chunk_text == "Distinct third chunk on separate topic."


def test_search_fulltext_chunks(db_session_factory) -> None:
    with db_session_factory() as session:
        ep = Episode(
            source_path="episodes/rahul-vohra/transcript.md",
            guest="Rahul Vohra",
            title="Superhuman Product Market Fit Engine",
            source_sha256="sha_rv_ft_1",
            body_sha256="sha_rv_ft_2",
        )
        session.add(ep)
        session.commit()
        session.refresh(ep)

        c1 = TranscriptChunk(
            episode_id=ep.id,
            chunk_index=0,
            chunk_text="The Superhuman product market fit engine measures how disappointed users would be without the product.",
            chunk_sha256="sha_rv_c1",
            token_count=60,
            character_count=105,
            speaker="Rahul Vohra",
            start_time_seconds=120.0,
            embedding=[0.05] * 768,
        )
        session.add(c1)
        session.commit()

    # Search by exact full-text keywords
    results = search_fulltext_chunks("Superhuman engine disappointed", top_k=5, session_factory=db_session_factory)
    assert len(results) >= 1
    assert any("Superhuman product market fit engine" in r["chunk_text"] for r in results)


def test_search_hybrid_chunks_rrf(db_session_factory) -> None:
    with db_session_factory() as session:
        ep = Episode(
            source_path="episodes/rahul-vohra/transcript.md",
            guest="Rahul Vohra",
            title="Superhuman Product Market Fit Engine",
            source_sha256="sha_rv_rrf_1",
            body_sha256="sha_rv_rrf_2",
        )
        session.add(ep)
        session.commit()
        session.refresh(ep)

        c1 = TranscriptChunk(
            episode_id=ep.id,
            chunk_index=0,
            chunk_text="The Superhuman product market fit engine measures how disappointed users would be without the product.",
            chunk_sha256="sha_rv_rrf_c1",
            token_count=60,
            character_count=105,
            speaker="Rahul Vohra",
            start_time_seconds=120.0,
            embedding=[0.05] * 768,
        )
        session.add(c1)
        session.commit()

    mock_embedder = MagicMock(spec=OllamaEmbedder)
    mock_embedder.model = "nomic-embed-text:v1.5"
    mock_embedder.dimensions = 768
    mock_embedder.embed_query.return_value = [0.05] * 768

    results = search_hybrid_chunks(
        "Superhuman product market fit engine",
        top_k=3,
        session_factory=db_session_factory,
        embedder=mock_embedder,
    )
    assert len(results) >= 1
    assert hasattr(results[0], "rrf_score")
    assert results[0].rrf_score > 0
    assert "Rahul Vohra" in results[0].guest or "Superhuman" in results[0].chunk_text


