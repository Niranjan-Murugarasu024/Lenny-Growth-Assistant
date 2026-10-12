from __future__ import annotations

from typing import Sequence

from backend.app.retrieval.search import SearchResult

SYSTEM_PROMPT = """You are The Lenny Growth Assistant, an AI expert on product management, growth, startup scaling, leadership, and company strategy, grounded in Lenny's Podcast transcript archives.

Your instructions:
1. Answer the user's question using ONLY the provided transcript evidence.
2. Distinguish transcript evidence from your own connective explanation. Clearly attribute claims to the specific guest speaking (e.g. "According to Ben Williams...", "Lauryn Isford highlights that...").
3. Avoid inventing guest claims, episode titles, quotations, metrics, or timestamps not present in the supplied evidence.
4. If the provided transcript evidence is empty, insufficient, or unrelated to the question, acknowledge this directly and state: "I could not find sufficient evidence in Lenny's Podcast transcripts to answer this question." Do not attempt to guess or hallucinate facts beyond the transcripts.
5. Provide numbered citations referring ONLY to the supplied evidence sources (e.g. [Source 1], [Source 2]). Do not reference sources that are not in the provided context.
"""


def format_transcript_context(chunks: Sequence[SearchResult]) -> str:
    """Format retrieved transcript chunks into structured prompt context."""
    if not chunks:
        return "No relevant transcript passages found."

    context_parts: list[str] = []
    for idx, c in enumerate(chunks, 1):
        spk = c.speaker or c.guest or "Unknown"
        ts = c.timestamp or "N/A"
        clean_text = c.chunk_text.strip()
        context_parts.append(
            f"--- [Source {idx}] ---\n"
            f"Guest: {c.guest}\n"
            f"Episode: {c.title}\n"
            f"Timestamp: {ts} | Speaker: {spk}\n"
            f"Passage:\n{clean_text}\n"
        )

    return "\n".join(context_parts)


def build_chat_messages(
    user_question: str,
    retrieved_chunks: Sequence[SearchResult],
    conversation_history: list[dict[str, str]] | None = None,
    system_prompt: str = SYSTEM_PROMPT,
) -> list[dict[str, str]]:
    """
    Construct the message array for the chat model.

    Keeps system instructions separate from user messages and documents,
    includes bounded recent conversation history, and structures current
    evidence into the final user prompt.
    """
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt}
    ]

    # Append bounded recent conversation turns (excluding system)
    if conversation_history:
        for turn in conversation_history:
            role = turn.get("role", "")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content.strip():
                messages.append({"role": role, "content": content.strip()})

    # Construct current user turn with evidence
    if retrieved_chunks:
        evidence_block = format_transcript_context(retrieved_chunks)
        user_content = (
            f"Here are relevant passages from Lenny's Podcast transcripts:\n\n"
            f"{evidence_block}\n\n"
            f"User Question: {user_question.strip()}\n\n"
            f"Answer the question using the transcript evidence above. "
            f"Cite relevant evidence using [Source X]."
        )
    else:
        user_content = (
            f"Transcript Evidence: None found (no passages met the relevance threshold).\n\n"
            f"User Question: {user_question.strip()}\n\n"
            f"Note: Since no relevant transcript passages are available, explicitly acknowledge "
            f"insufficient evidence rather than fabricating an answer."
        )

    messages.append({"role": "user", "content": user_content})
    return messages
