from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from backend.app.ingestion.parser import (
    DialogueTurn,
    ParsedTranscript,
    extract_dialogue_turns,
    parse_timestamp_to_seconds,
    parse_transcript_source,
)


def create_test_transcript(
    tmp_path: Path,
    content: str,
    subpath: str = "episodes/test-guest/transcript.md",
    encoding: str = "utf-8",
) -> tuple[Path, Path]:
    archive_root = tmp_path / "archive"
    full_path = archive_root / subpath
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content, encoding=encoding)
    return full_path, archive_root


def test_parse_valid_frontmatter_and_metadata(tmp_path: Path) -> None:
    content = """---
guest: Ada Chen Rekhi
title: Feeling stuck? Here's how to know when it's time to leave your job
youtube_url: https://www.youtube.com/watch?v=abc123xyz
video_id: abc123xyz
publish_date: 2024-05-15
duration_seconds: 3600
duration: "01:00:00"
---
# Feeling stuck?

## Transcript

Ada Chen Rekhi (00:00:00):
It's a terrible outcome to wake up one day and be late career and feel trapped.

Lenny (00:00:36):
Welcome to Lenny's Podcast!
"""
    file_path, archive_root = create_test_transcript(tmp_path, content)
    parsed = parse_transcript_source(file_path, archive_root)

    assert parsed.guest == "Ada Chen Rekhi"
    assert parsed.title == "Feeling stuck? Here's how to know when it's time to leave your job"
    assert parsed.youtube_video_id == "abc123xyz"
    assert parsed.source_platform == "youtube"
    assert parsed.publish_date == date(2024, 5, 15)
    assert parsed.duration_seconds == 3600.0
    assert parsed.frontmatter_found is True
    assert parsed.missing_required_metadata == []
    assert parsed.parse_error is None
    assert parsed.raw_metadata["guest"] == "Ada Chen Rekhi"
    assert len(parsed.turns) >= 3


def test_parse_path_traversal_rejection(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    outside_file = tmp_path / "outside.md"
    outside_file.write_text("outside transcript")

    with pytest.raises(ValueError, match="outside archive root"):
        parse_transcript_source(outside_file, archive_root)


def test_parse_timestamp_to_seconds() -> None:
    assert parse_timestamp_to_seconds("00:00:00") == 0.0
    assert parse_timestamp_to_seconds("00:01:21") == 81.0
    assert parse_timestamp_to_seconds("01:30:15") == 5415.0
    assert parse_timestamp_to_seconds("03:50") == 230.0
    assert parse_timestamp_to_seconds("12:34") == 754.0
    assert parse_timestamp_to_seconds(None) is None
    assert parse_timestamp_to_seconds("") is None
    assert parse_timestamp_to_seconds("invalid") is None
    assert parse_timestamp_to_seconds("1:2:3:4") is None


def test_parse_malformed_yaml(tmp_path: Path) -> None:
    content = """---
guest: [invalid yaml {unclosed
title: Broken
---
Some dialogue here.
"""
    file_path, archive_root = create_test_transcript(tmp_path, content)
    parsed = parse_transcript_source(file_path, archive_root)

    assert parsed.parse_error is not None
    assert "YAML" in parsed.parse_error
    assert parsed.dialogue_body.strip() == "Some dialogue here."


def test_parse_missing_required_metadata(tmp_path: Path) -> None:
    content = """---
guest: Partial Guest
---
Dialogue line without full metadata.
"""
    file_path, archive_root = create_test_transcript(tmp_path, content)
    parsed = parse_transcript_source(file_path, archive_root)

    assert parsed.guest == "Partial Guest"
    assert "title" in parsed.missing_required_metadata
    assert "youtube_url" in parsed.missing_required_metadata
    assert "video_id" in parsed.missing_required_metadata
    assert "publish_date" in parsed.missing_required_metadata


def test_parse_spotify_exclusive_episode(tmp_path: Path) -> None:
    content = """---
guest: Nickey Skarstad
title: The craft of product management
spotify_url: https://open.spotify.com/episode/4aB3c
publish_date: 2023-10-01
---
Nickey (00:00:00):
Product management requires deep empathy.
"""
    file_path, archive_root = create_test_transcript(tmp_path, content)
    parsed = parse_transcript_source(file_path, archive_root)

    assert parsed.guest == "Nickey Skarstad"
    assert parsed.source_platform == "spotify"
    assert parsed.spotify_url == "https://open.spotify.com/episode/4aB3c"
    assert parsed.spotify_id == "4aB3c"
    assert parsed.youtube_video_id is None


def test_parse_unicode_content(tmp_path: Path) -> None:
    content = """---
guest: Gustav Söderström
title: AI & Innovation at Spotify — "The future is here"
youtube_url: https://www.youtube.com/watch?v=gustav123
video_id: gustav123
publish_date: 2024-01-10
---
Gustav Söderström (00:00:00):
We're exploring large language models… it’s truly exciting! 🚀
"""
    file_path, archive_root = create_test_transcript(tmp_path, content)
    parsed = parse_transcript_source(file_path, archive_root)

    assert parsed.guest == "Gustav Söderström"
    assert "—" in parsed.title
    assert "🚀" in parsed.dialogue_body
    assert parsed.turns[0].speaker == "Gustav Söderström"
    assert "Söderström" in parsed.turns[0].text


def test_parse_empty_dialogue_body(tmp_path: Path) -> None:
    content = """---
guest: Empty Guest
title: Empty Episode
---
"""
    file_path, archive_root = create_test_transcript(tmp_path, content)
    parsed = parse_transcript_source(file_path, archive_root)

    assert parsed.dialogue_body == ""
    assert parsed.turns == []
    assert parsed.word_count == 0


def test_body_hash_vs_source_hash(tmp_path: Path) -> None:
    content_a = """---
guest: Guest One
title: Episode A
youtube_url: https://youtube.com/watch?v=aaa
video_id: aaa
publish_date: 2024-01-01
---
Speaker (00:00:00):
Identical dialogue body here.
"""
    content_b = """---
guest: Guest Two
title: Episode B
youtube_url: https://youtube.com/watch?v=bbb
video_id: bbb
publish_date: 2024-02-01
---
Speaker (00:00:00):
Identical dialogue body here.
"""
    file_a, root = create_test_transcript(tmp_path, content_a, subpath="episodes/ep-a/transcript.md")
    file_b, _ = create_test_transcript(tmp_path, content_b, subpath="episodes/ep-b/transcript.md")

    parsed_a = parse_transcript_source(file_a, root)
    parsed_b = parse_transcript_source(file_b, root)

    assert parsed_a.source_sha256 != parsed_b.source_sha256
    assert parsed_a.body_sha256 == parsed_b.body_sha256
    assert len(parsed_a.body_sha256) == 64


def test_extract_dialogue_turns_headings_and_speakers() -> None:
    text = """# Episode Header

## Section 1

Adam Fishman (00:00:00):
Welcome to the discussion.

(00:00:15):
Continuing the same thought here.

Lenny (00:00:30):
Thanks Adam.
"""
    turns = extract_dialogue_turns(text)

    # First turn is heading # Episode Header
    assert turns[0].is_heading is True
    assert "# Episode Header" in turns[0].text

    # Second turn is heading ## Section 1
    assert turns[1].is_heading is True
    assert "## Section 1" in turns[1].text

    # Third turn is Adam Fishman at 0.0s
    assert turns[2].speaker == "Adam Fishman"
    assert turns[2].start_time_seconds == 0.0
    assert "Welcome to the discussion." in turns[2].text

    # Fourth turn is continuation turn at 15.0s, retains speaker Adam Fishman
    assert turns[3].speaker == "Adam Fishman"
    assert turns[3].start_time_seconds == 15.0

    # Fifth turn is Lenny at 30.0s
    assert turns[4].speaker == "Lenny"
    assert turns[4].start_time_seconds == 30.0
