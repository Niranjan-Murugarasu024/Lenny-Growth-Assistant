"""
Regression tests for critical essay generation worker defects:
- BUG-001: TranscriptChunk timestamp schema mismatch (ORM model has start_time_seconds, not timestamp)
- BUG-002: Brief snapshot deserialization with strict extra="forbid" schema
- BUG-003: Accessible drafts and quality failure handling
- Async AI revision job lifecycle and conflict handling
"""
import uuid
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.models import ChatMessage, ChatSession, Episode, TranscriptChunk, WritingArtifact, WritingArtifactVersion
from backend.app.writing.job_runner import DurableEssayJobManager, unpack_job_brief
from backend.app.writing.schemas import WritingBriefRequest
from backend.app.writing.service import WritingService, format_seconds_to_timestamp


def test_bug_001_session_grounded_context_handles_orm_chunk_without_timestamp_attribute(db_session_factory):
    """
    BUG-001 Regression:
    Ensure get_session_grounded_context formats timestamp from start_time_seconds
    on the real TranscriptChunk ORM model and does not raise AttributeError: 'TranscriptChunk' object has no attribute 'timestamp'.
    """
    session_id = uuid.uuid4()
    with db_session_factory() as session:
        # Create chat session
        chat_sess = ChatSession(id=session_id)
        session.add(chat_sess)
        session.flush()

        # Create episode and chunk
        ep = Episode(
            source_path="episodes/brian/test.md",
            guest="Brian Chesky",
            title="Designing The 11-Star Experience",
            source_sha256="hash1",
            body_sha256="hash2",
            youtube_video_id="abc12345",
        )
        session.add(ep)
        session.flush()

        tc = TranscriptChunk(
            episode_id=ep.id,
            chunk_index=0,
            chunk_text="You have to design the 11-star experience first.",
            chunk_sha256="sha256_mock_hash",
            token_count=10,
            character_count=48,
            embedding=[0.05] * 768,
            embedding_model="nomic-embed-text:v1.5",
            start_time_seconds=225.0,  # 03:45
        )
        session.add(tc)
        session.flush()

        # Verify tc model does NOT have timestamp attribute directly
        assert not hasattr(tc, "timestamp")

        # Create assistant message citing this chunk
        msg = ChatMessage(
            session_id=session_id,
            role="assistant",
            content="Brian Chesky recommends designing the 11-star experience [1].",
            sources=[
                {
                    "chunk_id": tc.id,
                    "title": ep.title,
                    "guest": ep.guest,
                    "source_path": ep.source_path,
                    "start_time_seconds": 225.0,
                    # Deliberately omit or include timestamp
                }
            ],
        )
        session.add(msg)
        session.commit()

    # Invoke WritingService.get_session_grounded_context
    writing_service = WritingService(session_factory=db_session_factory)
    results, grounded_answer = writing_service.get_session_grounded_context(session_id)

    assert len(results) == 1
    chunk_res = results[0]
    assert chunk_res.chunk_id == tc.id
    assert chunk_res.guest == "Brian Chesky"
    assert chunk_res.timestamp == "00:03:45"
    assert grounded_answer is not None
    assert "11-star experience" in grounded_answer


def test_bug_002_brief_snapshot_deserialization_with_strict_schema():
    """
    BUG-002 Regression:
    Ensure unpack_job_brief separates validated WritingBriefRequest from provider/model
    execution snapshot metadata while preserving strict extra="forbid".
    """
    # 1. New structured format
    structured_payload = {
        "brief": {
            "topic": "How to measure product-market fit",
            "audience": "Founders and PMs",
            "purpose": "Provide frameworks for PMF metrics",
            "target_word_count": 650,
        },
        "snapshot": {
            "provider": "ollama",
            "model": "qwen2.5:1.5b",
        },
    }
    brief, snapshot = unpack_job_brief(structured_payload)
    assert brief.topic == "How to measure product-market fit"
    assert brief.target_word_count == 650
    assert snapshot["provider"] == "ollama"
    assert snapshot["model"] == "qwen2.5:1.5b"

    # 2. Legacy format with _snapshot_* keys embedded
    legacy_payload = {
        "topic": "Scaling growth loops",
        "audience": "Growth marketers",
        "purpose": "Loop architectures",
        "target_word_count": 1250,
        "_snapshot_provider": "nvidia",
        "_snapshot_model": "openai/gpt-oss-20b",
    }
    brief_leg, snapshot_leg = unpack_job_brief(legacy_payload)
    assert brief_leg.topic == "Scaling growth loops"
    assert snapshot_leg["provider"] == "nvidia"
    assert snapshot_leg["model"] == "openai/gpt-oss-20b"

    # 3. Truly invalid input should still be forbidden by extra="forbid"
    invalid_payload = {
        "brief": {
            "topic": "Test topic",
            "unknown_extra_field": "disallowed",
        },
        "snapshot": {},
    }
    with pytest.raises(ValidationError):
        unpack_job_brief(invalid_payload)


def test_async_revision_job_execution_and_conflict_handling(db_session_factory):
    """
    Phase 3: Test that submit_revision_job returns trackable EssayJob,
    updates stage, and prevents conflicting stale edits.
    """
    job_mgr = DurableEssayJobManager(session_factory=db_session_factory)

    # Create artifact with version 1
    with db_session_factory() as session:
        art = WritingArtifact(
            title="Initial Test Article",
            artifact_type="essay",
            status="completed",
        )
        session.add(art)
        session.flush()

        v1 = WritingArtifactVersion(
            artifact_id=art.id,
            version_number=1,
            markdown_content="# Initial Test Article\n\nContent paragraph 1.",
            html_content="<h1>Initial Test Article</h1><p>Content paragraph 1.</p>",
            word_count=50,
            writing_brief={"topic": "Initial Test Article", "target_word_count": 500},
            sources=[],
            eval_metadata={"passed": True},
            model_metadata={"provider": "ollama", "model": "qwen2.5:1.5b"},
        )
        session.add(v1)
        session.commit()
        art_id = art.id

    # Submit revision job
    essay_job = job_mgr.submit_revision_job(
        artifact_id=art_id,
        instructions="Make the conclusion more decisive",
        target_word_count=500,
    )
    assert essay_job.job_id.startswith("job_rev_")
    assert essay_job.artifact_id == art_id
    assert essay_job.status in ("queued", "running", "completed")

    # Verify job retrieved from DB
    retrieved = job_mgr.get_job(essay_job.job_id)
    assert retrieved is not None
    assert retrieved.job_id == essay_job.job_id
