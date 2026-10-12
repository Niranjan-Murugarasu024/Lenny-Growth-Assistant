"""add fulltext index and writing_jobs table

Revision ID: 0004_fulltext_and_writing_jobs
Revises: 0003_writing_artifacts
Create Date: 2026-10-12 11:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004_fulltext_and_writing_jobs"
down_revision: Union[str, None] = "0003_writing_artifacts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create writing_jobs table
    op.create_table(
        "writing_jobs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("topic", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(length=100), nullable=True),
        sa.Column("target_word_count", sa.Integer(), nullable=False, server_default="1250"),
        sa.Column("brief", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("artifact_id", sa.Uuid(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["writing_artifacts.id"],
            name="fk_writing_jobs_artifact_id_writing_artifacts",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_writing_jobs_status", "writing_jobs", ["status"])
    op.create_index("ix_writing_jobs_idempotency_key", "writing_jobs", ["idempotency_key"], unique=True)
    op.create_index("ix_writing_jobs_artifact_id", "writing_jobs", ["artifact_id"])
    op.create_index("ix_writing_jobs_created_at", "writing_jobs", ["created_at"])
    op.create_index("ix_writing_jobs_heartbeat_at", "writing_jobs", ["heartbeat_at"])
    op.create_index("ix_writing_jobs_status_created_at", "writing_jobs", ["status", "created_at"])

    # 2. Add GIN full-text index on transcript_chunks (chunk_text)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transcript_chunks_tsv ON transcript_chunks "
        "USING gin (to_tsvector('english', chunk_text));"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_transcript_chunks_tsv;")
    op.drop_table("writing_jobs")
