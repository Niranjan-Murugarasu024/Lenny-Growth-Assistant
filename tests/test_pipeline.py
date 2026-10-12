from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
import uuid

import pytest
from sqlalchemy import select

from backend.app.config import get_settings
from backend.app.database import create_db_engine, create_session_factory
from backend.app.ingestion.embedder import OllamaEmbedder
from backend.app.ingestion.pipeline import run_ingestion_pipeline
from backend.app.models import Episode, IngestionRun, TranscriptChunk


def _make_dummy_vector(dim: int = 768) -> list[float]:
    return [0.01] * dim





@pytest.fixture
def mock_embedder() -> MagicMock:
    embedder = MagicMock(spec=OllamaEmbedder)
    embedder.model = "nomic-embed-text:v1.5"
    embedder.embed_documents.side_effect = lambda texts: [_make_dummy_vector(768) for _ in texts]
    return embedder


def create_test_transcript_file(
    root: Path,
    guest_dir: str,
    guest: str = "Test Guest",
    title: str = "Test Episode",
    dialogue: str = "Lenny (00:00:00):\nWelcome to the show.",
    youtube_id: str | None = "vid123",
) -> Path:
    ep_dir = root / "episodes" / guest_dir
    ep_dir.mkdir(parents=True, exist_ok=True)
    file_path = ep_dir / "transcript.md"

    yt_line = f"video_id: {youtube_id}\nyoutube_url: https://youtube.com/watch?v={youtube_id}" if youtube_id else "spotify_url: https://open.spotify.com/episode/abc123"
    content = f"""---
guest: {guest}
title: {title}
{yt_line}
publish_date: 2024-01-01
---
{dialogue}
"""
    file_path.write_text(content, encoding="utf-8")
    return file_path


def test_pipeline_single_episode_ingestion(tmp_path: Path, db_session_factory, mock_embedder) -> None:
    unique_key = uuid.uuid4().hex[:8]
    guest_folder = f"test-ep-{unique_key}"
    create_test_transcript_file(tmp_path, guest_folder, guest=f"Guest {unique_key}")

    result = run_ingestion_pipeline(
        archive_root=tmp_path,
        episodes_dir=tmp_path / "episodes",
        session_factory=db_session_factory,
        embedder=mock_embedder,
    )

    assert result.status == "completed"
    assert result.total_episodes == 1
    assert result.success_count == 1
    assert result.skipped_count == 0
    assert result.failed_count == 0
    assert result.run_id is not None
    assert mock_embedder.embed_documents.called

    source_path = f"episodes/{guest_folder}/transcript.md"
    with db_session_factory() as session:
        ep = session.query(Episode).filter_by(source_path=source_path).first()
        assert ep is not None
        assert ep.guest == f"Guest {unique_key}"

        chunks = session.query(TranscriptChunk).filter_by(episode_id=ep.id).all()
        assert len(chunks) >= 1
        assert chunks[0].embedding is not None
        assert len(chunks[0].embedding) == 768

        run = session.query(IngestionRun).filter_by(id=result.run_id).one()
        assert run.status == "completed"
        assert run.success_count == 1


def test_pipeline_idempotency_skips_unchanged(tmp_path: Path, db_session_factory, mock_embedder) -> None:
    unique_key = uuid.uuid4().hex[:8]
    guest_folder = f"test-ep-{unique_key}"
    create_test_transcript_file(tmp_path, guest_folder, guest=f"Guest {unique_key}")

    # First run: should ingest
    res1 = run_ingestion_pipeline(
        archive_root=tmp_path,
        episodes_dir=tmp_path / "episodes",
        session_factory=db_session_factory,
        embedder=mock_embedder,
    )
    assert res1.success_count == 1
    mock_embedder.embed_documents.reset_mock()

    # Second run: should skip unchanged episode without calling embedder
    res2 = run_ingestion_pipeline(
        archive_root=tmp_path,
        episodes_dir=tmp_path / "episodes",
        session_factory=db_session_factory,
        embedder=mock_embedder,
    )
    assert res2.status == "completed"
    assert res2.skipped_count == 1
    assert res2.success_count == 0
    assert not mock_embedder.embed_documents.called


def test_pipeline_metadata_refresh_without_reembedding(tmp_path: Path, db_session_factory, mock_embedder) -> None:
    unique_key = uuid.uuid4().hex[:8]
    guest_folder = f"test-ep-{unique_key}"
    create_test_transcript_file(
        tmp_path,
        guest_folder,
        guest=f"Guest {unique_key}",
        title="Original Title",
        dialogue="Speaker (00:00:00):\nIdentical dialogue text.",
    )

    # First run
    run_ingestion_pipeline(
        archive_root=tmp_path,
        episodes_dir=tmp_path / "episodes",
        session_factory=db_session_factory,
        embedder=mock_embedder,
    )
    mock_embedder.embed_documents.reset_mock()

    # Change only metadata (title), keeping dialogue identical
    create_test_transcript_file(
        tmp_path,
        guest_folder,
        guest=f"Guest {unique_key}",
        title="Updated Title For Episode",
        dialogue="Speaker (00:00:00):\nIdentical dialogue text.",
    )

    res = run_ingestion_pipeline(
        archive_root=tmp_path,
        episodes_dir=tmp_path / "episodes",
        session_factory=db_session_factory,
        embedder=mock_embedder,
    )

    assert res.success_count == 1
    # Embedder must NOT be called for metadata-only updates
    assert not mock_embedder.embed_documents.called

    source_path = f"episodes/{guest_folder}/transcript.md"
    with db_session_factory() as session:
        ep = session.query(Episode).filter_by(source_path=source_path).one()
        assert ep.title == "Updated Title For Episode"


def test_pipeline_dialogue_change_rebuilds_chunks(tmp_path: Path, db_session_factory, mock_embedder) -> None:
    unique_key = uuid.uuid4().hex[:8]
    guest_folder = f"test-ep-{unique_key}"
    create_test_transcript_file(
        tmp_path,
        guest_folder,
        guest=f"Guest {unique_key}",
        dialogue="Speaker (00:00:00):\nInitial dialogue content.",
    )

    # First run
    run_ingestion_pipeline(
        archive_root=tmp_path,
        episodes_dir=tmp_path / "episodes",
        session_factory=db_session_factory,
        embedder=mock_embedder,
    )
    mock_embedder.embed_documents.reset_mock()

    # Modify dialogue body
    create_test_transcript_file(
        tmp_path,
        guest_folder,
        guest=f"Guest {unique_key}",
        dialogue="Speaker (00:00:00):\nCompletely new and modified dialogue content.",
    )

    res = run_ingestion_pipeline(
        archive_root=tmp_path,
        episodes_dir=tmp_path / "episodes",
        session_factory=db_session_factory,
        embedder=mock_embedder,
    )

    assert res.success_count == 1
    # Embedder MUST be called because dialogue changed
    assert mock_embedder.embed_documents.called


def test_pipeline_duplicate_dialogue_pair_preserved(tmp_path: Path, db_session_factory, mock_embedder) -> None:
    unique_key = uuid.uuid4().hex[:8]
    folder_a = f"dup-a-{unique_key}"
    folder_b = f"dup-b-{unique_key}"
    identical_dialogue = "Andy (00:00:00):\nThe greatest sales deck ever pitched."

    create_test_transcript_file(tmp_path, folder_a, guest="Andy A", dialogue=identical_dialogue)
    create_test_transcript_file(tmp_path, folder_b, guest="Andy B", dialogue=identical_dialogue)

    res = run_ingestion_pipeline(
        archive_root=tmp_path,
        episodes_dir=tmp_path / "episodes",
        session_factory=db_session_factory,
        embedder=mock_embedder,
    )

    assert res.total_episodes == 2
    assert res.success_count == 2
    assert res.failed_count == 0

    path_a = f"episodes/{folder_a}/transcript.md"
    path_b = f"episodes/{folder_b}/transcript.md"

    with db_session_factory() as session:
        ep_a = session.query(Episode).filter_by(source_path=path_a).first()
        ep_b = session.query(Episode).filter_by(source_path=path_b).first()

        assert ep_a is not None
        assert ep_b is not None
        assert ep_a.id != ep_b.id
        assert ep_a.body_sha256 == ep_b.body_sha256

        chunks_a = session.query(TranscriptChunk).filter_by(episode_id=ep_a.id).all()
        chunks_b = session.query(TranscriptChunk).filter_by(episode_id=ep_b.id).all()
        assert len(chunks_a) >= 1
        assert len(chunks_b) >= 1


def test_pipeline_dry_run_mode(tmp_path: Path, db_session_factory, mock_embedder) -> None:
    unique_key = uuid.uuid4().hex[:8]
    guest_folder = f"dry-run-{unique_key}"
    create_test_transcript_file(tmp_path, guest_folder)

    res = run_ingestion_pipeline(
        archive_root=tmp_path,
        episodes_dir=tmp_path / "episodes",
        session_factory=db_session_factory,
        embedder=mock_embedder,
        dry_run=True,
    )

    assert res.status == "dry_run"
    assert res.run_id is None
    # No embedding calls
    assert not mock_embedder.embed_documents.called

    source_path = f"episodes/{guest_folder}/transcript.md"
    with db_session_factory() as session:
        ep = session.query(Episode).filter_by(source_path=source_path).first()
        assert ep is None  # Nothing written to DB


def test_database_isolation_does_not_pollute_application_db(
    tmp_path: Path,
    db_session_factory,
    mock_embedder,
) -> None:
    """Regression test: verify running pipeline tests does NOT modify the application database."""
    app_factory = create_session_factory()  # default settings -> application DB lenny_growth

    with app_factory() as app_session:
        app_episodes_before = app_session.query(Episode).count()
        app_chunks_before = app_session.query(TranscriptChunk).count()
        app_runs_before = app_session.query(IngestionRun).count()

    # Ingest a new test episode into the test-isolated session factory
    unique_key = uuid.uuid4().hex[:8]
    create_test_transcript_file(tmp_path, f"isolation-test-{unique_key}")

    res = run_ingestion_pipeline(
        archive_root=tmp_path,
        episodes_dir=tmp_path / "episodes",
        session_factory=db_session_factory,
        embedder=mock_embedder,
    )
    assert res.success_count == 1

    # Verify that the test record was written to the test DB
    with db_session_factory() as test_session:
        test_episodes = test_session.query(Episode).count()
        assert test_episodes >= 1

    # Assert that the application database was completely untouched
    with app_factory() as app_session:
        app_episodes_after = app_session.query(Episode).count()
        app_chunks_after = app_session.query(TranscriptChunk).count()
        app_runs_after = app_session.query(IngestionRun).count()

        assert app_episodes_after == app_episodes_before
        assert app_chunks_after == app_chunks_before
        assert app_runs_after == app_runs_before


def test_pipeline_partial_failure_isolation_and_atomic_rollback(
    tmp_path: Path,
    db_session_factory,
) -> None:
    """Verify that an episode failure rolls back atomically without breaking successful episodes."""
    key1 = uuid.uuid4().hex[:8]
    key2 = uuid.uuid4().hex[:8]
    folder_ok = f"ep-ok-{key1}"
    folder_fail = f"ep-fail-{key2}"

    create_test_transcript_file(tmp_path, folder_ok, guest=f"Good Guest {key1}")
    create_test_transcript_file(
        tmp_path,
        folder_fail,
        guest=f"Bad Guest {key2}",
        dialogue="Bad Guest (00:00:00):\nThis dialogue text mentions Bad Guest.",
    )

    embedder = MagicMock(spec=OllamaEmbedder)
    embedder.model = "nomic-embed-text:v1.5"

    def embed_side_effect(texts: list[str]) -> list[list[float]]:
        # Fail if text contains Bad Guest
        for t in texts:
            if "Bad Guest" in t:
                raise RuntimeError("Simulated Ollama embedding failure")
        return [_make_dummy_vector(768) for _ in texts]

    embedder.embed_documents.side_effect = embed_side_effect

    res = run_ingestion_pipeline(
        archive_root=tmp_path,
        episodes_dir=tmp_path / "episodes",
        session_factory=db_session_factory,
        embedder=embedder,
    )

    assert res.total_episodes == 2
    assert res.success_count == 1
    assert res.failed_count == 1
    assert res.status == "completed_with_errors"

    path_ok = f"episodes/{folder_ok}/transcript.md"
    path_fail = f"episodes/{folder_fail}/transcript.md"

    with db_session_factory() as session:
        # Good episode is preserved with its chunks
        ep_ok = session.query(Episode).filter_by(source_path=path_ok).first()
        assert ep_ok is not None
        chunks_ok = session.query(TranscriptChunk).filter_by(episode_id=ep_ok.id).all()
        assert len(chunks_ok) >= 1

        # Failed episode was rolled back atomically
        ep_fail = session.query(Episode).filter_by(source_path=path_fail).first()
        assert ep_fail is None

        # Run record accurately reflects failure
        run = session.query(IngestionRun).filter_by(id=res.run_id).one()
        assert run.status == "completed_with_errors"
        assert run.failed_count == 1
        assert run.error_summary is not None
        assert path_fail in run.error_summary


def test_pipeline_retry_after_failure_recovers_cleanly(
    tmp_path: Path,
    db_session_factory,
) -> None:
    """Verify that an episode which failed on a previous run can be retried and ingested cleanly."""
    key = uuid.uuid4().hex[:8]
    folder = f"retry-ep-{key}"
    create_test_transcript_file(tmp_path, folder, guest=f"Retry Guest {key}")

    failing_embedder = MagicMock(spec=OllamaEmbedder)
    failing_embedder.model = "nomic-embed-text:v1.5"
    failing_embedder.embed_documents.side_effect = RuntimeError("Temporary Ollama crash")

    # Run 1: Fails
    res1 = run_ingestion_pipeline(
        archive_root=tmp_path,
        episodes_dir=tmp_path / "episodes",
        session_factory=db_session_factory,
        embedder=failing_embedder,
    )
    assert res1.failed_count == 1
    assert res1.success_count == 0

    # Run 2: Recovered embedder -> Retry succeeds
    working_embedder = MagicMock(spec=OllamaEmbedder)
    working_embedder.model = "nomic-embed-text:v1.5"
    working_embedder.embed_documents.side_effect = lambda texts: [_make_dummy_vector(768) for _ in texts]

    res2 = run_ingestion_pipeline(
        archive_root=tmp_path,
        episodes_dir=tmp_path / "episodes",
        session_factory=db_session_factory,
        embedder=working_embedder,
    )
    assert res2.status == "completed"
    assert res2.success_count == 1
    assert res2.failed_count == 0

    source_path = f"episodes/{folder}/transcript.md"
    with db_session_factory() as session:
        ep = session.query(Episode).filter_by(source_path=source_path).one()
        assert ep.guest == f"Retry Guest {key}"
        chunks = session.query(TranscriptChunk).filter_by(episode_id=ep.id).all()
        assert len(chunks) >= 1


def test_pipeline_corpus_discovery_and_manifest_alignment() -> None:
    """Verify that file discovery accurately mirrors data/manifest.json for all 303 episodes."""
    import json
    from backend.app.ingestion.pipeline import discover_transcript_files

    manifest_path = Path("data/manifest.json")
    if not manifest_path.exists():
        pytest.skip("data/manifest.json not present")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    manifest_paths = {ep["source_path"] for ep in manifest_data["episodes"]}
    archive_root = Path("data/raw/lennys-podcast-transcripts").resolve()
    discovered_files = discover_transcript_files(archive_root / "episodes")
    discovered_rel_paths = {
        f.relative_to(archive_root).as_posix()
        for f in discovered_files
    }

    assert len(discovered_rel_paths) == 303
    assert discovered_rel_paths == manifest_paths
