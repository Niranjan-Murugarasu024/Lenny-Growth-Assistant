"""
Dedicated Ship 30 for 30 Content Skill (Section 4.2).

Encodes core Ship 30 for 30 ghostwriting principles to turn grounded answers
and transcript research into publication-grade, verified essays.
"""
from __future__ import annotations

import logging
from typing import Sequence

from backend.app.retrieval.search import SearchResult
from backend.app.writing.evaluator import get_acceptable_word_count_range
from backend.app.writing.schemas import WritingBriefRequest

logger = logging.getLogger(__name__)


class Ship30ContentSkill:
    """
    Dedicated skill encoding Ship 30 for 30 writing principles (Section 4.2).

    Principles:
    1. Hook & Narrative Progression:
       - Compelling opening hook that halts scrolling and highlights an urgent tension or counterintuitive truth.
       - Explicit thesis statement in the introductory section (e.g. 'At its core,', 'The key insight is,', 'Fundamentally,').
       - 1-3-1 cadence and structured narrative arc: Status Quo -> Paradigm Shift -> Actionable Frameworks -> Practical Playbook.
    2. Target Length:
       - Approximately 1,250 words for the body of the essay (evaluator acceptance range: 1,125 to 1,375 words).
    3. Skimmable Formatting:
       - Descriptive Markdown subheadings (## Section Heading).
       - Bulleted lists (- item) and numbered steps (1. step) for actionable takeaways.
       - Selective bold emphasis (**key phrase**, **core metric**) so a 30-second skim delivers 80% value.
       - Generous whitespace and concise paragraphs (1-3 sentences per paragraph).
    4. Specific, Useful Takeaways:
       - Concrete mental models, operator frameworks, and checklists directly usable tomorrow.
       - Explicit resolution with a '## Conclusion and Key Takeaways' or '## Actionable Playbook' section.
    5. Grounded Claims & Citations:
       - Grounded strictly in Lenny's Podcast transcripts.
       - Every guest insight, number, and framework cites [Source X] inline.
       - Concluding '## References' section mapping each [Source X] to guest and episode.
    """

    DEFAULT_TARGET_WORD_COUNT: int = 1250

    def format_evidence_context(
        self,
        chunks: Sequence[SearchResult],
        grounded_answer: str | None = None,
    ) -> str:
        """
        Format research evidence into numbered references block for drafting.
        If a grounded chat response is provided, includes it as primary context.
        """
        parts: list[str] = []

        if grounded_answer and grounded_answer.strip():
            parts.append(
                "--- GROUNDED ANSWER CONTEXT FROM CONVERSATION ---\n"
                f"{grounded_answer.strip()}\n"
                "--------------------------------------------------\n"
            )

        if not chunks:
            parts.append("No transcript passages found meeting relevance threshold.")
            return "\n".join(parts)

        parts.append("--- RESEARCH EVIDENCE FROM LENNY'S PODCAST ARCHIVES ---")
        for idx, c in enumerate(chunks, 1):
            parts.append(
                f"[Source {idx}] (Chunk #{c.chunk_id})\n"
                f"Guest: {c.guest}\n"
                f"Episode: {c.title}\n"
                f"Timestamp: {c.timestamp or 'N/A'} | Speaker: {c.speaker or c.guest}\n"
                f"Excerpt:\n{c.chunk_text.strip()}\n"
            )
        return "\n".join(parts)

    def build_system_instruction(self, target_word_count: int = 1250) -> str:
        """
        Encode the Ship 30 for 30 writing principles into the system instruction.
        """
        lower_bound, upper_bound = get_acceptable_word_count_range(target_word_count)

        return (
            "You are an elite ghostwriter specializing in the Ship 30 for 30 essay format and a domain expert "
            "in product management, growth, and company building. You transform grounded insights and transcript "
            "evidence from Lenny's Podcast into substantive, highly readable, publication-grade essays.\n\n"
            "ENCODED SHIP 30 FOR 30 WRITING PRINCIPLES:\n\n"
            f"1. TARGET LENGTH (~{target_word_count} WORDS):\n"
            f"   - Target approximately {target_word_count} words for the body of the essay.\n"
            f"   - MANDATORY CONSTRAINT: The body word count (everything before ## References) MUST be strictly "
            f"between {lower_bound} and {upper_bound} words. Do NOT exceed {upper_bound} words and do NOT write fewer than {lower_bound} words.\n\n"
            "2. STRONG HOOK & CLEAR NARRATIVE PROGRESSION:\n"
            "   - Single primary document title (# Title) that promises a specific, high-value takeaway.\n"
            "   - Opening paragraph MUST open with a compelling hook that immediately halts the reader and frames the central problem.\n"
            "   - The opening section MUST explicitly state the central thesis using clear signals such as 'At its core,', "
            "'The key insight is,', or 'Fundamentally,'.\n"
            "   - Maintain a dynamic 1-3-1 narrative cadence (short punchy sentence, explanatory paragraph, crisp transition).\n"
            "   - Progress logically: Status Quo / Problem -> Paradigm Shift -> In-Depth Frameworks -> Tactical Execution.\n\n"
            "3. SKIMMABLE FORMATTING (HEADINGS, BULLETS, SELECTIVE BOLD):\n"
            "   - Structure the essay with at least 3-4 thematic body sections using clear Markdown headers (## Section Title).\n"
            "   - Use bullet points (- item) or numbered lists (1. step) in each section to break down complex ideas into digestible nuggets.\n"
            "   - Apply selective bold emphasis (**key phrase**, **core metric**, **tactical rule**) so a reader skimming in 30 seconds absorbs 80% of the value.\n"
            "   - Keep paragraphs short (1 to 3 sentences maximum) with generous whitespace.\n\n"
            "4. SPECIFIC, USEFUL TAKEAWAYS:\n"
            "   - Deliver tangible, battle-tested operator playbooks, checklists, and mental models that founders and PMs can execute immediately.\n"
            "   - Conclude with a dedicated '## Conclusion and Actionable Playbook' or '## Key Takeaways' section summarizing practical next steps.\n\n"
            "5. GROUNDED CLAIMS & PROVENANCE:\n"
            "   - Ground all factual assertions, metrics, guest frameworks, and quotes strictly in the provided [Source X] passages.\n"
            "   - Cite sources inline using [Source X] corresponding to the numbered evidence provided.\n"
            "   - NEVER invent guests, episodes, numbers, or citations not present in the evidence.\n"
            "   - Conclude with a '## References' section listing each cited [Source X] with guest name and episode title.\n\n"
            "6. CLEAN OUTPUT:\n"
            "   - Output ONLY the clean Markdown document without conversational preamble or meta-commentary."
        )

    def build_user_prompt(
        self,
        brief: WritingBriefRequest,
        evidence: Sequence[SearchResult],
        grounded_answer: str | None = None,
        revision_instructions: str | None = None,
        prior_draft: str | None = None,
    ) -> str:
        """
        Build the prompt for initial drafting or bounded revision.
        """
        target_wc = brief.target_word_count
        lower_bound, upper_bound = get_acceptable_word_count_range(target_wc)
        evidence_block = self.format_evidence_context(evidence, grounded_answer)

        if revision_instructions and prior_draft:
            return (
                "REVISION TASK — SHIP 30 FOR 30 ESSAY:\n"
                f"Topic: {brief.topic}\n"
                f"Audience: {brief.audience}\n"
                f"Tone: {brief.tone.value}\n"
                f"Target Body Word Count: {target_wc} words (STRICT ACCEPTABLE RANGE: {lower_bound} to {upper_bound} words)\n\n"
                f"PRIOR DRAFT:\n{prior_draft}\n\n"
                f"SPECIFIC REVISION INSTRUCTIONS:\n{revision_instructions}\n\n"
                f"AVAILABLE PODCAST EVIDENCE:\n{evidence_block}\n\n"
                f"Rewrite the essay strictly addressing the revision instructions while preserving factual grounding, "
                f"skimmable formatting (headings, bullets, selective bold), and staying strictly between {lower_bound} and {upper_bound} words."
            )

        thesis_note = (
            f"Central Thesis to develop: {brief.central_thesis}"
            if brief.central_thesis
            else "Formulate a strong, defensible thesis based on the podcast insights."
        )

        grounded_note = ""
        if grounded_answer and grounded_answer.strip():
            grounded_note = (
                "BASE GROUNDED CONVERSATION:\n"
                f"Transform the following grounded conversation insights into the full ~{target_wc}-word Ship 30 for 30 essay:\n"
                f"{grounded_answer.strip()}\n\n"
            )

        if not evidence:
            return (
                "WRITE A SHIP 30 FOR 30 ESSAY:\n"
                f"Topic: {brief.topic}\n"
                f"Audience: {brief.audience}\n"
                f"Purpose: {brief.purpose}\n"
                f"Tone: {brief.tone.value}\n"
                f"{thesis_note}\n"
                f"Target Body Word Count: {target_wc} words (strictly {lower_bound} to {upper_bound} words)\n"
                f"Additional Guidance: {brief.additional_instructions or 'None'}\n\n"
                f"{grounded_note}"
                "RESEARCH EVIDENCE FROM PODCAST ARCHIVES:\n"
                "No direct transcript passages were found matching this topic query.\n\n"
                f"Produce a comprehensive, publication-grade Ship 30 for 30 essay targeting strictly {lower_bound} to {upper_bound} words "
                "grounded in established product management, growth, and startup execution principles. Include a compelling hook, "
                "an explicit opening thesis statement ('At its core,' or 'The key insight is,'), at least 3-4 thematic body sections "
                "with descriptive headers, bullet points, selective bold emphasis, and an actionable playbook conclusion.\n"
                "CRITICAL: Do NOT invent fake transcript citations like [Source 1] and do NOT append a References section."
            )

        return (
            "WRITE A SHIP 30 FOR 30 ESSAY:\n"
            f"Topic: {brief.topic}\n"
            f"Audience: {brief.audience}\n"
            f"Purpose: {brief.purpose}\n"
            f"Tone: {brief.tone.value}\n"
            f"{thesis_note}\n"
            f"Target Body Word Count: {target_wc} words (strictly {lower_bound} to {upper_bound} words)\n"
            f"Additional Guidance: {brief.additional_instructions or 'None'}\n\n"
            f"{grounded_note}"
            f"RESEARCH EVIDENCE FROM PODCAST ARCHIVES:\n"
            f"{evidence_block}\n\n"
            f"Produce the full Markdown essay targeting strictly {lower_bound} to {upper_bound} words, "
            "with a compelling hook, explicit opening thesis, at least 3-4 thematic body sections with headers, "
            "bullet points, selective bold emphasis, grounded claims citing provided [Source X], a concrete actionable playbook conclusion, and a final ## References section."
        )
