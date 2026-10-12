from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

# Required metadata fields in transcript frontmatter
REQUIRED_METADATA_FIELDS = (
    "guest",
    "title",
    "youtube_url",
    "video_id",
    "publish_date",
)

# Matches YAML frontmatter with delimiters
FRONTMATTER_PATTERN = re.compile(
    r"\A---[ \t]*\r?\n"
    r"(?:(.*?)\r?\n)?"
    r"---[ \t]*(?:\r?\n|\Z)",
    flags=re.DOTALL,
)

# Matches speaker turn header with timestamp: "Speaker Name (00:00:00):" or "(00:01:21):"
SPEAKER_TIMESTAMP_PATTERN = re.compile(
    r"^([^()\n\r:]+?)?\s*\(((?:\d{1,2}:)?\d{1,2}:\d{2})\)\s*:\s*(.*)$"
)

# Matches speaker turn header without timestamp: "Speaker Name:"
SPEAKER_ONLY_PATTERN = re.compile(
    r"^([^\W\d_][^\n\r:]{1,40})\s*:\s*(.*)$"
)

# Potential timestamp pattern anywhere in text
TIMESTAMP_PATTERN = re.compile(
    r"(?<!\d)(?:\d{1,2}:)?\d{1,2}:\d{2}(?!\d)"
)


def json_safe(value: Any) -> Any:
    """Convert YAML values to JSON-compatible values (isoformat dates, strings, etc.)."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return str(value)


def parse_timestamp_to_seconds(ts_str: str | None) -> float | None:
    """Convert HH:MM:SS or MM:SS timestamp string to total float seconds."""
    if not ts_str:
        return None

    cleaned = ts_str.strip()
    parts = cleaned.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600.0 + int(minutes) * 60.0 + float(seconds)
        elif len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60.0 + float(seconds)
    except (ValueError, TypeError):
        return None

    return None


@dataclass
class DialogueTurn:
    """A semantic dialogue turn, heading, or paragraph in the transcript."""

    speaker: str | None
    start_time_seconds: float | None
    timestamp_str: str | None
    text: str
    is_heading: bool = False


@dataclass
class ParsedTranscript:
    """Complete parsed transcript record including frontmatter, hashes, and dialogue turns."""

    source_path: str
    guest: str
    title: str
    source_platform: str
    source_url: str | None
    youtube_video_id: str | None
    spotify_url: str | None
    spotify_id: str | None
    publish_date: date | None
    duration_seconds: float | None
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    source_sha256: str = ""
    body_sha256: str = ""
    dialogue_body: str = ""
    turns: list[DialogueTurn] = field(default_factory=list)
    frontmatter_found: bool = False
    missing_required_metadata: list[str] = field(default_factory=list)
    parse_error: str | None = None
    word_count: int = 0
    character_count: int = 0
    potential_timestamp_matches: int = 0


def _parse_publish_date(value: Any) -> date | None:
    """Safely convert frontmatter date value to python datetime.date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _parse_duration_seconds(value: Any, duration_str: Any = None) -> float | None:
    """Extract duration in seconds from numeric seconds or HH:MM:SS string."""
    if value is not None:
        try:
            sec = float(value)
            if sec > 0:
                return sec
        except (ValueError, TypeError):
            pass

    if duration_str and isinstance(duration_str, str):
        sec = parse_timestamp_to_seconds(duration_str)
        if sec is not None and sec > 0:
            return sec

    return None


def extract_dialogue_turns(body_text: str) -> list[DialogueTurn]:
    """Parse dialogue text into ordered semantic units (headings, speaker turns, paragraphs)."""
    lines = body_text.splitlines()
    turns: list[DialogueTurn] = []

    current_speaker: str | None = None
    current_ts_str: str | None = None
    current_ts_sec: float | None = None
    current_text_lines: list[str] = []
    is_heading_block = False

    def flush_block() -> None:
        nonlocal current_text_lines, is_heading_block
        if current_text_lines:
            content = "\n".join(current_text_lines).strip()
            if content:
                turns.append(
                    DialogueTurn(
                        speaker=None if is_heading_block else current_speaker,
                        start_time_seconds=None if is_heading_block else current_ts_sec,
                        timestamp_str=None if is_heading_block else current_ts_str,
                        text=content,
                        is_heading=is_heading_block,
                    )
                )
            current_text_lines = []
            is_heading_block = False

    for line in lines:
        stripped = line.strip()

        # Handle Markdown headings
        if stripped.startswith("#"):
            flush_block()
            is_heading_block = True
            current_text_lines.append(stripped)
            flush_block()
            continue

        # Check for timestamped speaker turn: "Speaker (00:00:00):" or "(00:01:21):"
        ts_match = SPEAKER_TIMESTAMP_PATTERN.match(stripped)
        if ts_match:
            flush_block()
            speaker_match = ts_match.group(1)
            if speaker_match and speaker_match.strip():
                current_speaker = speaker_match.strip()

            current_ts_str = ts_match.group(2)
            current_ts_sec = parse_timestamp_to_seconds(current_ts_str)

            current_text_lines.append(stripped)
            continue

        # Check for non-timestamped speaker turn: "Speaker Name:"
        spk_match = SPEAKER_ONLY_PATTERN.match(stripped)
        if spk_match and not stripped.startswith("http"):
            cand_speaker = spk_match.group(1).strip()
            # Avoid matching random punctuation or markdown list keys
            if len(cand_speaker.split()) <= 4 and not cand_speaker.endswith("."):
                flush_block()
                current_speaker = cand_speaker
                current_ts_str = None
                current_ts_sec = None
                current_text_lines.append(stripped)
                continue

        # Dialogue continuation line
        current_text_lines.append(line)

    flush_block()
    return turns


def parse_transcript_source(
    path: Path | str,
    archive_root: Path | str,
) -> ParsedTranscript:
    """
    Parse a single transcript file into a normalized ParsedTranscript record.

    Validates path boundaries, extracts YAML frontmatter safely, calculates
    raw source and normalized dialogue SHA-256 hashes, and extracts dialogue turns.
    """
    path_obj = Path(path).resolve()
    archive_root_obj = Path(archive_root).resolve()

    try:
        source_path = path_obj.relative_to(archive_root_obj).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"Transcript path '{path_obj}' is outside archive root '{archive_root_obj}'"
        ) from exc

    try:
        raw_bytes = path_obj.read_bytes()
    except OSError as exc:
        return ParsedTranscript(
            source_path=source_path,
            guest="",
            title="",
            source_platform="youtube",
            source_url=None,
            youtube_video_id=None,
            spotify_url=None,
            spotify_id=None,
            publish_date=None,
            duration_seconds=None,
            raw_metadata={},
            source_sha256="",
            body_sha256="",
            dialogue_body="",
            turns=[],
            frontmatter_found=False,
            missing_required_metadata=list(REQUIRED_METADATA_FIELDS),
            parse_error=f"File read error: {exc}",
        )

    source_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    raw_text = raw_bytes.decode("utf-8-sig", errors="replace")

    metadata: dict[str, Any] = {}
    dialogue_body = raw_text
    parse_error: str | None = None
    frontmatter_found = False

    match = FRONTMATTER_PATTERN.search(raw_text)
    if match:
        frontmatter_found = True
        dialogue_body = raw_text[match.end():]

        try:
            loaded = yaml.safe_load(match.group(1) or "")
            if loaded is None:
                metadata = {}
            elif isinstance(loaded, dict):
                metadata = loaded
            else:
                raise ValueError("YAML frontmatter must be a mapping")
        except yaml.YAMLError as exc:
            parse_error = f"YAML parse error: {exc}"
        except ValueError as exc:
            parse_error = str(exc)
        except Exception as exc:
            parse_error = f"Unexpected frontmatter error: {exc}"
    else:
        parse_error = "Missing YAML frontmatter delimiters"

    # Normalized dialogue body and hash matching audit_corpus.py
    normalized_body = "\n".join(
        line.rstrip() for line in dialogue_body.splitlines()
    ).strip()
    body_sha256 = hashlib.sha256(normalized_body.encode("utf-8")).hexdigest()

    # Determine missing metadata
    def is_missing_val(val: Any) -> bool:
        if val is None:
            return True
        if isinstance(val, str):
            return not val.strip()
        if isinstance(val, (dict, list, tuple, set)):
            return len(val) == 0
        return False

    missing_fields = [
        field for field in REQUIRED_METADATA_FIELDS if is_missing_val(metadata.get(field))
    ]

    # Platform detection
    youtube_url = str(metadata.get("youtube_url") or "").strip() or None
    video_id = str(metadata.get("video_id") or "").strip() or None
    if not video_id and youtube_url:
        yt_match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", youtube_url)
        if yt_match:
            video_id = yt_match.group(1)

    spotify_url = str(metadata.get("spotify_url") or "").strip() or None
    spotify_id = str(metadata.get("spotify_id") or "").strip() or None
    if not spotify_id and spotify_url:
        sp_match = re.search(r"episode/([A-Za-z0-9]+)", spotify_url)
        if sp_match:
            spotify_id = sp_match.group(1)

    if spotify_url or spotify_id:
        if not youtube_url and not video_id:
            source_platform = "spotify"
            source_url = spotify_url
        else:
            source_platform = "youtube"
            source_url = youtube_url or spotify_url
    else:
        source_platform = "youtube"
        source_url = youtube_url

    guest = str(metadata.get("guest") or "").strip()
    title = str(metadata.get("title") or "").strip()
    publish_date = _parse_publish_date(metadata.get("publish_date"))
    duration_sec = _parse_duration_seconds(
        metadata.get("duration_seconds"), metadata.get("duration")
    )

    turns = extract_dialogue_turns(dialogue_body)
    word_count = len(dialogue_body.split())
    character_count = len(dialogue_body)
    ts_matches = len(TIMESTAMP_PATTERN.findall(dialogue_body))

    return ParsedTranscript(
        source_path=source_path,
        guest=guest,
        title=title,
        source_platform=source_platform,
        source_url=source_url,
        youtube_video_id=video_id,
        spotify_url=spotify_url,
        spotify_id=spotify_id,
        publish_date=publish_date,
        duration_seconds=duration_sec,
        raw_metadata=json_safe(metadata),
        source_sha256=source_sha256,
        body_sha256=body_sha256,
        dialogue_body=dialogue_body,
        turns=turns,
        frontmatter_found=frontmatter_found,
        missing_required_metadata=missing_fields,
        parse_error=parse_error,
        word_count=word_count,
        character_count=character_count,
        potential_timestamp_matches=ts_matches,
    )
