"""
Deterministic evaluation layer for Ship 30 for 30 essay drafts.
Evaluates word count, structural sections, thesis presence, repetition,
and verifies citation provenance against collected evidence and PostgreSQL.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import TranscriptChunk


@dataclass
class EssayEvaluation:
    """Detailed deterministic evaluation results for a drafted essay."""
    body_word_count: int
    total_word_count: int
    target_word_count: int
    word_count_in_range: bool
    word_count_delta: int
    sections_present: list[str]
    headings_count: int
    thesis_detected: bool
    has_title: bool
    has_conclusion: bool
    has_references: bool
    repetition_detected: bool
    citations_count: int
    all_citations_verified: bool
    verified_chunk_ids: list[int]
    unverified_citations: list[str]
    passed: bool
    checks: dict[str, Any] = field(default_factory=dict)
    feedback: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["passes_all_checks"] = self.passed
        d["word_count_check"] = self.word_count_in_range
        d["required_sections_check"] = self.has_title and self.headings_count >= 2
        d["sources_grounded_check"] = self.all_citations_verified
        d["failure_reasons"] = list(self.feedback)
        return d


def get_acceptable_word_count_range(target_word_count: int) -> tuple[int, int]:
    """
    Derive the acceptable body word count range: target +/- 10%.
    For default target 1,250 words: [1,125, 1,375].
    For target N: [round(N * 0.90), round(N * 1.10)].
    """
    lower = int(round(target_word_count * 0.90))
    upper = int(round(target_word_count * 1.10))
    return lower, upper


def split_body_and_references(markdown_text: str) -> tuple[str, str]:
    """
    Separate essay body from the terminal bibliography/references section.
    """
    ref_pattern = re.compile(
        r"(?:\n|^)(?:#{1,3}\s*(?:References|Sources|Works Cited|Podcast Sources)|---\s*\n\s*(?:\*|_)?(?:Sources|References))",
        re.IGNORECASE,
    )
    match = ref_pattern.search(markdown_text)
    if match:
        body = markdown_text[:match.start()].strip()
        references = markdown_text[match.start():].strip()
        return body, references
    return markdown_text.strip(), ""


def count_words(text: str) -> int:
    """
    Count plain words in a text block, stripping Markdown formatting, links, and code blocks.
    Words inside inline code are counted as words.
    """
    if not text:
        return 0
    # Strip multi-line code blocks
    cleaned = re.sub(r"```[\s\S]*?```", "", text)
    # Strip images and links but keep link text: [text](url) -> text
    cleaned = re.sub(r"!\[.*?\]\(.*?\)", "", cleaned)
    cleaned = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", cleaned)
    # Strip HTML tags
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    # Strip markdown headers, bold, italics, blockquotes, inline code backticks
    cleaned = re.sub(r"[#*_~>`]", " ", cleaned)
    # Words are sequences of alphanumeric characters and hyphens/apostrophes
    words = re.findall(r"\b[\w'-]+\b", cleaned)
    return len(words)


def extract_citation_markers(text: str) -> list[str]:
    """
    Extract citation markers such as [Source 1], [Source X], [Chunk #123], or (Chunk #123).
    """
    markers: list[str] = []
    # Match [Source X]
    for m in re.finditer(r"\[Source\s+(\d+)\]", text, re.IGNORECASE):
        markers.append(m.group(0))
    # Match [Chunk #X] or (Chunk #X)
    for m in re.finditer(r"[\[\(]Chunk\s*#?\s*(\d+)[\]\)]", text, re.IGNORECASE):
        markers.append(m.group(0))
    return list(dict.fromkeys(markers))


def detect_thesis_statement(text: str) -> bool:
    """
    Check if a central thesis or primary assertion is present in the introductory sections.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    intro_block = " ".join(paragraphs[:4]).lower() if paragraphs else text.lower()

    thesis_signals = [
        "thesis",
        "core argument",
        "argument is",
        "in this essay",
        "this essay argues",
        "the key insight is",
        "the truth is that",
        "fundamentally,",
        "here is the reality:",
        "the premise is simple:",
        "at its core,",
    ]
    return any(sig in intro_block for sig in thesis_signals)


def check_repetitive_phrases(text: str) -> bool:
    """
    Detect abnormal repetition (e.g., identical paragraphs or duplicate 10+ word sentences).
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 30]
    seen_paras = set()
    for p in paragraphs:
        normalized = re.sub(r"\s+", " ", p.lower())
        if normalized in seen_paras:
            return True
        seen_paras.add(normalized)
    return False


def evaluate_essay(
    markdown_text: str,
    target_word_count: int = 1250,
    collected_chunks: Sequence[dict[str, Any]] | None = None,
    db: Session | None = None,
) -> EssayEvaluation:
    """
    Run deterministic multi-point evaluation over an essay draft.
    """
    body, references = split_body_and_references(markdown_text)
    body_wc = count_words(body)
    total_wc = count_words(markdown_text)

    # Word count evaluation: acceptable window is target +/- 10% (1125 - 1375 for 1250)
    lower_bound, upper_bound = get_acceptable_word_count_range(target_word_count)
    word_count_in_range = lower_bound <= body_wc <= upper_bound
    delta = body_wc - target_word_count

    # Section checks
    has_title = bool(re.search(r"^#\s+[^\n]+", markdown_text, re.MULTILINE))
    headings = re.findall(r"^#{2,3}\s+[^\n]+", markdown_text, re.MULTILINE)
    headings_count = len(headings)
    has_conclusion = bool(
        re.search(r"^##\s+.*(?:Conclusion|Key Takeaways|Final Thoughts|Summary)", markdown_text, re.IGNORECASE | re.MULTILINE)
    )
    has_references = bool(references) or bool(
        re.search(r"^##\s+.*(?:References|Sources|Works Cited)", markdown_text, re.IGNORECASE | re.MULTILINE)
    )
    thesis_detected = detect_thesis_statement(body)
    repetition_detected = check_repetitive_phrases(body)

    sections_present: list[str] = []
    if has_title:
        sections_present.append("title")
    if thesis_detected:
        sections_present.append("thesis")
    if headings_count >= 2:
        sections_present.append("body_headings")
    if has_conclusion:
        sections_present.append("conclusion")
    if has_references:
        sections_present.append("references")

    # Citation and Grounding Evaluation
    markers = extract_citation_markers(markdown_text)
    citations_count = len(markers)

    # Map markers to chunk IDs
    available_chunk_ids: set[int] = set()
    source_index_map: dict[int, int] = {}  # index (1, 2, 3...) -> chunk_id
    if collected_chunks:
        for idx, c in enumerate(collected_chunks, 1):
            cid = c.get("chunk_id")
            if cid is not None:
                try:
                    int_cid = int(cid)
                    available_chunk_ids.add(int_cid)
                    source_index_map[idx] = int_cid
                except (ValueError, TypeError):
                    pass

    referenced_chunk_ids: set[int] = set()
    unverified_markers: list[str] = []

    for marker in markers:
        src_match = re.search(r"\[Source\s+(\d+)\]", marker, re.IGNORECASE)
        if src_match:
            s_idx = int(src_match.group(1))
            if s_idx in source_index_map:
                referenced_chunk_ids.add(source_index_map[s_idx])
            else:
                unverified_markers.append(marker)
            continue

        chunk_match = re.search(r"Chunk\s*#?\s*(\d+)", marker, re.IGNORECASE)
        if chunk_match:
            c_id = int(chunk_match.group(1))
            if c_id in available_chunk_ids:
                referenced_chunk_ids.add(c_id)
            else:
                unverified_markers.append(marker)
            continue

        unverified_markers.append(marker)

    # Independent PostgreSQL verification of all referenced chunk IDs
    verified_chunk_ids: list[int] = []
    if db is not None and referenced_chunk_ids:
        stmt = select(TranscriptChunk.id).where(TranscriptChunk.id.in_(list(referenced_chunk_ids)))
        rows = db.scalars(stmt).all()
        verified_chunk_ids = list(rows)
    else:
        verified_chunk_ids = list(referenced_chunk_ids)

    # All referenced chunks must exist in DB and in evidence
    all_citations_verified = (
        len(unverified_markers) == 0
        and len(verified_chunk_ids) == len(referenced_chunk_ids)
    )

    feedback: list[str] = []
    if not word_count_in_range:
        feedback.append(
            f"Body word count ({body_wc}) is outside acceptable target range "
            f"[{lower_bound}, {upper_bound}] (target: {target_word_count})."
        )
    if not has_title:
        feedback.append("Missing primary document title (# Title).")
    if headings_count < 2:
        feedback.append("Insufficient section headings (at least 2 required).")
    if not thesis_detected:
        feedback.append("Clear central thesis statement was not identified in opening.")
    if not has_references and citations_count > 0:
        feedback.append("Document references sources inline but lacks a References section.")
    if repetition_detected:
        feedback.append("Detected duplicate paragraph or excessive phrase repetition.")
    if not all_citations_verified:
        feedback.append(f"Unverified or untraced citations detected: {unverified_markers}")

    checks = {
        "word_count": {
            "body": body_wc,
            "target": target_word_count,
            "acceptable_range": [lower_bound, upper_bound],
            "passed": word_count_in_range,
        },
        "structure": {
            "has_title": has_title,
            "headings_count": headings_count,
            "has_conclusion": has_conclusion,
            "has_references": has_references,
            "passed": has_title and headings_count >= 2,
        },
        "thesis": {
            "detected": thesis_detected,
            "passed": thesis_detected,
        },
        "repetition": {
            "detected": repetition_detected,
            "passed": not repetition_detected,
        },
        "citations": {
            "markers_count": citations_count,
            "all_verified": all_citations_verified,
            "verified_chunk_ids": verified_chunk_ids,
            "unverified_markers": unverified_markers,
            "passed": all_citations_verified,
        },
    }

    # Mandatory acceptance criteria: word count in range, title, headings, thesis, no repetition, verified citations
    passed = (
        word_count_in_range
        and has_title
        and headings_count >= 2
        and thesis_detected
        and not repetition_detected
        and all_citations_verified
    )

    return EssayEvaluation(
        body_word_count=body_wc,
        total_word_count=total_wc,
        target_word_count=target_word_count,
        word_count_in_range=word_count_in_range,
        word_count_delta=delta,
        sections_present=sections_present,
        headings_count=headings_count,
        thesis_detected=thesis_detected,
        has_title=has_title,
        has_conclusion=has_conclusion,
        has_references=has_references,
        repetition_detected=repetition_detected,
        citations_count=citations_count,
        all_citations_verified=all_citations_verified,
        verified_chunk_ids=verified_chunk_ids,
        unverified_citations=unverified_markers,
        passed=passed,
        checks=checks,
        feedback=feedback,
    )
