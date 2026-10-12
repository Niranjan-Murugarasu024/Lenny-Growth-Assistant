"""initial schema with episodes, transcript_chunks, and ingestion_runs

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-11 16:30:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import pgvector.sqlalchemy

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Enable pgvector extension before creating vector columns
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # 2. Create episodes table
    op.create_table(
        "episodes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_path", sa.String(length=512), nullable=False),
        sa.Column("guest", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_platform", sa.String(length=50), server_default="youtube", nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("youtube_video_id", sa.String(length=100), nullable=True),
        sa.Column("spotify_url", sa.Text(), nullable=True),
        sa.Column("spotify_id", sa.String(length=100), nullable=True),
        sa.Column("publish_date", sa.Date(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("raw_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("body_sha256", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), server_default="nomic-embed-text:v1.5", nullable=False),
        sa.Column("chunker_version", sa.String(length=50), server_default="v1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_path", name="uq_episodes_source_path"),
    )
    op.create_index("ix_episodes_source_path", "episodes", ["source_path"], unique=True)
    op.create_index("ix_episodes_guest", "episodes", ["guest"], unique=False)
    op.create_index("ix_episodes_publish_date", "episodes", ["publish_date"], unique=False)
    op.create_index("ix_episodes_youtube_video_id", "episodes", ["youtube_video_id"], unique=False)
    op.create_index("ix_episodes_source_sha256", "episodes", ["source_sha256"], unique=False)
    op.create_index("ix_episodes_body_sha256", "episodes", ["body_sha256"], unique=False)

    # 3. Create transcript_chunks table
    op.create_table(
        "transcript_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("episode_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("chunk_sha256", sa.String(length=64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("speaker", sa.String(length=255), nullable=True),
        sa.Column("start_time_seconds", sa.Float(), nullable=True),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=768), nullable=True),
        sa.Column("embedding_model", sa.String(length=100), server_default="nomic-embed-text:v1.5", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["episode_id"], ["episodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("episode_id", "chunk_index", name="uq_transcript_chunks_episode_chunk_index"),
    )
    op.create_index("ix_transcript_chunks_episode_id", "transcript_chunks", ["episode_id"], unique=False)
    op.create_index("ix_transcript_chunks_chunk_sha256", "transcript_chunks", ["chunk_sha256"], unique=False)
    op.create_index("ix_transcript_chunks_episode_chunk", "transcript_chunks", ["episode_id", "chunk_index"], unique=False)

    # 4. Create ingestion_runs table
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="running", nullable=False),
        sa.Column("total_episodes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("success_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("ingestion_runs")
    op.drop_table("transcript_chunks")
    op.drop_table("episodes")
    op.execute("DROP EXTENSION IF EXISTS vector;")
