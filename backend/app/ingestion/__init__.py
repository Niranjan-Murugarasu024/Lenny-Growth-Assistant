"""Ingestion package for transcript parsing, tokenization, structure-aware chunking, embedding, and pipeline orchestration."""
from __future__ import annotations

from backend.app.ingestion.chunker import (
    ChunkData,
    TokenCounter,
    chunk_transcript,
)
from backend.app.ingestion.embedder import (
    EmbeddingBatchCountError,
    EmbeddingConnectionError,
    EmbeddingDimensionError,
    EmbeddingError,
    EmbeddingOversizedInputError,
    EmbeddingValueError,
    OllamaEmbedder,
)
from backend.app.ingestion.parser import (
    DialogueTurn,
    ParsedTranscript,
    parse_timestamp_to_seconds,
    parse_transcript_source,
)
from backend.app.ingestion.pipeline import (
    PipelineResult,
    run_ingestion_pipeline,
)

__all__ = [
    "ChunkData",
    "DialogueTurn",
    "EmbeddingBatchCountError",
    "EmbeddingConnectionError",
    "EmbeddingDimensionError",
    "EmbeddingError",
    "EmbeddingOversizedInputError",
    "EmbeddingValueError",
    "OllamaEmbedder",
    "ParsedTranscript",
    "PipelineResult",
    "TokenCounter",
    "chunk_transcript",
    "parse_timestamp_to_seconds",
    "parse_transcript_source",
    "run_ingestion_pipeline",
]
