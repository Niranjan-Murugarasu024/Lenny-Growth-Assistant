from __future__ import annotations

from datetime import date, datetime
from typing import Any
import uuid
from uuid import UUID as PyUUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
    validates,
)

from backend.app.database import Base

# Universal JSON type using JSONB on PostgreSQL and JSON fallback on SQLite
JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")


class Episode(Base):
    """Episode metadata and source file integrity records."""

    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_path: Mapped[str] = mapped_column(
        String(512),
        unique=True,
        nullable=False,
        index=True,
        comment="Normalized relative POSIX path within raw transcript repository",
    )
    guest: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_platform: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="youtube",
        comment="Platform identifier, e.g. youtube or spotify",
    )
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    youtube_video_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Non-unique external YouTube ID due to upstream attribution anomalies",
    )
    spotify_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    spotify_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    publish_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=dict,
        comment="Full parsed YAML frontmatter preserved as JSONB",
    )
    source_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="SHA-256 of full source file bytes",
    )
    body_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="SHA-256 of normalized transcript dialogue text",
    )
    embedding_model: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="nomic-embed-text:v1.5",
    )
    chunker_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="v1",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    chunks: Mapped[list[TranscriptChunk]] = relationship(
        "TranscriptChunk",
        back_populates="episode",
        cascade="all, delete-orphan",
        order_by="TranscriptChunk.chunk_index",
    )

    @validates("source_path")
    def validate_source_path(self, key: str, value: str) -> str:
        """Enforce normalized relative POSIX path without escaping source root."""
        if not value or not str(value).strip():
            raise ValueError("source_path must be a non-empty string.")

        normalized = str(value).strip().replace("\\", "/")

        # Reject absolute paths (POSIX leading slash or Windows drive letter)
        if normalized.startswith("/") or ":" in normalized:
            raise ValueError(
                f"source_path must be a relative path, got absolute path: {value!r}"
            )

        # Reject path traversal
        segments = [seg for seg in normalized.split("/") if seg]
        if ".." in segments:
            raise ValueError(
                f"source_path cannot escape root with '..', got: {value!r}"
            )

        return "/".join(segments)

    def __repr__(self) -> str:
        return (
            f"<Episode(id={self.id}, guest={self.guest!r}, "
            f"source_path={self.source_path!r})>"
        )


class TranscriptChunk(Base):
    """Text chunks and vector embeddings generated from episode transcripts."""

    __tablename__ = "transcript_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(768),
        nullable=True,
        comment="768-dimensional embedding from nomic-embed-text:v1.5",
    )
    embedding_model: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="nomic-embed-text:v1.5",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    episode: Mapped[Episode] = relationship("Episode", back_populates="chunks")

    __table_args__ = (
        UniqueConstraint(
            "episode_id",
            "chunk_index",
            name="uq_transcript_chunks_episode_chunk_index",
        ),
        Index("ix_transcript_chunks_episode_chunk", "episode_id", "chunk_index"),
    )

    def __repr__(self) -> str:
        return (
            f"<TranscriptChunk(id={self.id}, episode_id={self.episode_id}, "
            f"chunk_index={self.chunk_index})>"
        )


class IngestionRun(Base):
    """Execution audit records for transcript corpus ingestion runs."""

    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="running",
    )
    total_episodes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE,
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<IngestionRun(id={self.id}, status={self.status!r}, "
            f"success={self.success_count}/{self.total_episodes})>"
        )


class ChatSession(Base):
    """Conversational session containing persistent user and assistant messages."""

    __tablename__ = "chat_sessions"

    id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_TYPE,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    messages: Mapped[list[ChatMessage]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at.asc(), ChatMessage.id.asc()",
    )

    __table_args__ = (
        Index("ix_chat_sessions_created_at", "created_at"),
        Index("ix_chat_sessions_updated_at", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<ChatSession(id={self.id}, title={self.title!r})>"


class ChatMessage(Base):
    """Individual conversational turn persisted within a chat session."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sources: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON_TYPE,
        nullable=True,
        default=list,
    )
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    session: Mapped[ChatSession] = relationship("ChatSession", back_populates="messages")

    __table_args__ = (
        Index("ix_chat_messages_session_created_at", "session_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ChatMessage(id={self.id}, session_id={self.session_id}, "
            f"role={self.role!r})>"
        )


class WritingArtifact(Base):
    """
    Persistent root entity for versioned writing documents (essays, summaries, frameworks).
    """

    __tablename__ = "writing_artifacts"

    id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    session_id: Mapped[PyUUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    artifact_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="essay",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="completed",
        comment="Status: queued, generating, completed, failed",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    session: Mapped[ChatSession | None] = relationship("ChatSession")
    versions: Mapped[list[WritingArtifactVersion]] = relationship(
        "WritingArtifactVersion",
        back_populates="artifact",
        cascade="all, delete-orphan",
        order_by="WritingArtifactVersion.version_number.asc()",
    )

    __table_args__ = (
        Index("ix_writing_artifacts_created_at", "created_at"),
        Index("ix_writing_artifacts_updated_at", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<WritingArtifact(id={self.id}, title={self.title!r}, status={self.status!r})>"


class WritingArtifactVersion(Base):
    """
    Immutable versioned snapshot of a writing artifact containing Markdown, HTML preview,
    word count, writing brief, validated sources, and quality evaluation results.
    """

    __tablename__ = "writing_artifact_versions"

    id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    artifact_id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("writing_artifacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    markdown_content: Mapped[str] = mapped_column(Text, nullable=False)
    html_content: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    writing_brief: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=dict,
    )
    sources: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=list,
    )
    eval_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=dict,
    )
    model_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    artifact: Mapped[WritingArtifact] = relationship(
        "WritingArtifact",
        back_populates="versions",
    )

    __table_args__ = (
        UniqueConstraint(
            "artifact_id",
            "version_number",
            name="uq_writing_artifact_versions_artifact_version",
        ),
        Index("ix_writing_artifact_versions_artifact_version", "artifact_id", "version_number"),
        Index("ix_writing_artifact_versions_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<WritingArtifactVersion(id={self.id}, artifact_id={self.artifact_id}, "
            f"version={self.version_number}, word_count={self.word_count})>"
        )


class WritingJob(Base):
    """
    Persistent background writing job tracking execution lifecycle, retries,
    heartbeats, and idempotency across API and worker restarts.
    """

    __tablename__ = "writing_jobs"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="Stable job identifier e.g. job_9369f4fa7afe",
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128),
        unique=True,
        nullable=True,
        index=True,
        comment="Optional client-provided idempotency key for deduplication",
    )
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="queued",
        index=True,
        comment="queued, running, completed, failed",
    )
    stage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1250)
    brief: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=dict,
    )
    artifact_id: Mapped[PyUUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("writing_artifacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    artifact: Mapped[WritingArtifact | None] = relationship("WritingArtifact")

    __table_args__ = (
        Index("ix_writing_jobs_created_at", "created_at"),
        Index("ix_writing_jobs_heartbeat_at", "heartbeat_at"),
        Index("ix_writing_jobs_status_created_at", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<WritingJob(id={self.id!r}, status={self.status!r}, topic={self.topic!r})>"


class AppSetting(Base):
    """
    Persistent key-value system settings stored in PostgreSQL to synchronize
    state across FastAPI instances, background workers, and container restarts.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<AppSetting(key={self.key!r}, value={self.value!r})>"



