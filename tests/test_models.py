from __future__ import annotations

import pytest

from backend.app.models import Episode, IngestionRun, TranscriptChunk


def test_episode_valid_initialization() -> None:
    episode = Episode(
        source_path="episodes/brian-chesky/transcript.md",
        guest="Brian Chesky",
        title="Leading Airbnb Through Crisis",
        source_platform="youtube",
        source_url="https://youtube.com/watch?v=123",
        youtube_video_id="123",
        raw_metadata={"guest": "Brian Chesky", "channel": "Lenny's Podcast"},
        source_sha256="a" * 64,
        body_sha256="b" * 64,
        embedding_model="nomic-embed-text:v1.5",
        chunker_version="v1",
    )
    assert episode.source_path == "episodes/brian-chesky/transcript.md"
    assert episode.guest == "Brian Chesky"
    assert episode.source_platform == "youtube"
    assert episode.raw_metadata["guest"] == "Brian Chesky"


def test_episode_source_path_normalizes_windows_backslashes() -> None:
    episode = Episode(
        source_path="episodes\\brian-chesky\\transcript.md",
        guest="Brian Chesky",
        title="Title",
        source_sha256="a" * 64,
        body_sha256="b" * 64,
    )
    assert episode.source_path == "episodes/brian-chesky/transcript.md"


def test_episode_source_path_rejects_empty_string() -> None:
    with pytest.raises(ValueError, match="source_path must be a non-empty string"):
        Episode(
            source_path="",
            guest="Guest",
            title="Title",
            source_sha256="a" * 64,
            body_sha256="b" * 64,
        )

    with pytest.raises(ValueError, match="source_path must be a non-empty string"):
        Episode(
            source_path="   ",
            guest="Guest",
            title="Title",
            source_sha256="a" * 64,
            body_sha256="b" * 64,
        )


def test_episode_source_path_rejects_absolute_posix_path() -> None:
    with pytest.raises(ValueError, match="must be a relative path, got absolute path"):
        Episode(
            source_path="/data/raw/episodes/guest/transcript.md",
            guest="Guest",
            title="Title",
            source_sha256="a" * 64,
            body_sha256="b" * 64,
        )


def test_episode_source_path_rejects_windows_drive_path() -> None:
    with pytest.raises(ValueError, match="must be a relative path, got absolute path"):
        Episode(
            source_path="E:\\Lenddy's Growth assistant\\data\\raw\\episodes\\guest\\transcript.md",
            guest="Guest",
            title="Title",
            source_sha256="a" * 64,
            body_sha256="b" * 64,
        )


def test_episode_source_path_rejects_path_traversal() -> None:
    with pytest.raises(ValueError, match="cannot escape root with '\\.\\.'"):
        Episode(
            source_path="episodes/../../secrets.txt",
            guest="Guest",
            title="Title",
            source_sha256="a" * 64,
            body_sha256="b" * 64,
        )


def test_episode_nullable_metadata_fields() -> None:
    # All optional fields set to None
    episode = Episode(
        source_path="episodes/anonymous/transcript.md",
        guest="Anonymous",
        title="Untracked Episode",
        source_platform="spotify",
        source_url=None,
        youtube_video_id=None,
        spotify_url=None,
        spotify_id=None,
        publish_date=None,
        duration_seconds=None,
        raw_metadata={},
        source_sha256="a" * 64,
        body_sha256="b" * 64,
    )
    assert episode.source_url is None
    assert episode.youtube_video_id is None
    assert episode.publish_date is None
    assert episode.duration_seconds is None


def test_transcript_chunk_nullable_fields_and_embedding_type() -> None:
    chunk = TranscriptChunk(
        episode_id=1,
        chunk_index=0,
        chunk_text="Welcome to the podcast.",
        chunk_sha256="c" * 64,
        token_count=5,
        character_count=23,
        speaker=None,
        start_time_seconds=None,
        embedding=None,
        embedding_model="nomic-embed-text:v1.5",
    )
    assert chunk.speaker is None
    assert chunk.start_time_seconds is None
    assert chunk.embedding is None

    # Check vector column type dimension
    col_type = TranscriptChunk.__table__.columns["embedding"].type
    assert hasattr(col_type, "dim")
    assert col_type.dim == 768


def test_ingestion_run_defaults() -> None:
    run = IngestionRun(
        status="running",
        total_episodes=10,
    )
    assert run.status == "running"
    assert run.total_episodes == 10
    assert run.finished_at is None
    assert run.error_summary is None
