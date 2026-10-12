"""
Unit tests for deterministic essay evaluation, word counting, and citation verification.
"""
from __future__ import annotations

import pytest

from backend.app.models import Episode, TranscriptChunk
from backend.app.writing.evaluator import (
    count_words,
    detect_thesis_statement,
    evaluate_essay,
    extract_citation_markers,
    get_acceptable_word_count_range,
    split_body_and_references,
)


def test_split_body_and_references():
    content = (
        "# The Future of Growth\n\n"
        "Here is the essay content about growth loops and retention.\n\n"
        "## References\n"
        "[Source 1] Brian Chesky - Leading Through Crisis\n"
        "[Source 2] Elena Verna - AI Growth Playbook\n"
    )
    body, refs = split_body_and_references(content)
    assert "Here is the essay content" in body
    assert "## References" in refs
    assert "Elena Verna" in refs
    assert "## References" not in body


def test_count_words_strips_markdown():
    text = (
        "# Heading\n\n"
        "This is **bold** and *italic* text with a [link](https://example.com) and `code`.\n\n"
        "```python\ndef foo(): pass\n```"
    )
    wc = count_words(text)
    # Heading (1) + This (1) + is (1) + bold (1) + and (1) + italic (1) + text (1) + with (1) + a (1) + link (1) + and (1) + code (1) = 12
    assert wc == 12


def test_extract_citation_markers():
    text = (
        "According to Elena Verna [Source 1], growth loops compound. "
        "Brian Chesky mentions this in [Chunk #42] and Todd Jackson reinforces it [Source 3]."
    )
    markers = extract_citation_markers(text)
    assert "[Source 1]" in markers
    assert "[Chunk #42]" in markers
    assert "[Source 3]" in markers
    assert len(markers) == 3


def test_detect_thesis_statement():
    text_with_thesis = (
        "# Product Strategy\n\n"
        "In this essay, we argue that sustainable growth is driven exclusively by retention loops.\n\n"
        "## The Framework\nContent here."
    )
    assert detect_thesis_statement(text_with_thesis) is True

    text_without_thesis = (
        "# Product Strategy\n\n"
        "Today we look at some stuff. Growth is fun. Things happen.\n\n"
        "## Details\nRandom text."
    )
    assert detect_thesis_statement(text_without_thesis) is False


def test_evaluate_essay_full_pass(db_session_factory):
    with db_session_factory() as session:
        ep = Episode(
            source_path="episodes/elena-verna/transcript.md",
            guest="Elena Verna",
            title="B2B Growth",
            source_sha256="hash111",
            body_sha256="hash222",
        )
        session.add(ep)
        session.commit()
        session.refresh(ep)

        chunk = TranscriptChunk(
            episode_id=ep.id,
            chunk_index=0,
            chunk_text="Product led growth requires viral loops.",
            chunk_sha256="chash111",
            token_count=10,
            character_count=40,
        )
        session.add(chunk)
        session.commit()
        session.refresh(chunk)
        chunk_id = chunk.id

        # Generate a body with ~100 words targeting 100 words
        paragraphs = [
            "# Unlocking Product-Led Growth",
            "At its core, the argument is that viral growth loops determine long-term enterprise value [Source 1].",
            "## 1. The Power of Retention Loops",
            "When products generate natural user-to-user invites, acquisition costs fall dramatically over time. " * 3,
            "## 2. Monetization Alignment",
            "Aligning pricing with actual usage value ensures customer expansion revenue without sales intervention. " * 3,
            "## Conclusion and Strategic Takeaways",
            "In summary, modern software companies must embed viral hooks into their primary user onboarding workflows.",
            "## References",
            f"[Source 1] Elena Verna - B2B Growth (Chunk #{chunk_id})",
        ]
        doc = "\n\n".join(paragraphs)

        collected = [{"chunk_id": chunk_id, "title": ep.title, "guest": ep.guest}]
        eval_result = evaluate_essay(
            markdown_text=doc,
            target_word_count=120,
            collected_chunks=collected,
            db=session,
        )

        assert eval_result.has_title is True
        assert eval_result.headings_count >= 2
        assert eval_result.thesis_detected is True
        assert eval_result.all_citations_verified is True
        assert chunk_id in eval_result.verified_chunk_ids
        assert eval_result.passed is True


def test_evaluate_essay_rejects_unverified_sources(db_session_factory):
    with db_session_factory() as session:
        doc = (
            "# False Claims\n\n"
            "At its core, this claim cites a fake source [Source 99].\n\n"
            "## Section 1\nDetails here.\n\n"
            "## Conclusion\nEnd."
        )
        collected = [{"chunk_id": 10, "title": "Real Episode", "guest": "Real Guest"}]
        eval_result = evaluate_essay(
            markdown_text=doc,
            target_word_count=50,
            collected_chunks=collected,
            db=session,
        )

        assert eval_result.all_citations_verified is False
        assert "[Source 99]" in eval_result.unverified_citations
        assert eval_result.passed is False


def test_acceptable_word_count_range_derivation():
    # Target 1,250 -> strictly 1,125 to 1,375 (+/- 10%)
    lower, upper = get_acceptable_word_count_range(1250)
    assert lower == 1125
    assert upper == 1375

    # Target 500 -> 450 to 550
    lower_500, upper_500 = get_acceptable_word_count_range(500)
    assert lower_500 == 450
    assert upper_500 == 550

    # Target 2,000 -> 1,800 to 2,200
    lower_2k, upper_2k = get_acceptable_word_count_range(2000)
    assert lower_2k == 1800
    assert upper_2k == 2200


def _build_essay(body_words: int, chunk_id: int, include_thesis: bool = True, ref_words: int = 50) -> str:
    """Build deterministic essay with exact body word count and separate references."""
    header = "# The Growth Engine\n\n"
    thesis = "At its core, the argument is that viral loops drive sustainable retention [Source 1].\n\n" if include_thesis else "Here are random notes.\n\n"
    s1 = "## 1. Deep Onboarding\n\n"
    s2 = "## 2. Retention Metrics\n\n"
    scaffold = header + thesis + s1 + s2
    scaffold_wc = count_words(scaffold)
    remaining = max(0, body_words - scaffold_wc)
    filler = " ".join(["compound"] * remaining)
    body = scaffold + filler
    # Adjust to exact body words
    while count_words(body) < body_words:
        body += " compound"
    while count_words(body) > body_words:
        body = body.rsplit(" ", 1)[0]

    # Separate references
    ref_filler = " ".join(["citation"] * max(0, ref_words - 10))
    references = f"\n\n## References\n[Source 1] Real Guest - Real Episode (Chunk #{chunk_id}) {ref_filler}"
    return body + references


def test_evaluate_essay_below_word_count_range_fails():
    # Target 1,250: 900 words is well below 1,125
    doc = _build_essay(body_words=900, chunk_id=1)
    collected = [{"chunk_id": 1, "title": "Ep", "guest": "Guest"}]
    res = evaluate_essay(doc, target_word_count=1250, collected_chunks=collected, db=None)
    assert res.body_word_count == 900
    assert res.word_count_in_range is False
    assert res.passed is False
    assert any("outside acceptable target range" in fb for fb in res.feedback)


def test_evaluate_essay_above_word_count_range_fails():
    # Target 1,250: 1,722 words is well above 1,375
    doc = _build_essay(body_words=1722, chunk_id=1)
    collected = [{"chunk_id": 1, "title": "Ep", "guest": "Guest"}]
    res = evaluate_essay(doc, target_word_count=1250, collected_chunks=collected, db=None)
    assert res.body_word_count == 1722
    assert res.word_count_in_range is False
    assert res.passed is False
    assert any("outside acceptable target range [1125, 1375]" in fb for fb in res.feedback)


def test_evaluate_essay_exact_boundaries():
    collected = [{"chunk_id": 1, "title": "Ep", "guest": "Guest"}]

    # Exactly at lower boundary (1,125 words) -> PASS
    doc_lower = _build_essay(body_words=1125, chunk_id=1)
    res_lower = evaluate_essay(doc_lower, target_word_count=1250, collected_chunks=collected, db=None)
    assert res_lower.body_word_count == 1125
    assert res_lower.word_count_in_range is True
    assert res_lower.passed is True

    # Exactly at upper boundary (1,375 words) -> PASS
    doc_upper = _build_essay(body_words=1375, chunk_id=1)
    res_upper = evaluate_essay(doc_upper, target_word_count=1250, collected_chunks=collected, db=None)
    assert res_upper.body_word_count == 1375
    assert res_upper.word_count_in_range is True
    assert res_upper.passed is True

    # 1 word below lower boundary (1,124 words) -> FAIL
    doc_below = _build_essay(body_words=1124, chunk_id=1)
    res_below = evaluate_essay(doc_below, target_word_count=1250, collected_chunks=collected, db=None)
    assert res_below.body_word_count == 1124
    assert res_below.word_count_in_range is False
    assert res_below.passed is False

    # 1 word above upper boundary (1,376 words) -> FAIL
    doc_above = _build_essay(body_words=1376, chunk_id=1)
    res_above = evaluate_essay(doc_above, target_word_count=1250, collected_chunks=collected, db=None)
    assert res_above.body_word_count == 1376
    assert res_above.word_count_in_range is False
    assert res_above.passed is False


def test_evaluate_essay_references_do_not_inflate_body_word_count():
    collected = [{"chunk_id": 1, "title": "Ep", "guest": "Guest"}]
    # Body is 1,250 words (exact target), References is 300 words. Total words is 1,550.
    doc = _build_essay(body_words=1250, chunk_id=1, ref_words=300)
    res = evaluate_essay(doc, target_word_count=1250, collected_chunks=collected, db=None)
    assert res.body_word_count == 1250
    assert res.total_word_count >= 1500
    assert res.word_count_in_range is True
    assert res.passed is True

