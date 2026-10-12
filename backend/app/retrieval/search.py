from __future__ import annotations

from dataclasses import dataclass, field
import logging
import math
from typing import Sequence

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import get_settings
from backend.app.database import create_session_factory
from backend.app.ingestion.embedder import OllamaEmbedder
from backend.app.models import Episode, TranscriptChunk

logger = logging.getLogger(__name__)


def format_seconds_to_timestamp(seconds: float | None) -> str | None:
    """Format total seconds into HH:MM:SS string only when valid and verified."""
    if seconds is None or seconds < 0:
        return None
    total_sec = int(round(seconds))
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    secs = total_sec % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


@dataclass
class SearchResult:
    """Semantic search result record representing a matching transcript chunk."""

    chunk_id: int
    chunk_index: int
    chunk_text: str
    cosine_distance: float
    guest: str
    title: str
    source_path: str
    speaker: str | None
    start_time_seconds: float | None
    timestamp: str | None
    embedding_model: str
    alternate_sources: list[str] = field(default_factory=list)
    source_url: str | None = None
    youtube_video_id: str | None = None


def search_similar_chunks(
    query: str,
    top_k: int = 5,
    session_factory: sessionmaker[Session] | None = None,
    embedder: OllamaEmbedder | None = None,
    diversify_duplicates: bool = False,
) -> list[SearchResult]:
    """
    Retrieve the top-k transcript chunks matching a query by cosine distance.

    Prefixes query with 'search_query: ', verifies vector dimensions, and queries
    the database using bound SQLAlchemy expressions without approximate indexing.

    When diversify_duplicates is True, duplicate passages from identical dialogue
    episodes are grouped together, displaying alternative source paths without
    crowding out distinct results from the top-k ranking.
    """
    cleaned_query = (query or "").strip()
    if not cleaned_query:
        return []

    if top_k <= 0:
        raise ValueError(f"top_k must be a positive integer, got {top_k}")

    settings = get_settings()
    active_embedder = embedder or OllamaEmbedder()
    db_factory = session_factory or create_session_factory()

    # 1. Embed query with 'search_query: ' prefix
    logger.debug("Generating query embedding for: %r (model: %s)", cleaned_query, active_embedder.model)
    query_vector = active_embedder.embed_query(cleaned_query)

    # 2. Validate query vector properties
    expected_dim = active_embedder.dimensions or settings.embedding_dimensions
    if len(query_vector) != expected_dim:
        raise ValueError(
            f"Query embedding dimension mismatch: expected {expected_dim}, got {len(query_vector)}"
        )
    for idx, val in enumerate(query_vector):
        if not math.isfinite(val):
            raise ValueError(f"Query embedding element {idx} is non-finite: {val!r}")

    # 3. Formulate SQLAlchemy expression with cosine distance and bound parameters
    cosine_dist = TranscriptChunk.embedding.cosine_distance(query_vector).label("cosine_distance")
    fetch_limit = max(top_k * 3, 20) if diversify_duplicates else top_k

    stmt = (
        select(
            TranscriptChunk.id,
            TranscriptChunk.chunk_index,
            TranscriptChunk.chunk_text,
            TranscriptChunk.chunk_sha256,
            TranscriptChunk.speaker,
            TranscriptChunk.start_time_seconds,
            TranscriptChunk.embedding_model,
            Episode.guest,
            Episode.title,
            Episode.source_path,
            Episode.source_url,
            Episode.youtube_video_id,
            cosine_dist,
        )
        .join(Episode, TranscriptChunk.episode_id == Episode.id)
        .where(TranscriptChunk.embedding.isnot(None))
        .order_by(cosine_dist.asc())
        .limit(fetch_limit)
    )

    results: list[SearchResult] = []
    seen_hashes: dict[str, SearchResult] = {}

    with db_factory() as session:
        rows = session.execute(stmt).all()
        for row in rows:
            dist_val = float(row.cosine_distance) if row.cosine_distance is not None else 1.0
            ts_str = format_seconds_to_timestamp(row.start_time_seconds)

            if diversify_duplicates:
                chunk_hash = row.chunk_sha256
                if chunk_hash in seen_hashes:
                    alt_desc = f"{row.source_path} (Chunk #{row.chunk_index})"
                    if alt_desc not in seen_hashes[chunk_hash].alternate_sources:
                        seen_hashes[chunk_hash].alternate_sources.append(alt_desc)
                    continue

            sr = SearchResult(
                chunk_id=row.id,
                chunk_index=row.chunk_index,
                chunk_text=row.chunk_text,
                cosine_distance=round(dist_val, 4),
                guest=row.guest,
                title=row.title,
                source_path=row.source_path,
                speaker=row.speaker,
                start_time_seconds=row.start_time_seconds,
                timestamp=ts_str,
                embedding_model=row.embedding_model,
                source_url=row.source_url,
                youtube_video_id=row.youtube_video_id,
            )

            results.append(sr)
            if diversify_duplicates:
                seen_hashes[row.chunk_sha256] = sr
                if len(results) >= top_k:
                    break

    return results


def search_fulltext_chunks(
    query: str,
    top_k: int = 10,
    session_factory: sessionmaker[Session] | None = None,
) -> list[dict]:
    """
    Retrieve transcript chunks using PostgreSQL full-text search with ts_rank_cd.
    """
    cleaned_query = (query or "").strip()
    if not cleaned_query or top_k <= 0:
        return []

    db_factory = session_factory or create_session_factory()
    sql_websearch = text("""
        SELECT 
            tc.id,
            tc.chunk_index,
            tc.chunk_text,
            tc.chunk_sha256,
            tc.speaker,
            tc.start_time_seconds,
            tc.embedding_model,
            e.guest,
            e.title,
            e.source_path,
            e.source_url,
            e.youtube_video_id,
            ts_rank_cd(to_tsvector('english', tc.chunk_text), q) AS rank
        FROM transcript_chunks tc
        JOIN episodes e ON tc.episode_id = e.id,
        websearch_to_tsquery('english', :query) q
        WHERE to_tsvector('english', tc.chunk_text) @@ q
        ORDER BY rank DESC
        LIMIT :limit
    """)

    sql_plain = text("""
        SELECT 
            tc.id,
            tc.chunk_index,
            tc.chunk_text,
            tc.chunk_sha256,
            tc.speaker,
            tc.start_time_seconds,
            tc.embedding_model,
            e.guest,
            e.title,
            e.source_path,
            e.source_url,
            e.youtube_video_id,
            ts_rank_cd(to_tsvector('english', tc.chunk_text), q) AS rank
        FROM transcript_chunks tc
        JOIN episodes e ON tc.episode_id = e.id,
        plainto_tsquery('english', :query) q
        WHERE to_tsvector('english', tc.chunk_text) @@ q
        ORDER BY rank DESC
        LIMIT :limit
    """)

    with db_factory() as session:
        try:
            rows = session.execute(sql_websearch, {"query": cleaned_query, "limit": top_k}).mappings().all()
        except Exception:
            rows = []

        if not rows:
            try:
                rows = session.execute(sql_plain, {"query": cleaned_query, "limit": top_k}).mappings().all()
            except Exception:
                rows = []

        return [dict(r) for r in rows]


def search_hybrid_chunks(
    query: str,
    top_k: int = 5,
    session_factory: sessionmaker[Session] | None = None,
    embedder: OllamaEmbedder | None = None,
    diversify_duplicates: bool = True,
    rrf_k: int = 60,
) -> list[SearchResult]:
    """
    Retrieve transcript chunks combining dense semantic search (pgvector) and
    lexical full-text search (tsvector) using Reciprocal Rank Fusion (RRF).

    RRF Score formula:
        RRF(d) = 1 / (rrf_k + rank_dense) + 1 / (rrf_k + rank_lexical)
    """
    cleaned_query = (query or "").strip()
    if not cleaned_query:
        return []

    if top_k <= 0:
        raise ValueError(f"top_k must be a positive integer, got {top_k}")

    # 1. Fetch dense candidates (up to 30)
    dense_fetch_k = max(top_k * 4, 30)
    dense_results = search_similar_chunks(
        query=cleaned_query,
        top_k=dense_fetch_k,
        session_factory=session_factory,
        embedder=embedder,
        diversify_duplicates=False,
    )

    # 2. Fetch lexical candidates (up to 30)
    lexical_rows = search_fulltext_chunks(
        query=cleaned_query,
        top_k=dense_fetch_k,
        session_factory=session_factory,
    )

    # 3. Compute Reciprocal Rank Fusion (RRF) scores
    rrf_scores: dict[int, float] = {}
    dense_ranks: dict[int, int] = {}
    lexical_ranks: dict[int, int] = {}
    candidate_map: dict[int, SearchResult] = {}

    for rank, sr in enumerate(dense_results, start=1):
        dense_ranks[sr.chunk_id] = rank
        candidate_map[sr.chunk_id] = sr
        rrf_scores[sr.chunk_id] = rrf_scores.get(sr.chunk_id, 0.0) + (1.0 / (rrf_k + rank))

    for rank, row in enumerate(lexical_rows, start=1):
        chunk_id = row["id"]
        lexical_ranks[chunk_id] = rank
        if chunk_id not in candidate_map:
            ts_str = format_seconds_to_timestamp(row.get("start_time_seconds"))
            candidate_map[chunk_id] = SearchResult(
                chunk_id=chunk_id,
                chunk_index=row["chunk_index"],
                chunk_text=row["chunk_text"],
                cosine_distance=0.5,  # Fallback neutral distance for lexical-only matches
                guest=row["guest"],
                title=row["title"],
                source_path=row["source_path"],
                speaker=row.get("speaker"),
                start_time_seconds=row.get("start_time_seconds"),
                timestamp=ts_str,
                embedding_model=row.get("embedding_model", "nomic-embed-text:v1.5"),
                source_url=row.get("source_url"),
                youtube_video_id=row.get("youtube_video_id"),
            )
        rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + (1.0 / (rrf_k + rank))

    # 4. Sort candidates by fused RRF score descending
    sorted_chunk_ids = sorted(candidate_map.keys(), key=lambda cid: rrf_scores[cid], reverse=True)

    final_results: list[SearchResult] = []
    seen_hashes: dict[str, SearchResult] = {}

    for cid in sorted_chunk_ids:
        sr = candidate_map[cid]
        sr.rrf_score = round(rrf_scores[cid], 5)

        if diversify_duplicates:
            # Check for duplicate text
            chunk_hash = getattr(sr, "chunk_sha256", None) or str(hash(sr.chunk_text))
            if chunk_hash in seen_hashes:
                alt_desc = f"{sr.source_path} (Chunk #{sr.chunk_index})"
                if alt_desc not in seen_hashes[chunk_hash].alternate_sources:
                    seen_hashes[chunk_hash].alternate_sources.append(alt_desc)
                continue
            seen_hashes[chunk_hash] = sr

        final_results.append(sr)
        if len(final_results) >= top_k:
            break

    return final_results
