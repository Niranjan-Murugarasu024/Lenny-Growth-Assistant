from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re
from typing import Any, Sequence

from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.database import create_session_factory
from backend.app.ingestion.embedder import OllamaEmbedder
from backend.app.rag.factory import get_chat_provider
from backend.app.rag.provider_base import ChatProvider, ProviderError
from backend.app.rag.prompt import build_chat_messages
from backend.app.retrieval.search import SearchResult, search_similar_chunks

logger = logging.getLogger(__name__)


@dataclass
class RAGResponse:
    """Complete grounded answer and validated retrieval provenance."""

    content: str
    provider: str
    model: str
    sources: list[dict[str, Any]]
    retrieval_count: int
    relevant_count: int


class RAGService:
    """Orchestrator for Retrieval-Augmented Generation."""

    def __init__(
        self,
        settings: Settings | None = None,
        session_factory: sessionmaker[Session] | None = None,
        embedder: OllamaEmbedder | None = None,
        chat_client: ChatProvider | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_factory = session_factory or create_session_factory(settings=self.settings)
        self.embedder = embedder or OllamaEmbedder(
            base_url=self.settings.ollama_base_url,
            model=self.settings.embedding_model,
        )
        self.chat_client = chat_client or get_chat_provider(settings=self.settings)

    def answer_question(
        self,
        user_question: str,
        conversation_history: list[dict[str, str]] | None = None,
        max_distance: float | None = None,
        top_k: int | None = None,
    ) -> RAGResponse:
        """
        Execute RAG workflow:
        1. Retrieve top-k passages using exact vector search with duplicate diversification.
        2. Evaluate passages against the cosine-distance relevance threshold.
        3. Construct prompt with bounded conversation history and retrieved passages.
        4. Request generation from Ollama chat model.
        5. Validate returned citations against real retrieved chunks.
        """
        cleaned_question = user_question.strip()
        effective_top_k = top_k or self.settings.retrieval_top_k
        effective_max_dist = (
            max_distance
            if max_distance is not None
            else self.settings.retrieval_max_cosine_distance
        )

        # 1. Retrieve candidates
        raw_results = search_similar_chunks(
            query=cleaned_question,
            top_k=effective_top_k,
            session_factory=self.session_factory,
            embedder=self.embedder,
            diversify_duplicates=True,
        )

        # 2. Filter by relevance threshold
        relevant_chunks: list[SearchResult] = [
            r for r in raw_results if r.cosine_distance <= effective_max_dist
        ]

        logger.info(
            "Retrieved %d chunks for query %r (%d passed max_distance=%.2f)",
            len(raw_results),
            cleaned_question,
            len(relevant_chunks),
            effective_max_dist,
        )

        # 3. Handle bounded history
        bounded_history: list[dict[str, str]] = []
        if conversation_history:
            limit = self.settings.chat_max_history_messages
            bounded_history = conversation_history[-limit:]

        # 4. If no chunks pass threshold -> unsupported query
        if not relevant_chunks:
            # When retrieval fails to find supported evidence, query model with explicit guidance
            messages = build_chat_messages(
                user_question=cleaned_question,
                retrieved_chunks=[],
                conversation_history=bounded_history,
            )
            fallback_occurred = False
            try:
                chat_result = self.chat_client.generate_chat_response(messages=messages)
            except ProviderError as exc:
                if getattr(self.settings, "fallback_to_ollama", False) and getattr(self.chat_client, "name", None) != "ollama":
                    logger.warning("Cloud provider generation failed (%s); executing fallback to local Ollama", exc)
                    from backend.app.rag.ollama_client import OllamaChatClient
                    fallback_client = OllamaChatClient(settings=self.settings)
                    chat_result = fallback_client.generate_chat_response(messages=messages)
                    fallback_occurred = True
                else:
                    raise

            if fallback_occurred:
                provider_name = "ollama (fallback)"
            else:
                provider_name = getattr(self.chat_client, "name", None)
                if not isinstance(provider_name, str):
                    provider_name = self.settings.chat_provider

            return RAGResponse(
                content=chat_result["content"],
                provider=provider_name,
                model=chat_result["model"],
                sources=[],
                retrieval_count=len(raw_results),
                relevant_count=0,
            )

        # 5. Build prompt with relevant evidence
        messages = build_chat_messages(
            user_question=cleaned_question,
            retrieved_chunks=relevant_chunks,
            conversation_history=bounded_history,
        )

        # 6. Generate answer from model provider
        fallback_occurred = False
        try:
            chat_result = self.chat_client.generate_chat_response(messages=messages)
        except ProviderError as exc:
            if getattr(self.settings, "fallback_to_ollama", False) and getattr(self.chat_client, "name", None) != "ollama":
                logger.warning("Cloud provider generation failed (%s); executing fallback to local Ollama", exc)
                from backend.app.rag.ollama_client import OllamaChatClient
                fallback_client = OllamaChatClient(settings=self.settings)
                chat_result = fallback_client.generate_chat_response(messages=messages)
                fallback_occurred = True
            else:
                raise

        raw_content = chat_result["content"]

        # 7. Validate and structure source references
        # Application-side source validation: only return actual retrieved chunk records
        validated_sources = self._build_validated_sources(
            relevant_chunks=relevant_chunks,
            generated_text=raw_content,
        )

        if fallback_occurred:
            provider_name = "ollama (fallback)"
        else:
            provider_name = getattr(self.chat_client, "name", None)
            if not isinstance(provider_name, str):
                provider_name = self.settings.chat_provider

        return RAGResponse(
            content=raw_content,
            provider=provider_name,
            model=chat_result["model"],
            sources=validated_sources,
            retrieval_count=len(raw_results),
            relevant_count=len(relevant_chunks),
        )

    def _build_validated_sources(
        self,
        relevant_chunks: Sequence[SearchResult],
        generated_text: str,
    ) -> list[dict[str, Any]]:
        """
        Build verified structured source objects for in-context chunks.

        Detects cited source markers (e.g. [Source 1], [Source 2]) and attaches
        verifiable metadata from the actual database chunk records.
        """
        # Find which [Source X] numbers appear in the answer
        cited_indices: set[int] = set()
        for match in re.finditer(r"\[Source\s+(\d+)\]", generated_text, re.IGNORECASE):
            try:
                cited_indices.add(int(match.group(1)))
            except ValueError:
                pass

        sources: list[dict[str, Any]] = []
        for idx, chunk in enumerate(relevant_chunks, 1):
            excerpt = chunk.chunk_text.replace("\n", " ").strip()
            if len(excerpt) > 350:
                excerpt = excerpt[:347] + "..."

            yt_url = None
            if chunk.youtube_video_id:
                yt_url = f"https://www.youtube.com/watch?v={chunk.youtube_video_id}"
                if chunk.start_time_seconds and chunk.start_time_seconds > 0:
                    yt_url += f"&t={int(chunk.start_time_seconds)}s"
            elif chunk.source_url and "youtube.com" in chunk.source_url:
                yt_url = chunk.source_url
                if chunk.start_time_seconds and chunk.start_time_seconds > 0 and "&t=" not in yt_url:
                    yt_url += f"&t={int(chunk.start_time_seconds)}s"

            source_obj = {
                "citation_index": idx,
                "is_cited": idx in cited_indices if cited_indices else True,
                "chunk_id": chunk.chunk_id,
                "chunk_index": chunk.chunk_index,
                "source_path": chunk.source_path,
                "guest": chunk.guest,
                "title": chunk.title,
                "speaker": chunk.speaker,
                "timestamp": chunk.timestamp,
                "start_time_seconds": chunk.start_time_seconds,
                "cosine_distance": chunk.cosine_distance,
                "excerpt": excerpt,
                "alternate_sources": chunk.alternate_sources,
                "source_url": chunk.source_url,
                "youtube_video_id": chunk.youtube_video_id,
                "youtube_url": yt_url,
            }
            sources.append(source_obj)

        return sources
