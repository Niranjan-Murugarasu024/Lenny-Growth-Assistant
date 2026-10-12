from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.deps import (
    get_app_settings,
    get_db,
    get_session_factory,
    verify_internal_token,
)
from backend.app.api.schemas import (
    InternalChunkData,
    InternalContextRequest,
    InternalContextResponse,
    InternalSearchRequest,
    InternalSearchResponse,
)
from backend.app.config import Settings
from backend.app.ingestion.embedder import OllamaEmbedder
from backend.app.models import Episode, TranscriptChunk
from backend.app.retrieval.search import format_seconds_to_timestamp, search_similar_chunks

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal/v1/transcripts",
    tags=["Internal Transcripts"],
    dependencies=[Depends(verify_internal_token)],
)


def get_embedder(
    settings: Annotated[Settings, Depends(get_app_settings)]
) -> OllamaEmbedder:
    """Dependency provider for OllamaEmbedder."""
    return OllamaEmbedder(
        base_url=settings.ollama_base_url,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )


@router.post("/search", response_model=InternalSearchResponse)
def internal_search_transcripts(
    payload: InternalSearchRequest,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    embedder: Annotated[OllamaEmbedder, Depends(get_embedder)],
) -> InternalSearchResponse:
    """
    Perform semantic vector search across transcript chunks.

    Restricted internal endpoint for autonomous agent tools.
    """
    cleaned_query = payload.query.strip()
    if not cleaned_query:
        return InternalSearchResponse(query=payload.query, count=0, chunks=[])

    raw_results = search_similar_chunks(
        query=cleaned_query,
        top_k=payload.top_k,
        session_factory=session_factory,
        embedder=embedder,
        diversify_duplicates=True,
    )

    filtered_results = raw_results
    if payload.max_distance is not None:
        filtered_results = [
            r for r in raw_results if r.cosine_distance <= payload.max_distance
        ]

    chunk_items: list[InternalChunkData] = []
    for r in filtered_results:
        chunk_items.append(
            InternalChunkData(
                chunk_id=r.chunk_id,
                chunk_index=r.chunk_index,
                chunk_text=r.chunk_text,
                cosine_distance=r.cosine_distance,
                guest=r.guest,
                title=r.title,
                source_path=r.source_path,
                speaker=r.speaker,
                timestamp=r.timestamp,
                start_time_seconds=r.start_time_seconds,
                alternate_sources=r.alternate_sources,
            )
        )

    logger.info(
        "Internal search: query=%r, raw_count=%d, returned=%d (max_distance=%s)",
        cleaned_query,
        len(raw_results),
        len(chunk_items),
        payload.max_distance,
    )

    return InternalSearchResponse(
        query=cleaned_query,
        count=len(chunk_items),
        chunks=chunk_items,
    )


@router.post("/context", response_model=InternalContextResponse)
def internal_get_transcript_context(
    payload: InternalContextRequest,
    db: Annotated[Session, Depends(get_db)],
) -> InternalContextResponse:
    """
    Retrieve surrounding chronological context chunks for a specific transcript chunk.

    Enforces episode isolation so context cannot bleed across different episodes.
    """
    target = db.get(TranscriptChunk, payload.chunk_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CHUNK_NOT_FOUND",
                "message": f"Transcript chunk with ID {payload.chunk_id} was not found.",
            },
        )

    min_idx = max(0, target.chunk_index - payload.before)
    max_idx = target.chunk_index + payload.after

    stmt = (
        select(TranscriptChunk, Episode)
        .join(Episode, TranscriptChunk.episode_id == Episode.id)
        .where(
            TranscriptChunk.episode_id == target.episode_id,
            TranscriptChunk.chunk_index >= min_idx,
            TranscriptChunk.chunk_index <= max_idx,
        )
        .order_by(TranscriptChunk.chunk_index.asc())
    )

    rows = db.execute(stmt).all()
    chunk_items: list[InternalChunkData] = []
    for chunk, ep in rows:
        chunk_items.append(
            InternalChunkData(
                chunk_id=chunk.id,
                chunk_index=chunk.chunk_index,
                chunk_text=chunk.chunk_text,
                cosine_distance=None,
                guest=ep.guest,
                title=ep.title,
                source_path=ep.source_path,
                speaker=chunk.speaker,
                timestamp=format_seconds_to_timestamp(chunk.start_time_seconds),
                start_time_seconds=chunk.start_time_seconds,
                alternate_sources=[],
            )
        )

    logger.info(
        "Internal context: chunk_id=%d, episode_id=%d, retrieved %d context chunks",
        payload.chunk_id,
        target.episode_id,
        len(chunk_items),
    )

    return InternalContextResponse(
        target_chunk_id=target.id,
        episode_id=target.episode_id,
        count=len(chunk_items),
        chunks=chunk_items,
    )
