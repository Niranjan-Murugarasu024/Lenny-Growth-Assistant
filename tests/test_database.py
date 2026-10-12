from __future__ import annotations

import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.config import get_settings
from backend.app.database import create_db_engine, create_session_factory
from backend.app.models import Episode, IngestionRun, TranscriptChunk
from scripts.check_database import check_database





def test_check_database_diagnostic_succeeds() -> None:
    """Verify that the check_database script passes against the live schema."""
    assert check_database() is True


def test_episode_crud_and_source_path_uniqueness(db_session_factory) -> None:
    unique_suffix = uuid.uuid4().hex[:8]
    path = f"episodes/test-guest-{unique_suffix}/transcript.md"

    with db_session_factory() as session:
        ep = Episode(
            source_path=path,
            guest=f"Test Guest {unique_suffix}",
            title="A Test Episode",
            source_platform="youtube",
            source_url="https://youtube.com/watch?v=xyz",
            youtube_video_id="xyz123",
            raw_metadata={"tags": ["growth", "ai"]},
            source_sha256="1" * 64,
            body_sha256="2" * 64,
        )
        session.add(ep)
        session.commit()
        ep_id = ep.id

    assert ep_id is not None

    # Test uniqueness on source_path
    with db_session_factory() as session:
        duplicate_ep = Episode(
            source_path=path,  # same path
            guest="Another Guest",
            title="Another Title",
            source_platform="youtube",
            source_sha256="3" * 64,
            body_sha256="4" * 64,
        )
        session.add(duplicate_ep)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    # Clean up
    with db_session_factory() as session:
        ep_to_del = session.get(Episode, ep_id)
        if ep_to_del:
            session.delete(ep_to_del)
            session.commit()


def test_youtube_video_id_is_non_unique(db_session_factory) -> None:
    """Verify that multiple episodes CAN share the same youtube_video_id."""
    unique_suffix = uuid.uuid4().hex[:8]
    shared_video_id = f"shared_vid_{unique_suffix}"

    with db_session_factory() as session:
        ep1 = Episode(
            source_path=f"episodes/guest1-{unique_suffix}/transcript.md",
            guest="Guest 1",
            title="Episode 1",
            youtube_video_id=shared_video_id,
            source_sha256="a" * 64,
            body_sha256="b" * 64,
        )
        ep2 = Episode(
            source_path=f"episodes/guest2-{unique_suffix}/transcript.md",
            guest="Guest 2",
            title="Episode 2",
            youtube_video_id=shared_video_id,
            source_sha256="c" * 64,
            body_sha256="d" * 64,
        )
        session.add_all([ep1, ep2])
        # Must commit without IntegrityError
        session.commit()
        ep1_id, ep2_id = ep1.id, ep2.id

    assert ep1_id != ep2_id

    # Clean up
    with db_session_factory() as session:
        for eid in (ep1_id, ep2_id):
            e = session.get(Episode, eid)
            if e:
                session.delete(e)
        session.commit()


def test_transcript_chunk_vector_and_cascade_delete(db_session_factory) -> None:
    unique_suffix = uuid.uuid4().hex[:8]

    # Create dummy 768-dim vector
    dummy_vector = [0.01 * (i % 100) for i in range(768)]

    with db_session_factory() as session:
        ep = Episode(
            source_path=f"episodes/vector-guest-{unique_suffix}/transcript.md",
            guest="Vector Guest",
            title="Vector Testing",
            source_sha256="5" * 64,
            body_sha256="6" * 64,
        )
        session.add(ep)
        session.commit()

        chunk = TranscriptChunk(
            episode_id=ep.id,
            chunk_index=0,
            chunk_text="Testing vector embedding column.",
            chunk_sha256="7" * 64,
            token_count=5,
            character_count=32,
            embedding=dummy_vector,
        )
        session.add(chunk)
        session.commit()
        ep_id = ep.id
        chunk_id = chunk.id

    # Verify chunk was stored and vector has 768 dimensions
    with db_session_factory() as session:
        loaded_chunk = session.get(TranscriptChunk, chunk_id)
        assert loaded_chunk is not None
        assert loaded_chunk.embedding is not None
        assert len(loaded_chunk.embedding) == 768

    # Test uniqueness constraint on (episode_id, chunk_index)
    with db_session_factory() as session:
        duplicate_chunk = TranscriptChunk(
            episode_id=ep_id,
            chunk_index=0,  # duplicate index
            chunk_text="Another text.",
            chunk_sha256="8" * 64,
            token_count=2,
            character_count=13,
        )
        session.add(duplicate_chunk)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    # Test cascade delete: deleting episode should delete chunks
    with db_session_factory() as session:
        ep_to_del = session.get(Episode, ep_id)
        session.delete(ep_to_del)
        session.commit()

    with db_session_factory() as session:
        assert session.get(TranscriptChunk, chunk_id) is None


def test_ingestion_run_lifecycle(db_session_factory) -> None:
    with db_session_factory() as session:
        run = IngestionRun(
            status="running",
            total_episodes=303,
            success_count=0,
            skipped_count=0,
            failed_count=0,
        )
        session.add(run)
        session.commit()
        run_id = run.id

    with db_session_factory() as session:
        loaded = session.get(IngestionRun, run_id)
        assert loaded is not None
        loaded.status = "completed"
        loaded.success_count = 300
        loaded.skipped_count = 3
        loaded.error_summary = {"skipped": ["duplicate_body"]}
        session.commit()

    with db_session_factory() as session:
        verified = session.get(IngestionRun, run_id)
        assert verified is not None
        assert verified.status == "completed"
        assert verified.success_count == 300
        assert verified.error_summary == {"skipped": ["duplicate_body"]}
        session.delete(verified)
        session.commit()
