from __future__ import annotations

from datetime import date
from pathlib import Path
import re

import pytest

from backend.app.config import get_settings
from backend.app.ingestion.chunker import (
    ChunkData,
    TokenCounter,
    chunk_transcript,
)
from backend.app.ingestion.parser import (
    DialogueTurn,
    ParsedTranscript,
    parse_transcript_source,
)


@pytest.fixture(scope="session")
def tokenizer() -> TokenCounter:
    return TokenCounter()


def make_dummy_transcript(
    turns: list[DialogueTurn],
    guest: str = "Test Guest",
    title: str = "Test Episode",
    source_path: str = "episodes/test-guest/transcript.md",
) -> ParsedTranscript:
    full_body = "\n\n".join(t.text for t in turns)
    return ParsedTranscript(
        source_path=source_path,
        guest=guest,
        title=title,
        source_platform="youtube",
        source_url="https://youtube.com/watch?v=dummy",
        youtube_video_id="dummy",
        spotify_url=None,
        spotify_id=None,
        publish_date=date(2024, 1, 1),
        duration_seconds=1200.0,
        raw_metadata={"guest": guest, "title": title},
        source_sha256="dummy_source_hash",
        body_sha256="dummy_body_hash",
        dialogue_body=full_body,
        turns=turns,
    )


def test_chunk_token_limits(tokenizer: TokenCounter) -> None:
    # Create turns that sum to well over target tokens
    turns = [
        DialogueTurn(
            speaker="Lenny",
            start_time_seconds=float(i * 30),
            timestamp_str=f"00:{i:02d}:00",
            text=(
                f"Lenny (00:{i:02d}:00):\n"
                "In this section of the podcast we are discussing long-term retention strategies, "
                "onboarding optimization, customer development interviews, and how product teams "
                "prioritize competing engineering roadmaps under intense market pressure."
            ),
        )
        for i in range(25)
    ]
    parsed = make_dummy_transcript(turns)
    target = 450
    chunks = chunk_transcript(parsed, target_tokens=target, overlap_tokens=60, tokenizer=tokenizer)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.token_count <= target
        assert chunk.token_count == tokenizer.count_tokens(chunk.chunk_text)
        assert len(chunk.chunk_sha256) == 64


def test_no_embedding_prefixes_in_stored_chunks(tokenizer: TokenCounter) -> None:
    turns = [
        DialogueTurn(
            speaker="Guest",
            start_time_seconds=0.0,
            timestamp_str="00:00:00",
            text="Guest (00:00:00):\nHere is the discussion about growth loops.",
        )
    ]
    parsed = make_dummy_transcript(turns)
    chunks = chunk_transcript(parsed, tokenizer=tokenizer)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert not chunk.chunk_text.startswith("search_document:")
    assert not chunk.chunk_text.startswith("search_query:")
    assert "search_document:" not in chunk.chunk_text


def test_oversized_turn_splitting_at_sentence_boundaries(tokenizer: TokenCounter) -> None:
    # Construct an oversized turn with 10 sentences that exceed 450 tokens
    sentences = [
        f"Sentence number {i} provides essential context regarding modern product management, "
        f"user cohort analysis, unit economics, lifetime value metrics, and organic distribution loops."
        for i in range(30)
    ]
    long_turn_text = "Lenny (00:05:00):\n" + " ".join(sentences)
    turn_tokens = tokenizer.count_tokens(long_turn_text)
    assert turn_tokens > 500  # Verify it is oversized

    turns = [
        DialogueTurn(
            speaker="Lenny",
            start_time_seconds=300.0,
            timestamp_str="00:05:00",
            text=long_turn_text,
        )
    ]
    parsed = make_dummy_transcript(turns)
    target = 300
    chunks = chunk_transcript(parsed, target_tokens=target, overlap_tokens=40, tokenizer=tokenizer)

    assert len(chunks) > 1
    for c in chunks:
        assert c.token_count <= target
        assert c.speaker == "Lenny"

    # Verify all sentence numbers are represented across chunks (no silent drop)
    all_chunks_text = " ".join(c.chunk_text for c in chunks)
    for i in range(30):
        assert f"Sentence number {i}" in all_chunks_text


def test_dialogue_coverage_no_dialogue_loss(tokenizer: TokenCounter) -> None:
    phrases = [
        "First turn opening remarks on PLG.",
        "Second turn exploring viral loops.",
        "Third turn detailing pricing experimentation.",
        "Fourth turn discussing churn reduction.",
        "Fifth turn concluding the interview.",
    ]
    turns = [
        DialogueTurn(
            speaker=f"Speaker {i}",
            start_time_seconds=float(i * 60),
            timestamp_str=f"00:0{i}:00",
            text=f"Speaker {i} (00:0{i}:00):\n{phrases[i]}",
        )
        for i in range(len(phrases))
    ]
    parsed = make_dummy_transcript(turns)
    chunks = chunk_transcript(parsed, target_tokens=200, overlap_tokens=30, tokenizer=tokenizer)

    combined_text = "\n".join(c.chunk_text for c in chunks)
    for phrase in phrases:
        assert phrase in combined_text


def test_chunk_overlap_behavior(tokenizer: TokenCounter) -> None:
    turns = [
        DialogueTurn(
            speaker=f"Speaker {i}",
            start_time_seconds=float(i * 10),
            timestamp_str=f"00:00:{i*10:02d}",
            text=f"Turn {i}: Detailed commentary number {i} discussing software growth mechanisms.",
        )
        for i in range(20)
    ]
    parsed = make_dummy_transcript(turns)
    target = 100
    overlap = 30
    chunks = chunk_transcript(parsed, target_tokens=target, overlap_tokens=overlap, tokenizer=tokenizer)

    assert len(chunks) >= 3
    # Check that adjacent chunks share text when overlap > 0
    overlap_found = False
    for idx in range(len(chunks) - 1):
        c1_words = set(chunks[idx].chunk_text.split())
        c2_words = set(chunks[idx + 1].chunk_text.split())
        shared = c1_words.intersection(c2_words)
        if len(shared) > 5:
            overlap_found = True
            break
    assert overlap_found is True


def test_timestamp_and_speaker_preservation(tokenizer: TokenCounter) -> None:
    turns = [
        DialogueTurn(
            speaker=None,
            start_time_seconds=None,
            timestamp_str=None,
            text="# Episode Heading",
            is_heading=True,
        ),
        DialogueTurn(
            speaker="Ada Chen Rekhi",
            start_time_seconds=120.0,
            timestamp_str="00:02:00",
            text="Ada Chen Rekhi (00:02:00):\nFinding career alignment is crucial.",
        ),
        DialogueTurn(
            speaker="Lenny",
            start_time_seconds=180.0,
            timestamp_str="00:03:00",
            text="Lenny (00:03:00):\nHow did you discover Notejoy?",
        ),
    ]
    parsed = make_dummy_transcript(turns)
    chunks = chunk_transcript(parsed, target_tokens=450, overlap_tokens=60, tokenizer=tokenizer)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.speaker == "Ada Chen Rekhi"
    assert chunk.start_time_seconds == 120.0
    assert "# Episode Heading" in chunk.chunk_text
    assert "Finding career alignment" in chunk.chunk_text


def test_chunk_metadata_fields(tokenizer: TokenCounter) -> None:
    turns = [
        DialogueTurn(
            speaker="Guest",
            start_time_seconds=0.0,
            timestamp_str="00:00:00",
            text="Guest (00:00:00):\nHello world.",
        )
    ]
    parsed = make_dummy_transcript(turns)
    chunks = chunk_transcript(parsed, tokenizer=tokenizer)

    assert len(chunks) == 1
    c = chunks[0]
    assert c.source_path == "episodes/test-guest/transcript.md"
    assert c.guest == "Test Guest"
    assert c.title == "Test Episode"
    assert c.chunk_index == 0
    assert isinstance(c.chunk_text, str)
    assert isinstance(c.chunk_sha256, str)
    assert c.token_count > 0
    assert c.character_count == len(c.chunk_text)
    assert c.speaker == "Guest"
    assert c.start_time_seconds == 0.0
    assert c.chunker_version == "v1"


def test_unicode_and_special_characters(tokenizer: TokenCounter) -> None:
    turns = [
        DialogueTurn(
            speaker="Gustav Söderström",
            start_time_seconds=0.0,
            timestamp_str="00:00:00",
            text="Gustav Söderström (00:00:00):\nDiscussing “large language models” — it’s fantastic! ✨",
        )
    ]
    parsed = make_dummy_transcript(turns)
    chunks = chunk_transcript(parsed, tokenizer=tokenizer)

    assert len(chunks) == 1
    c = chunks[0]
    assert "Söderström" in c.chunk_text
    assert "“" in c.chunk_text
    assert "✨" in c.chunk_text
    assert c.token_count == tokenizer.count_tokens(c.chunk_text)


def test_duplicate_source_preservation(tokenizer: TokenCounter) -> None:
    # Ensure two transcripts with identical dialogue but different source paths produce independent chunks
    turns_a = [
        DialogueTurn(
            speaker="Andy Raskin",
            start_time_seconds=0.0,
            timestamp_str="00:00:00",
            text="Andy Raskin (00:00:00):\nThe greatest sales deck ever.",
        )
    ]
    parsed_a = make_dummy_transcript(
        turns_a,
        guest="Andy Raskin",
        title="Episode 1",
        source_path="episodes/andy-raskin/transcript.md",
    )
    parsed_b = make_dummy_transcript(
        turns_a,
        guest="Andy Raskin",
        title="Episode 1 (Duplicate)",
        source_path="episodes/andy-raskin_/transcript.md",
    )

    chunks_a = chunk_transcript(parsed_a, tokenizer=tokenizer)
    chunks_b = chunk_transcript(parsed_b, tokenizer=tokenizer)

    assert len(chunks_a) == 1
    assert len(chunks_b) == 1
    assert chunks_a[0].source_path == "episodes/andy-raskin/transcript.md"
    assert chunks_b[0].source_path == "episodes/andy-raskin_/transcript.md"
    assert chunks_a[0].chunk_sha256 == chunks_b[0].chunk_sha256
    # Both are preserved without dropping
