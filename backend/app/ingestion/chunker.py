from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Sequence

from tokenizers import Tokenizer

from backend.app.config import get_settings
from backend.app.ingestion.parser import (
    DialogueTurn,
    ParsedTranscript,
    parse_timestamp_to_seconds,
)

# Sentence boundary pattern
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")


class TokenCounter:
    """Tokenizer service wrapping HuggingFace Tokenizer for nomic-embed-text:v1.5."""

    _instance: TokenCounter | None = None
    _cached_tokenizer: Tokenizer | None = None

    def __init__(self, model_name: str = "nomic-ai/nomic-embed-text-v1.5") -> None:
        if TokenCounter._cached_tokenizer is None:
            TokenCounter._cached_tokenizer = Tokenizer.from_pretrained(model_name)
        self.tokenizer = TokenCounter._cached_tokenizer

    def count_tokens(self, text: str) -> int:
        """Count actual tokens in text using nomic tokenizer."""
        if not text or not text.strip():
            return 0
        return len(self.tokenizer.encode(text).ids)

    def encode(self, text: str) -> list[int]:
        """Encode text to token ids."""
        if not text:
            return []
        return self.tokenizer.encode(text).ids


@dataclass
class ChunkData:
    """Structure-aware transcript chunk representation."""

    source_path: str
    guest: str
    title: str
    chunk_index: int
    chunk_text: str
    chunk_sha256: str
    token_count: int
    character_count: int
    speaker: str | None
    start_time_seconds: float | None
    chunker_version: str = "v1"


@dataclass
class _AtomicUnit:
    """Atomic text block (turn, paragraph, or sentence) with metadata and token count."""

    text: str
    tokens: int
    speaker: str | None
    start_time_seconds: float | None
    timestamp_str: str | None
    is_heading: bool = False


def _split_oversized_turn(
    turn: DialogueTurn,
    target_tokens: int,
    tokenizer: TokenCounter,
) -> list[_AtomicUnit]:
    """Decompose an oversized dialogue turn into paragraph/sentence units under target_tokens."""
    sub_units: list[_AtomicUnit] = []
    paragraphs = [p.strip() for p in turn.text.split("\n\n") if p.strip()]

    for para_idx, paragraph in enumerate(paragraphs):
        para_tokens = tokenizer.count_tokens(paragraph)
        if para_tokens <= target_tokens:
            sub_units.append(
                _AtomicUnit(
                    text=paragraph,
                    tokens=para_tokens,
                    speaker=turn.speaker,
                    start_time_seconds=turn.start_time_seconds if para_idx == 0 else None,
                    timestamp_str=turn.timestamp_str if para_idx == 0 else None,
                    is_heading=turn.is_heading,
                )
            )
            continue

        # Split paragraph into sentences
        sentences = [s.strip() for s in SENTENCE_SPLIT_PATTERN.split(paragraph) if s.strip()]
        cur_sent_group: list[str] = []
        cur_group_tokens = 0

        for sent in sentences:
            sent_tokens = tokenizer.count_tokens(sent)

            # If a single sentence exceeds target, split by word chunks
            if sent_tokens > target_tokens:
                if cur_sent_group:
                    grouped_text = " ".join(cur_sent_group)
                    sub_units.append(
                        _AtomicUnit(
                            text=grouped_text,
                            tokens=cur_group_tokens,
                            speaker=turn.speaker,
                            start_time_seconds=turn.start_time_seconds if not sub_units else None,
                            timestamp_str=turn.timestamp_str if not sub_units else None,
                        )
                    )
                    cur_sent_group = []
                    cur_group_tokens = 0

                # Split words of giant sentence
                words = sent.split()
                w_group: list[str] = []
                w_tokens = 0
                for w in words:
                    w_t = tokenizer.count_tokens(w + " ")
                    if w_tokens + w_t > target_tokens and w_group:
                        w_text = " ".join(w_group)
                        sub_units.append(
                            _AtomicUnit(
                                text=w_text,
                                tokens=w_tokens,
                                speaker=turn.speaker,
                                start_time_seconds=turn.start_time_seconds if not sub_units else None,
                                timestamp_str=turn.timestamp_str if not sub_units else None,
                            )
                        )
                        w_group = [w]
                        w_tokens = w_t
                    else:
                        w_group.append(w)
                        w_tokens += w_t

                if w_group:
                    w_text = " ".join(w_group)
                    sub_units.append(
                        _AtomicUnit(
                            text=w_text,
                            tokens=w_tokens,
                            speaker=turn.speaker,
                            start_time_seconds=turn.start_time_seconds if not sub_units else None,
                            timestamp_str=turn.timestamp_str if not sub_units else None,
                        )
                    )
                continue

            if cur_group_tokens + sent_tokens > target_tokens and cur_sent_group:
                grouped_text = " ".join(cur_sent_group)
                sub_units.append(
                    _AtomicUnit(
                        text=grouped_text,
                        tokens=cur_group_tokens,
                        speaker=turn.speaker,
                        start_time_seconds=turn.start_time_seconds if not sub_units else None,
                        timestamp_str=turn.timestamp_str if not sub_units else None,
                    )
                )
                cur_sent_group = [sent]
                cur_group_tokens = sent_tokens
            else:
                cur_sent_group.append(sent)
                cur_group_tokens += sent_tokens

        if cur_sent_group:
            grouped_text = " ".join(cur_sent_group)
            sub_units.append(
                _AtomicUnit(
                    text=grouped_text,
                    tokens=cur_group_tokens,
                    speaker=turn.speaker,
                    start_time_seconds=turn.start_time_seconds if not sub_units else None,
                    timestamp_str=turn.timestamp_str if not sub_units else None,
                )
            )

    return sub_units


def _prepare_atomic_units(
    turns: Sequence[DialogueTurn],
    target_tokens: int,
    tokenizer: TokenCounter,
) -> list[_AtomicUnit]:
    """Convert parsed dialogue turns into atomic units guaranteed to fit within target_tokens."""
    units: list[_AtomicUnit] = []
    for turn in turns:
        t_tokens = tokenizer.count_tokens(turn.text)
        if t_tokens <= target_tokens:
            units.append(
                _AtomicUnit(
                    text=turn.text,
                    tokens=t_tokens,
                    speaker=turn.speaker,
                    start_time_seconds=turn.start_time_seconds,
                    timestamp_str=turn.timestamp_str,
                    is_heading=turn.is_heading,
                )
            )
        else:
            # Turn exceeds target; split at paragraph and sentence boundaries
            sub_units = _split_oversized_turn(turn, target_tokens, tokenizer)
            units.extend(sub_units)
    return units


def chunk_transcript(
    parsed: ParsedTranscript,
    target_tokens: int | None = None,
    overlap_tokens: int | None = None,
    tokenizer: TokenCounter | None = None,
    chunker_version: str = "v1",
) -> list[ChunkData]:
    """
    Split a parsed transcript into structure-aware, overlapping chunks.

    Preserves headings, speaker labels, and timestamps. Prefers whole speaker
    turns or paragraphs, splitting oversized turns at sentence boundaries.
    Ensures zero dialogue is silently dropped.
    """
    settings = get_settings()
    tgt = target_tokens if target_tokens is not None else settings.chunk_target_tokens
    ovr = overlap_tokens if overlap_tokens is not None else settings.chunk_overlap_tokens
    tok = tokenizer or TokenCounter()

    if not parsed.turns:
        # Check if raw dialogue body has text despite no speaker matches
        raw_body = parsed.dialogue_body.strip()
        if not raw_body:
            return []
        # Create a single turn from raw body
        parsed.turns = [
            DialogueTurn(
                speaker=None,
                start_time_seconds=None,
                timestamp_str=None,
                text=raw_body,
            )
        ]

    atomic_units = _prepare_atomic_units(parsed.turns, tgt, tok)
    if not atomic_units:
        return []

    chunks: list[ChunkData] = []
    num_units = len(atomic_units)
    i = 0

    while i < num_units:
        current_cluster: list[_AtomicUnit] = [atomic_units[i]]
        j = i + 1

        while j < num_units:
            candidate = atomic_units[j]
            # Test joining current cluster with candidate unit
            joined_candidate = "\n\n".join(u.text for u in current_cluster + [candidate])
            candidate_tokens = tok.count_tokens(joined_candidate)

            if candidate_tokens <= tgt:
                current_cluster.append(candidate)
                j += 1
            else:
                break

        # Assemble chunk text
        chunk_text = "\n\n".join(u.text for u in current_cluster).strip()
        actual_tokens = tok.count_tokens(chunk_text)

        # Identify starting speaker and timestamp
        chunk_speaker: str | None = None
        chunk_start_time: float | None = None

        for u in current_cluster:
            if chunk_speaker is None and u.speaker:
                chunk_speaker = u.speaker
            if chunk_start_time is None and u.start_time_seconds is not None:
                chunk_start_time = u.start_time_seconds
            if chunk_speaker is not None and chunk_start_time is not None:
                break

        chunk_sha256 = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()

        chunks.append(
            ChunkData(
                source_path=parsed.source_path,
                guest=parsed.guest,
                title=parsed.title,
                chunk_index=len(chunks),
                chunk_text=chunk_text,
                chunk_sha256=chunk_sha256,
                token_count=actual_tokens,
                character_count=len(chunk_text),
                speaker=chunk_speaker,
                start_time_seconds=chunk_start_time,
                chunker_version=chunker_version,
            )
        )

        if j >= num_units:
            break

        # Compute next starting index with bounded overlap
        # Search backward from j - 1 for units fitting within overlap_tokens
        k = j - 1
        accumulated_overlap = 0
        overlap_start = j  # default no overlap

        while k > i:
            accumulated_overlap += atomic_units[k].tokens
            if accumulated_overlap <= ovr:
                overlap_start = k
                k -= 1
            else:
                break

        # Ensure forward progress: next index must be strictly greater than i
        i = overlap_start if overlap_start > i else i + 1

    return chunks
