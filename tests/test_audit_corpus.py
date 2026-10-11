from datetime import date, datetime, timezone
import json
from pathlib import Path

import pytest

from scripts.audit_corpus import (
    build_manifest,
    display_value,
    is_missing,
    json_safe,
    main,
    parse_transcript,
)


def create_transcript(
    tmp_path: Path,
    content: str,
    guest_dir: str = "example-guest",
    filename: str = "transcript.md",
    encoding: str = "utf-8",
) -> tuple[Path, Path]:
    archive_root = tmp_path / "archive"

    transcript_path = (
        archive_root
        / "episodes"
        / guest_dir
        / filename
    )

    transcript_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    transcript_path.write_text(
        content,
        encoding=encoding,
    )

    return transcript_path, archive_root


def test_valid_frontmatter_is_parsed(
    tmp_path: Path,
) -> None:
    content = """---
guest: Example Guest
title: Example Episode
youtube_url: https://www.youtube.com/watch?v=abc123
video_id: abc123
publish_date: 2025-01-02
keywords:
  - growth
  - pm
---
This is an example transcript.
At 00:01:20 the guest discusses product strategy.
"""

    path, archive_root = create_transcript(
        tmp_path,
        content,
    )

    record = parse_transcript(path, archive_root)

    assert record["frontmatter_found"] is True
    assert record["guest"] == "Example Guest"
    assert record["title"] == "Example Episode"
    assert record["youtube_url"] == "https://www.youtube.com/watch?v=abc123"
    assert record["video_id"] == "abc123"
    assert record["publish_date"] == "2025-01-02"
    assert record["parse_error"] is None
    assert record["missing_required_metadata"] == []
    assert record["word_count"] > 0
    assert record["character_count"] > 0
    assert record["empty_body"] is False
    assert record["potential_timestamp_matches"] >= 1
    assert len(record["source_sha256"]) == 64
    assert record["source_path"] == "episodes/example-guest/transcript.md"
    assert record["metadata"]["keywords"] == ["growth", "pm"]


def test_missing_metadata_is_reported(
    tmp_path: Path,
) -> None:
    content = """---
guest: Example Guest
---
Example transcript text.
"""

    path, archive_root = create_transcript(
        tmp_path,
        content,
    )

    record = parse_transcript(path, archive_root)

    assert record["frontmatter_found"] is True
    assert record["parse_error"] is None
    assert "title" in record["missing_required_metadata"]
    assert "video_id" in record["missing_required_metadata"]
    assert "youtube_url" in record["missing_required_metadata"]
    assert "publish_date" in record["missing_required_metadata"]


def test_whitespace_or_empty_string_metadata_is_missing(
    tmp_path: Path,
) -> None:
    content = """---
guest: ""
title: "   "
youtube_url: null
video_id: ""
publish_date: 2025-01-02
---
Some dialogue here.
"""

    path, archive_root = create_transcript(
        tmp_path,
        content,
    )

    record = parse_transcript(path, archive_root)

    assert record["frontmatter_found"] is True
    assert "guest" in record["missing_required_metadata"]
    assert "title" in record["missing_required_metadata"]
    assert "youtube_url" in record["missing_required_metadata"]
    assert "video_id" in record["missing_required_metadata"]
    assert "publish_date" not in record["missing_required_metadata"]


def test_malformed_yaml_is_reported(
    tmp_path: Path,
) -> None:
    content = """---
guest: [unclosed
---
The transcript body should still be preserved.
"""

    path, archive_root = create_transcript(
        tmp_path,
        content,
    )

    record = parse_transcript(path, archive_root)

    assert record["frontmatter_found"] is True
    assert record["parse_error"] is not None
    assert "YAML parse error" in record["parse_error"]
    assert record["word_count"] > 0
    assert len(record["source_sha256"]) == 64


def test_non_mapping_yaml_frontmatter_is_reported(
    tmp_path: Path,
) -> None:
    content = """---
- item 1
- item 2
---
Transcript dialogue following a YAML list instead of a dict.
"""

    path, archive_root = create_transcript(
        tmp_path,
        content,
    )

    record = parse_transcript(path, archive_root)

    assert record["frontmatter_found"] is True
    assert record["parse_error"] is not None
    assert "YAML frontmatter must be a mapping" in record["parse_error"]
    assert record["word_count"] > 0


def test_empty_frontmatter_delimiters_only(
    tmp_path: Path,
) -> None:
    content = "---\n---\nTranscript text with empty delimiters.\n"

    path, archive_root = create_transcript(
        tmp_path,
        content,
    )

    record = parse_transcript(path, archive_root)

    assert record["frontmatter_found"] is True
    assert record["parse_error"] is None
    assert record["metadata"] == {}
    assert len(record["missing_required_metadata"]) == 5
    assert record["word_count"] > 0


def test_missing_frontmatter_delimiters(
    tmp_path: Path,
) -> None:
    content = """# Plain Transcript Without Frontmatter
Speaker 1 (00:00:10): Hello world!
Speaker 2 (00:00:15): Welcome!
"""

    path, archive_root = create_transcript(
        tmp_path,
        content,
    )

    record = parse_transcript(path, archive_root)

    assert record["frontmatter_found"] is False
    assert record["parse_error"] == "Missing YAML frontmatter delimiters"
    assert record["word_count"] > 0
    assert record["potential_timestamp_matches"] == 2
    assert len(record["missing_required_metadata"]) == 5


def test_empty_file(
    tmp_path: Path,
) -> None:
    path, archive_root = create_transcript(
        tmp_path,
        "",
    )

    record = parse_transcript(path, archive_root)

    assert record["frontmatter_found"] is False
    assert record["empty_body"] is True
    assert record["word_count"] == 0
    assert record["character_count"] == 0
    assert record["potential_timestamp_matches"] == 0
    assert len(record["source_sha256"]) == 64


def test_empty_body_with_valid_frontmatter(
    tmp_path: Path,
) -> None:
    content = """---
guest: Solo Speaker
title: Silent Episode
youtube_url: https://example.com/yt
video_id: abc
publish_date: 2025-01-01
---
"""

    path, archive_root = create_transcript(
        tmp_path,
        content,
    )

    record = parse_transcript(path, archive_root)

    assert record["frontmatter_found"] is True
    assert record["empty_body"] is True
    assert record["word_count"] == 0
    assert record["character_count"] == 0


def test_utf8_bom_handling(
    tmp_path: Path,
) -> None:
    content = "\ufeff---\nguest: BOM Guest\ntitle: BOM Episode\nyoutube_url: https://yt\nvideo_id: 123\npublish_date: 2025-01-01\n---\nDialogue after BOM.\n"

    path = tmp_path / "archive" / "episodes" / "bom-guest" / "transcript.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))

    record = parse_transcript(path, tmp_path / "archive")

    assert record["frontmatter_found"] is True
    assert record["guest"] == "BOM Guest"
    assert record["parse_error"] is None


def test_unicode_and_emojis(
    tmp_path: Path,
) -> None:
    content = """---
guest: René & Chloë 🎙️
title: "The «Future» of AI — 2025"
youtube_url: https://youtube.com/watch?v=123
video_id: 123
publish_date: 2025-01-01
---
René (00:00:05): ¡Hola! Let’s explore 🚀.
"""

    path, archive_root = create_transcript(
        tmp_path,
        content,
    )

    record = parse_transcript(path, archive_root)

    assert record["frontmatter_found"] is True
    assert "René" in record["guest"]
    assert "🎙️" in record["guest"]
    assert record["parse_error"] is None
    assert record["word_count"] > 0


def test_timestamp_detection_variations(
    tmp_path: Path,
) -> None:
    content = """---
guest: Time Traveler
title: Timestamp Testing
youtube_url: https://yt
video_id: 1
publish_date: 2025-01-01
---
Timestamps to catch:
00:15
01:23:45
5:30
1:02:49

Not timestamps:
1:1 ratio
Version 2.0.1
Section 4.12
"""

    path, archive_root = create_transcript(
        tmp_path,
        content,
    )

    record = parse_transcript(path, archive_root)

    assert record["potential_timestamp_matches"] == 4


def test_json_safe_and_display_value_edge_types() -> None:
    now = datetime(2025, 5, 1, 12, 30, tzinfo=timezone.utc)
    d = date(2025, 5, 1)

    assert json_safe(now) == now.isoformat()
    assert json_safe(d) == "2025-05-01"
    assert json_safe((1, 2, 3)) == [1, 2, 3]
    assert json_safe({"a": d}) == {"a": "2025-05-01"}
    assert json_safe(42) == 42
    assert json_safe(None) is None

    assert display_value(d) == "2025-05-01"
    assert display_value(None) == ""
    assert display_value(["tag1", "tag2"]) == '["tag1", "tag2"]'
    assert display_value({"key": "val"}) == '{"key": "val"}'

    assert is_missing(None) is True
    assert is_missing("") is True
    assert is_missing("   ") is True
    assert is_missing([]) is True
    assert is_missing({}) is True
    assert is_missing(set()) is True
    assert is_missing("valid") is False
    assert is_missing(0) is False
    assert is_missing(False) is False


def test_build_manifest_success_and_duplicates(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "archive"
    episodes_dir = archive_root / "episodes"

    # Create two identical episodes to test duplicate detection
    identical_content = """---
guest: Identical Guest
title: Shared Episode
youtube_url: https://yt/1
video_id: 1
publish_date: 2025-01-01
---
Identical dialogue (00:01:00).
"""
    unique_content = """---
guest: Unique Guest
title: Unique Episode
youtube_url: https://yt/2
video_id: 2
publish_date: 2025-01-02
---
Unique dialogue (00:02:00).
"""

    (episodes_dir / "ep1").mkdir(parents=True)
    (episodes_dir / "ep1" / "transcript.md").write_text(identical_content, encoding="utf-8")

    (episodes_dir / "ep2").mkdir(parents=True)
    (episodes_dir / "ep2" / "transcript.md").write_text(identical_content, encoding="utf-8")

    (episodes_dir / "ep3").mkdir(parents=True)
    (episodes_dir / "ep3" / "transcript.md").write_text(unique_content, encoding="utf-8")

    manifest = build_manifest(archive_root, episodes_dir)

    assert manifest["schema_version"] == 1
    assert manifest["summary"]["episode_files"] == 3
    assert manifest["summary"]["unique_source_hashes"] == 2
    assert manifest["summary"]["duplicate_content_groups"] == 1

    assert len(manifest["duplicate_groups"]) == 1
    dup_group = manifest["duplicate_groups"][0]
    assert dup_group["source_paths"] == [
        "episodes/ep1/transcript.md",
        "episodes/ep2/transcript.md",
    ]

    assert len(manifest["episodes"]) == 3
    for ep in manifest["episodes"]:
        assert "\\" not in ep["source_path"]
        assert not ep["source_path"].startswith("/")


def test_build_manifest_missing_directories(
    tmp_path: Path,
) -> None:
    non_existent = tmp_path / "does_not_exist"
    valid_dir = tmp_path / "valid"
    valid_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="Transcript repository not found"):
        build_manifest(non_existent, valid_dir)

    with pytest.raises(FileNotFoundError, match="Episode directory not found"):
        build_manifest(valid_dir, non_existent)


def test_build_manifest_no_transcripts_found(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "archive"
    episodes_dir = archive_root / "episodes"
    episodes_dir.mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match="No transcript.md files found"):
        build_manifest(archive_root, episodes_dir)


def test_manifest_contains_no_absolute_paths_or_bodies(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "archive"
    episodes_dir = archive_root / "episodes"
    (episodes_dir / "ep1").mkdir(parents=True)
    secret_text = "SECRET_VERY_UNIQUE_BODY_CONTENT_12345"
    content = f"""---
guest: Guest
title: Title
youtube_url: https://yt
video_id: 1
publish_date: 2025-01-01
---
{secret_text}
"""
    (episodes_dir / "ep1" / "transcript.md").write_text(content, encoding="utf-8")

    manifest = build_manifest(archive_root, episodes_dir)
    manifest_json_str = json.dumps(manifest)

    # Validate JSON serializability
    loaded = json.loads(manifest_json_str)
    assert loaded["summary"]["episode_files"] == 1

    # Ensure transcript body is NOT in manifest
    assert secret_text not in manifest_json_str

    # Ensure no absolute local machine paths leak into episode records
    archive_str = str(archive_root)
    assert archive_str not in manifest_json_str
    for ep in manifest["episodes"]:
        assert not Path(ep["source_path"]).is_absolute()
        assert ":" not in ep["source_path"]


def test_main_cli_execution(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "archive"
    episodes_dir = archive_root / "episodes"
    manifest_path = tmp_path / "out" / "manifest.json"

    content = """---
guest: CLI Guest
title: CLI Episode
youtube_url: https://yt
video_id: cli1
publish_date: 2025-01-01
---
CLI dialogue (00:00:10).
"""
    (episodes_dir / "cli_ep").mkdir(parents=True)
    (episodes_dir / "cli_ep" / "transcript.md").write_text(content, encoding="utf-8")

    main([
        "--archive-root", str(archive_root),
        "--episodes-dir", str(episodes_dir),
        "--manifest-path", str(manifest_path),
    ])

    assert manifest_path.is_file()
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_data["summary"]["episode_files"] == 1
    assert manifest_data["episodes"][0]["guest"] == "CLI Guest"