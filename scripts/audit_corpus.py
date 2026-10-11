from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]

ARCHIVE_ROOT = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "lennys-podcast-transcripts"
)

EPISODES_DIR = ARCHIVE_ROOT / "episodes"
MANIFEST_PATH = PROJECT_ROOT / "data" / "manifest.json"

SOURCE_REPOSITORY = (
    "https://github.com/ChatPRD/"
    "lennys-podcast-transcripts"
)

REQUIRED_METADATA_FIELDS = (
    "guest",
    "title",
    "youtube_url",
    "video_id",
    "publish_date",
)

# Identifies likely MM:SS or HH:MM:SS patterns.
# A match does not establish that the value is a valid video offset.
TIMESTAMP_PATTERN = re.compile(
    r"(?<!\d)(?:\d{1,2}:)?\d{1,2}:\d{2}(?!\d)"
)

FRONTMATTER_PATTERN = re.compile(
    r"\A---[ \t]*\r?\n"
    r"(?:(.*?)\r?\n)?"
    r"---[ \t]*(?:\r?\n|\Z)",
    flags=re.DOTALL,
)


def json_safe(value: Any) -> Any:
    """Convert YAML values to JSON-compatible values."""

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if value is None or isinstance(
        value, (str, int, float, bool)
    ):
        return value

    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]

    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    return str(value)


def display_value(value: Any) -> str:
    """Convert a metadata value to a readable string."""

    if value is None:
        return ""

    if isinstance(value, (date, datetime)):
        return value.isoformat()

    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(
            json_safe(value),
            ensure_ascii=False,
        )

    return str(value).strip()


def is_missing(value: Any) -> bool:
    """Return True when required metadata is absent."""

    if value is None:
        return True

    if isinstance(value, str):
        return not value.strip()

    if isinstance(value, (dict, list, tuple, set)):
        return len(value) == 0

    return False


def parse_transcript(
    path: Path,
    archive_root: Path,
) -> dict[str, Any]:
    """
    Parse one transcript into an audit record.

    The original bytes are used for the SHA-256 hash.
    Transcript content is not copied into the manifest.
    """

    path = Path(path).resolve()
    archive_root = Path(archive_root).resolve()

    try:
        source_path = path.relative_to(archive_root).as_posix()
    except ValueError:
        source_path = path.as_posix()

    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        return {
            "source_path": source_path,
            "guest": "",
            "title": "",
            "youtube_url": "",
            "video_id": "",
            "publish_date": "",
            "metadata": {},
            "frontmatter_found": False,
            "missing_required_metadata": list(REQUIRED_METADATA_FIELDS),
            "parse_error": f"File read error: {exc}",
            "word_count": 0,
            "character_count": 0,
            "empty_body": True,
            "potential_timestamp_matches": 0,
            "source_sha256": "",
        }

    raw_text = raw_bytes.decode(
        "utf-8-sig",
        errors="replace",
    )

    metadata: dict[str, Any] = {}
    body = raw_text
    parse_error: str | None = None
    frontmatter_found = False

    match = FRONTMATTER_PATTERN.search(raw_text)

    if match:
        frontmatter_found = True

        # Keep the dialogue available even if its metadata
        # cannot be parsed.
        body = raw_text[match.end():]

        try:
            loaded = yaml.safe_load(match.group(1) or "")

            if loaded is None:
                metadata = {}
            elif isinstance(loaded, dict):
                metadata = loaded
            else:
                raise ValueError(
                    "YAML frontmatter must be a mapping"
                )

        except yaml.YAMLError as exc:
            parse_error = f"YAML parse error: {exc}"

        except ValueError as exc:
            parse_error = str(exc)

        except Exception as exc:
            parse_error = f"Unexpected frontmatter error: {exc}"

    else:
        parse_error = "Missing YAML frontmatter delimiters"

    missing_metadata = [
        field
        for field in REQUIRED_METADATA_FIELDS
        if is_missing(metadata.get(field))
    ]

    timestamp_count = len(
        TIMESTAMP_PATTERN.findall(body)
    )

    return {
        "source_path": source_path,
        "guest": display_value(metadata.get("guest")),
        "title": display_value(metadata.get("title")),
        "youtube_url": display_value(
            metadata.get("youtube_url")
        ),
        "video_id": display_value(
            metadata.get("video_id")
        ),
        "publish_date": display_value(
            metadata.get("publish_date")
        ),
        "metadata": json_safe(metadata),
        "frontmatter_found": frontmatter_found,
        "missing_required_metadata": missing_metadata,
        "parse_error": parse_error,
        "word_count": len(body.split()),
        "character_count": len(body),
        "empty_body": not bool(body.strip()),
        "potential_timestamp_matches": timestamp_count,
        "source_sha256": hashlib.sha256(
            raw_bytes
        ).hexdigest(),
    }


def build_manifest(
    archive_root: Path,
    episodes_dir: Path,
) -> dict[str, Any]:
    """Audit the transcript files and return a manifest."""

    archive_root = Path(archive_root).resolve()
    episodes_dir = Path(episodes_dir).resolve()

    if not archive_root.is_dir():
        raise FileNotFoundError(
            f"Transcript repository not found: {archive_root}"
        )

    if not episodes_dir.is_dir():
        raise FileNotFoundError(
            f"Episode directory not found: {episodes_dir}"
        )

    transcript_paths = sorted(
        episodes_dir.rglob("transcript.md")
    )

    if not transcript_paths:
        raise FileNotFoundError(
            "No transcript.md files found under "
            f"{episodes_dir}. Check the repository structure."
        )

    records = [
        parse_transcript(path, archive_root)
        for path in transcript_paths
    ]

    paths_by_hash: dict[str, list[str]] = defaultdict(list)

    for record in records:
        paths_by_hash[
            record["source_sha256"]
        ].append(record["source_path"])

    duplicate_groups = [
        {
            "source_sha256": digest,
            "source_paths": sorted(paths),
        }
        for digest, paths in sorted(paths_by_hash.items())
        if len(paths) > 1
    ]

    summary = {
        "episode_files": len(records),
        "total_words": sum(
            record["word_count"]
            for record in records
        ),
        "files_with_frontmatter": sum(
            record["frontmatter_found"]
            for record in records
        ),
        "files_with_parse_errors": sum(
            record["parse_error"] is not None
            for record in records
        ),
        "files_with_missing_required_metadata": sum(
            bool(record["missing_required_metadata"])
            for record in records
        ),
        "empty_transcripts": sum(
            record["empty_body"]
            for record in records
        ),
        "files_with_potential_timestamps": sum(
            record["potential_timestamp_matches"] > 0
            for record in records
        ),
        "unique_source_hashes": len(paths_by_hash),
        "duplicate_content_groups": len(duplicate_groups),
    }

    return {
        "schema_version": 1,
        "source_repository": SOURCE_REPOSITORY,
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "summary": summary,
        "duplicate_groups": duplicate_groups,
        "episodes": records,
    }


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Audit the transcript corpus and generate manifest.json"
    )
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=ARCHIVE_ROOT,
        help="Path to the archive repository root",
    )
    parser.add_argument(
        "--episodes-dir",
        type=Path,
        default=None,
        help="Path to the episodes directory (defaults to <archive-root>/episodes)",
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=MANIFEST_PATH,
        help="Path to the output manifest.json",
    )

    args = parser.parse_args(argv)

    archive_root = Path(args.archive_root).resolve()
    episodes_dir = (
        Path(args.episodes_dir).resolve()
        if args.episodes_dir
        else (archive_root / "episodes").resolve()
    )
    manifest_path = Path(args.manifest_path).resolve()

    try:
        manifest = build_manifest(
            archive_root,
            episodes_dir,
        )

    except (OSError, ValueError) as exc:
        raise SystemExit(
            f"Corpus audit failed: {exc}"
        ) from exc

    manifest_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("Corpus audit completed.")
    print(
        json.dumps(
            manifest["summary"],
            indent=2,
            ensure_ascii=False,
        )
    )
    print(f"\nManifest: {manifest_path}")


if __name__ == "__main__":
    main()