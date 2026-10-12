"""add writing_artifacts and writing_artifact_versions tables

Revision ID: 0003_writing_artifacts_and_versions
Revises: 0002_chat_sessions_and_messages
Create Date: 2026-10-11 23:30:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003_writing_artifacts"
down_revision: Union[str, None] = "0002_chat_sessions_and_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create writing_artifacts table
    op.create_table(
        "writing_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("artifact_type", sa.String(length=50), nullable=False, server_default="essay"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="completed"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name="fk_writing_artifacts_session_id_chat_sessions",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_writing_artifacts_session_id", "writing_artifacts", ["session_id"], unique=False)
    op.create_index("ix_writing_artifacts_created_at", "writing_artifacts", ["created_at"], unique=False)
    op.create_index("ix_writing_artifacts_updated_at", "writing_artifacts", ["updated_at"], unique=False)

    # 2. Create writing_artifact_versions table
    op.create_table(
        "writing_artifact_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("markdown_content", sa.Text(), nullable=False),
        sa.Column("html_content", sa.Text(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("writing_brief", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("eval_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["writing_artifacts.id"],
            name="fk_writing_artifact_versions_artifact_id_writing_artifacts",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", "version_number", name="uq_writing_artifact_versions_artifact_version"),
    )
    op.create_index("ix_writing_artifact_versions_artifact_id", "writing_artifact_versions", ["artifact_id"], unique=False)
    op.create_index(
        "ix_writing_artifact_versions_artifact_version",
        "writing_artifact_versions",
        ["artifact_id", "version_number"],
        unique=False,
    )
    op.create_index("ix_writing_artifact_versions_created_at", "writing_artifact_versions", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_writing_artifact_versions_created_at", table_name="writing_artifact_versions")
    op.drop_index("ix_writing_artifact_versions_artifact_version", table_name="writing_artifact_versions")
    op.drop_index("ix_writing_artifact_versions_artifact_id", table_name="writing_artifact_versions")
    op.drop_table("writing_artifact_versions")

    op.drop_index("ix_writing_artifacts_updated_at", table_name="writing_artifacts")
    op.drop_index("ix_writing_artifacts_created_at", table_name="writing_artifacts")
    op.drop_index("ix_writing_artifacts_session_id", table_name="writing_artifacts")
    op.drop_table("writing_artifacts")
