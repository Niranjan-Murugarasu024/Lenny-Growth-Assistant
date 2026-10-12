"""
Writing Orchestrator for Ship 30 for 30 essay generation.
Executes multi-stage workflow: research, thesis synthesis, drafting, deterministic
evaluation, bounded revision, and immutable artifact persistence in PostgreSQL.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Sequence
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import Settings, get_settings
from backend.app.database import create_session_factory
from backend.app.ingestion.embedder import OllamaEmbedder
from backend.app.models import ChatMessage, ChatSession, TranscriptChunk, WritingArtifact, WritingArtifactVersion
from backend.app.rag.factory import get_chat_provider
from backend.app.rag.provider_base import ChatProvider, ProviderError
from backend.app.retrieval.search import SearchResult, format_seconds_to_timestamp, search_similar_chunks
from backend.app.writing.evaluator import (
    EssayEvaluation,
    count_words,
    evaluate_essay,
    get_acceptable_word_count_range,
)
from backend.app.writing.html_renderer import render_markdown_to_safe_html, sanitize_html
from backend.app.writing.schemas import WritingBriefRequest
from backend.app.writing.ship30_skill import Ship30ContentSkill

logger = logging.getLogger(__name__)


class WritingService:
    """
    Dedicated service for producing and managing versioned essay artifacts.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        session_factory: sessionmaker[Session] | None = None,
        embedder: OllamaEmbedder | None = None,
        chat_client: ChatProvider | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_factory = session_factory or create_session_factory(settings=self.settings)
        self.embedder = embedder or OllamaEmbedder(
            base_url=self.settings.ollama_base_url,
            model=self.settings.embedding_model,
            dimensions=self.settings.embedding_dimensions,
        )
        if chat_client is not None:
            self.chat_client = chat_client
        else:
            timeout = getattr(self.settings, "writing_timeout_seconds", 300.0)
            from backend.app.database import get_db_setting

            active_prov = provider
            active_model = model
            if not active_prov:
                try:
                    with self.session_factory() as s:
                        active_prov = get_db_setting(s, "active_chat_provider", self.settings.chat_provider)
                        if not active_model:
                            active_model = get_db_setting(s, "active_chat_model", None)
                except Exception:
                    active_prov = self.settings.chat_provider
                    active_model = None

            provider_key = (active_prov or self.settings.chat_provider or "ollama").strip().lower()
            if provider_key in ("cloud", "litellm"):
                provider_key = "nvidia"

            if provider_key == "ollama":
                from backend.app.rag.ollama_client import OllamaChatClient
                self.chat_client = OllamaChatClient(
                    settings=self.settings,
                    default_model=active_model or self.settings.ollama_chat_model,
                    timeout_seconds=timeout,
                )
            elif provider_key in ("nvidia", "nim"):
                from backend.app.rag.nvidia_client import NvidiaChatClient
                self.chat_client = NvidiaChatClient(
                    settings=self.settings,
                    model=active_model or self.settings.nvidia_model,
                    timeout_seconds=timeout,
                )
            else:
                import dataclasses
                eff_settings = self.settings
                if active_prov:
                    eff_settings = dataclasses.replace(eff_settings, chat_provider=active_prov)
                self.chat_client = get_chat_provider(settings=eff_settings)
        self.ship30_skill = Ship30ContentSkill()

    def get_session_grounded_context(
        self,
        session_id: UUID,
    ) -> tuple[list[SearchResult], str | None]:
        """Extract cited transcript chunks and grounded answer from a chat session."""
        session_chunks: list[SearchResult] = []
        grounded_answer: str | None = None
        seen_chunk_ids: set[int] = set()

        with self.session_factory() as db:
            stmt = (
                select(ChatMessage)
                .where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.role == "assistant",
                )
                .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            )
            assistant_msgs = db.scalars(stmt).all()
            for amsg in assistant_msgs:
                if amsg.content and not grounded_answer:
                    grounded_answer = amsg.content
                if amsg.sources:
                    for src in amsg.sources:
                        cid = src.get("chunk_id") or src.get("id")
                        if cid is not None:
                            try:
                                int_cid = int(cid)
                            except (ValueError, TypeError):
                                continue
                            if int_cid not in seen_chunk_ids:
                                seen_chunk_ids.add(int_cid)
                                chunk_row = db.get(TranscriptChunk, int_cid)
                                if chunk_row:
                                    guest = chunk_row.episode.guest if chunk_row.episode else (src.get("guest") or "Unknown Guest")
                                    title = chunk_row.episode.title if chunk_row.episode else (src.get("title") or "Lenny's Podcast")
                                    source_path = chunk_row.episode.source_path if chunk_row.episode else ""
                                    source_url = src.get("source_url") or (chunk_row.episode.source_url if chunk_row.episode else None)
                                    yt_id = chunk_row.episode.youtube_video_id if chunk_row.episode else None
                                    ts_str = src.get("timestamp") or format_seconds_to_timestamp(chunk_row.start_time_seconds)
                                    session_chunks.append(
                                        SearchResult(
                                            chunk_id=chunk_row.id,
                                            chunk_index=chunk_row.chunk_index,
                                            chunk_text=chunk_row.chunk_text,
                                            cosine_distance=0.0,
                                            guest=guest,
                                            title=title,
                                            source_path=source_path,
                                            speaker=chunk_row.speaker,
                                            start_time_seconds=chunk_row.start_time_seconds,
                                            timestamp=ts_str,
                                            embedding_model=self.settings.embedding_model,
                                            source_url=source_url,
                                            youtube_video_id=yt_id,
                                        )
                                    )
                if len(session_chunks) >= 4 and grounded_answer:
                    break

        return session_chunks, grounded_answer

    def research(
        self,
        brief: WritingBriefRequest,
    ) -> tuple[list[SearchResult], bool]:
        """
        Stage 1: Multi-angle focused research against Lenny's Podcast transcripts.
        Integrates grounded context from associated chat session if present.
        Returns deduplicated relevant SearchResult list and an is_supported flag.
        """
        seen_chunk_ids: set[int] = set()
        collected_chunks: list[SearchResult] = []

        # If associated with a chat session, retrieve grounded session sources first
        if brief.session_id:
            try:
                session_chunks, _ = self.get_session_grounded_context(brief.session_id)
                for sc in session_chunks:
                    if sc.chunk_id not in seen_chunk_ids:
                        seen_chunk_ids.add(sc.chunk_id)
                        collected_chunks.append(sc)
            except Exception as e:
                logger.warning("Could not load session grounded chunks for %s: %s", brief.session_id, e)

        # Formulate 2-3 targeted search queries to capture depth and breadth
        queries = [brief.topic]
        if brief.purpose:
            queries.append(f"{brief.topic} framework strategy")
        if brief.central_thesis:
            queries.append(brief.central_thesis)
        else:
            queries.append(f"{brief.topic} lessons examples")

        max_dist = self.settings.retrieval_max_cosine_distance

        for q in queries[:3]:
            candidates = search_similar_chunks(
                query=q,
                top_k=4,
                session_factory=self.session_factory,
                embedder=self.embedder,
                diversify_duplicates=True,
            )
            for c in candidates:
                if c.chunk_id not in seen_chunk_ids and c.cosine_distance <= max_dist:
                    seen_chunk_ids.add(c.chunk_id)
                    collected_chunks.append(c)

        # If no chunks met strict max_dist, check relaxed distance (up to 0.40) to ground entity names
        if not collected_chunks:
            relaxed_dist = min(max_dist + 0.10, 0.40)
            for q in queries[:2]:
                candidates = search_similar_chunks(
                    query=q,
                    top_k=4,
                    session_factory=self.session_factory,
                    embedder=self.embedder,
                    diversify_duplicates=True,
                )
                for c in candidates:
                    if c.chunk_id not in seen_chunk_ids and c.cosine_distance <= relaxed_dist:
                        seen_chunk_ids.add(c.chunk_id)
                        collected_chunks.append(c)

        # Sort: session-grounded chunks first (distance 0.0), then by vector relevance
        collected_chunks.sort(key=lambda x: x.cosine_distance)
        final_chunks = collected_chunks[:6]

        is_supported = len(final_chunks) > 0
        logger.info(
            "Research completed for topic %r: found %d relevant chunks (supported=%s)",
            brief.topic,
            len(final_chunks),
            is_supported,
        )
        return final_chunks, is_supported

    def _format_research_context(self, chunks: Sequence[SearchResult]) -> str:
        """Format research evidence into a numbered references block for drafting."""
        return self.ship30_skill.format_evidence_context(chunks)

    def draft_essay(
        self,
        brief: WritingBriefRequest,
        evidence: list[SearchResult],
        revision_instructions: str | None = None,
        prior_draft: str | None = None,
        grounded_answer: str | None = None,
    ) -> str:
        """
        Stage 2 & 3: Draft or revise a ~1,250-word standalone Ship 30 for 30 essay
        utilizing the dedicated Ship 30 for 30 Content Skill (Section 4.2).
        """
        system_instruction = self.ship30_skill.build_system_instruction(
            target_word_count=brief.target_word_count,
        )
        user_prompt = self.ship30_skill.build_user_prompt(
            brief=brief,
            evidence=evidence,
            grounded_answer=grounded_answer,
            revision_instructions=revision_instructions,
            prior_draft=prior_draft,
        )

        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_prompt},
        ]

        logger.info("Generating Ship 30 for 30 essay draft for topic %r (target=%d)", brief.topic, brief.target_word_count)
        try:
            result = self.chat_client.generate_chat_response(messages=messages)
            self._last_draft_provider = getattr(self.chat_client, "name", self.settings.chat_provider)
            self._last_draft_model = getattr(self.chat_client, "model", self.settings.ollama_chat_model)
            self._last_draft_fallback = False
            return result["content"].strip()
        except ProviderError as exc:
            if getattr(self.settings, "fallback_to_ollama", False) and getattr(self.chat_client, "name", None) != "ollama":
                logger.warning("Cloud provider generation failed (%s); executing explicit fallback to local Ollama", exc)
                from backend.app.rag.ollama_client import OllamaChatClient
                fallback_client = OllamaChatClient(settings=self.settings, timeout_seconds=getattr(self.settings, "writing_timeout_seconds", 300.0))
                result = fallback_client.generate_chat_response(messages=messages)
                self._last_draft_provider = "ollama"
                self._last_draft_model = getattr(fallback_client, "model", self.settings.ollama_chat_model)
                self._last_draft_fallback = True
                self._last_draft_fallback_reason = str(exc)
                return result["content"].strip()
            raise


    def generate_and_persist_essay(
        self,
        brief: WritingBriefRequest,
    ) -> tuple[WritingArtifact, WritingArtifactVersion, EssayEvaluation]:
        """
        Complete end-to-end essay creation workflow:
        Research -> Draft -> Evaluate -> Bounded Revision -> Safe HTML -> PostgreSQL Persistence.
        """
        # 1. Validate session_id exists if provided, and load grounded conversation context
        grounded_answer: str | None = None
        with self.session_factory() as session:
            if brief.session_id:
                chat_session = session.get(ChatSession, brief.session_id)
                if not chat_session:
                    raise ValueError(f"Chat session with ID '{brief.session_id}' does not exist.")
                _, grounded_answer = self.get_session_grounded_context(brief.session_id)

        # 2. Research topic
        evidence, is_supported = self.research(brief)
        chunk_dicts = []
        for c in evidence:
            yt_url = None
            if c.youtube_video_id:
                yt_url = f"https://www.youtube.com/watch?v={c.youtube_video_id}"
                if c.start_time_seconds and c.start_time_seconds > 0:
                    yt_url += f"&t={int(c.start_time_seconds)}s"
            elif c.source_url and "youtube.com" in c.source_url:
                yt_url = c.source_url
                if c.start_time_seconds and c.start_time_seconds > 0 and "&t=" not in yt_url:
                    yt_url += f"&t={int(c.start_time_seconds)}s"

            chunk_dicts.append({
                "chunk_id": c.chunk_id,
                "chunk_index": c.chunk_index,
                "title": c.title,
                "guest": c.guest,
                "source_path": c.source_path,
                "timestamp": c.timestamp,
                "start_time_seconds": c.start_time_seconds,
                "cosine_distance": c.cosine_distance,
                "source_url": c.source_url,
                "youtube_video_id": c.youtube_video_id,
                "youtube_url": yt_url,
            })

        # 3. Initial Draft
        draft = self.draft_essay(brief, evidence, grounded_answer=grounded_answer)

        # 4. Evaluation
        with self.session_factory() as db:
            evaluation = evaluate_essay(
                markdown_text=draft,
                target_word_count=brief.target_word_count,
                collected_chunks=chunk_dicts,
                db=db,
            )

            # 5. Bounded Revision attempt if evaluation failed mandatory criteria
            max_revisions = 1
            revisions_run = 0
            lower_b, upper_b = get_acceptable_word_count_range(brief.target_word_count)
            while not evaluation.passed and revisions_run < max_revisions:
                revisions_run += 1
                logger.info(
                    "Draft failed mandatory criteria (attempt %d/%d, feedback=%s). Running bounded revision...",
                    revisions_run,
                    max_revisions,
                    "; ".join(evaluation.feedback),
                )
                revision_guidance = (
                    f"MANDATORY ACCEPTANCE CRITERIA FAILED:\n"
                    f"- Current body word count: {evaluation.body_word_count} words\n"
                    f"- Required range: strictly {lower_b} to {upper_b} words (target: {brief.target_word_count})\n"
                    f"- Issues to correct: {'; '.join(evaluation.feedback)}\n"
                    f"{'Condense verbose sections and remove filler to stay under ' + str(upper_b) + ' words.' if evaluation.body_word_count > upper_b else 'Elaborate on actionable frameworks and depth to reach at least ' + str(lower_b) + ' words.' if evaluation.body_word_count < lower_b else ''}"
                )
                revised_draft = self.draft_essay(
                    brief=brief,
                    evidence=evidence,
                    revision_instructions=revision_guidance,
                    prior_draft=draft,
                    grounded_answer=grounded_answer,
                )
                revised_eval = evaluate_essay(
                    markdown_text=revised_draft,
                    target_word_count=brief.target_word_count,
                    collected_chunks=chunk_dicts,
                    db=db,
                )
                # Keep revision if it improved
                if revised_eval.passed or abs(revised_eval.word_count_delta) < abs(evaluation.word_count_delta):
                    draft = revised_draft
                    evaluation = revised_eval

        # 6. Extract clean document title from markdown
        title_match = re.search(r"^#\s+([^\n]+)", draft, re.MULTILINE)
        doc_title = title_match.group(1).strip() if title_match else brief.topic[:250]

        # 7. Render Safe HTML
        html_preview = render_markdown_to_safe_html(draft, include_styles=True)

        # 8. Persist Artifact and Version 1 atomically in PostgreSQL
        artifact_status = "completed" if evaluation.passed else "failed"

        provider_name = getattr(self, "_last_draft_provider", getattr(self.chat_client, "name", self.settings.chat_provider))
        model_name = getattr(self, "_last_draft_model", getattr(self.chat_client, "model", self.settings.ollama_chat_model))

        meta_dict = {
            "provider": provider_name,
            "model": model_name,
            "generated_at": time.time(),
        }
        if getattr(self, "_last_draft_fallback", False):
            meta_dict["fallback_occurred"] = True
            meta_dict["fallback_reason"] = getattr(self, "_last_draft_fallback_reason", "Cloud provider failure")

        with self.session_factory() as db:
            artifact = WritingArtifact(
                session_id=brief.session_id,
                title=doc_title,
                artifact_type="essay",
                status=artifact_status,
            )
            db.add(artifact)
            db.flush()

            version1 = WritingArtifactVersion(
                artifact_id=artifact.id,
                version_number=1,
                markdown_content=draft,
                html_content=html_preview,
                word_count=evaluation.body_word_count,
                writing_brief=jsonable_encoder(brief.model_dump(mode="json")),
                sources=jsonable_encoder(chunk_dicts),
                eval_metadata=jsonable_encoder(evaluation.to_dict()),
                model_metadata=jsonable_encoder(meta_dict),
            )
            db.add(version1)
            db.commit()
            db.refresh(artifact)
            db.refresh(version1)

            logger.info(
                "Persisted writing artifact id=%s v=1 for topic %r (wc=%d)",
                artifact.id,
                brief.topic,
                version1.word_count,
            )

        return artifact, version1, evaluation

    def revise_artifact(
        self,
        artifact_id: UUID,
        instructions: str,
        target_word_count: int | None = None,
    ) -> tuple[WritingArtifact, WritingArtifactVersion, EssayEvaluation]:
        """
        Create a new immutable version of an existing artifact based on revision instructions.
        """
        with self.session_factory() as db:
            artifact = db.get(WritingArtifact, artifact_id)
            if not artifact:
                raise ValueError(f"Artifact with ID '{artifact_id}' does not exist.")

            # Load latest version
            versions = sorted(artifact.versions, key=lambda v: v.version_number)
            if not versions:
                raise ValueError(f"Artifact '{artifact_id}' has no existing versions.")
            latest = versions[-1]
            prior_markdown = latest.markdown_content
            prior_brief_dict = latest.writing_brief or {}
            prior_sources = latest.sources or []
            next_version_num = latest.version_number + 1

        brief = WritingBriefRequest.model_validate(prior_brief_dict)
        if target_word_count:
            brief.target_word_count = target_word_count

        # Re-fetch chunks
        chunk_ids = [s["chunk_id"] for s in prior_sources if "chunk_id" in s]
        evidence: list[SearchResult] = []
        if chunk_ids:
            with self.session_factory() as db:
                from backend.app.models import Episode, TranscriptChunk
                stmt = (
                    select(TranscriptChunk, Episode)
                    .join(Episode, TranscriptChunk.episode_id == Episode.id)
                    .where(TranscriptChunk.id.in_(chunk_ids))
                )
                for tc, ep in db.execute(stmt).all():
                    evidence.append(
                        SearchResult(
                            chunk_id=tc.id,
                            chunk_index=tc.chunk_index,
                            chunk_text=tc.chunk_text,
                            cosine_distance=0.1,
                            guest=ep.guest,
                            title=ep.title,
                            source_path=ep.source_path,
                            speaker=tc.speaker,
                            start_time_seconds=tc.start_time_seconds,
                            timestamp=format_seconds_to_timestamp(tc.start_time_seconds),
                            embedding_model=tc.embedding_model,
                        )
                    )

        # Draft revision
        revised_draft = self.draft_essay(
            brief=brief,
            evidence=evidence,
            revision_instructions=instructions,
            prior_draft=prior_markdown,
        )

        with self.session_factory() as db:
            evaluation = evaluate_essay(
                markdown_text=revised_draft,
                target_word_count=brief.target_word_count,
                collected_chunks=prior_sources,
                db=db,
            )

        html_preview = render_markdown_to_safe_html(revised_draft, include_styles=True)

        provider_name = getattr(self.chat_client, "name", self.settings.chat_provider)
        model_name = getattr(self.chat_client, "model", self.settings.ollama_chat_model)

        with self.session_factory() as db:
            artifact = db.get(WritingArtifact, artifact_id)
            new_version = WritingArtifactVersion(
                artifact_id=artifact_id,
                version_number=next_version_num,
                markdown_content=revised_draft,
                html_content=html_preview,
                word_count=evaluation.body_word_count,
                writing_brief=brief.model_dump(mode="json"),
                sources=prior_sources,
                eval_metadata=evaluation.to_dict(),
                model_metadata={
                    "provider": provider_name,
                    "model": model_name,
                    "revision_instructions": instructions,
                    "generated_at": time.time(),
                },
            )
            db.add(new_version)
            artifact.updated_at = func.now()
            db.commit()
            db.refresh(artifact)
            db.refresh(new_version)

            logger.info(
                "Created new version v=%d for artifact %s (wc=%d)",
                next_version_num,
                artifact_id,
                new_version.word_count,
            )

        return artifact, new_version, evaluation

    def save_manual_version(
        self,
        artifact_id: UUID,
        markdown_content: str,
        note: str | None = None,
    ) -> tuple[WritingArtifact, WritingArtifactVersion, EssayEvaluation]:
        """
        Save manually edited Markdown content as a new immutable version.
        Evaluates the content deterministically, renders sanitized HTML preview,
        and transactionally commits the new version.
        """
        with self.session_factory() as db:
            artifact = db.get(WritingArtifact, artifact_id)
            if not artifact:
                raise ValueError(f"Artifact {artifact_id} not found.")

            versions = sorted(artifact.versions, key=lambda v: v.version_number)
            if not versions:
                raise ValueError(f"Artifact {artifact_id} has no existing versions.")

            latest = versions[-1]
            prior_brief_dict = latest.writing_brief or {}
            prior_sources = latest.sources or []
            next_version_num = latest.version_number + 1

        brief = WritingBriefRequest.model_validate(prior_brief_dict)

        with self.session_factory() as db:
            evaluation = evaluate_essay(
                markdown_text=markdown_content,
                target_word_count=brief.target_word_count,
                collected_chunks=prior_sources,
                db=db,
            )

        html_preview = render_markdown_to_safe_html(markdown_content, include_styles=True)

        with self.session_factory() as db:
            artifact = db.get(WritingArtifact, artifact_id)
            new_version = WritingArtifactVersion(
                artifact_id=artifact_id,
                version_number=next_version_num,
                markdown_content=markdown_content,
                html_content=html_preview,
                word_count=evaluation.body_word_count,
                writing_brief=brief.model_dump(mode="json"),
                sources=prior_sources,
                eval_metadata=evaluation.to_dict(),
                model_metadata={
                    "author": "manual_edit",
                    "note": note,
                    "saved_at": time.time(),
                },
            )
            db.add(new_version)
            artifact.updated_at = func.now()
            db.commit()
            db.refresh(artifact)
            db.refresh(new_version)

            logger.info(
                "Created manual version v=%d for artifact %s (wc=%d)",
                next_version_num,
                artifact_id,
                new_version.word_count,
            )

        return artifact, new_version, evaluation

    def create_artifact(
        self,
        title: str,
        content: str,
        artifact_type: str = "document",
        session_id: UUID | None = None,
        sources: list[dict[str, Any]] | None = None,
        writing_brief: dict[str, Any] | None = None,
        model_metadata: dict[str, Any] | None = None,
    ) -> tuple[WritingArtifact, WritingArtifactVersion]:
        """
        Directly persist a Markdown or HTML artifact with server-side sanitization.
        """
        norm_type = (artifact_type or "document").strip().lower()
        if norm_type == "html":
            safe_html = sanitize_html(content, include_styles=True)
            markdown_repr = f"# {title}\n\n```html\n{content}\n```"
            wc = count_words(content)
        else:
            safe_html = render_markdown_to_safe_html(content, include_styles=True)
            markdown_repr = content
            wc = count_words(content)

        clean_title = title.strip() if title and title.strip() else "Untitled Artifact"
        m_meta = model_metadata or {"author": "user_action", "created_at": time.time()}

        with self.session_factory() as db:
            artifact = WritingArtifact(
                session_id=session_id,
                title=clean_title,
                artifact_type=norm_type,
                status="completed",
            )
            db.add(artifact)
            db.flush()

            ver = WritingArtifactVersion(
                artifact_id=artifact.id,
                version_number=1,
                markdown_content=markdown_repr,
                html_content=safe_html,
                word_count=wc,
                writing_brief=writing_brief or {"topic": clean_title},
                sources=sources or [],
                eval_metadata={"passed": True, "artifact_type": norm_type},
                model_metadata=m_meta,
            )
            db.add(ver)
            db.commit()
            db.refresh(artifact)
            db.refresh(ver)
            logger.info("Created and persisted %s artifact %s: %r (wc=%d)", norm_type, artifact.id, clean_title, wc)

        return artifact, ver

    def generate_artifact_from_conversation(
        self,
        session_id: UUID,
        prompt: str,
        artifact_type: str = "document",
        title: str | None = None,
    ) -> tuple[WritingArtifact, WritingArtifactVersion]:
        """
        Generate a Markdown document or complete HTML/CSS snippet from conversation context,
        preserving transcript grounding, and persist it as a sanitized artifact.
        """
        norm_type = (artifact_type or "document").strip().lower()

        # Gather session messages and cited sources
        session_chunks: list[SearchResult] = []
        conversation_text = ""
        with self.session_factory() as db:
            chat_session = db.get(ChatSession, session_id)
            if not chat_session:
                raise ValueError(f"Chat session '{session_id}' not found.")
            session_chunks, _ = self.get_session_grounded_context(session_id)
            stmt = select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())
            msgs = db.scalars(stmt).all()
            turns = [f"{m.role.upper()}: {m.content}" for m in msgs[-6:]]
            conversation_text = "\n\n".join(turns)

        evidence_block = self.ship30_skill.format_evidence_context(session_chunks)

        if norm_type == "html":
            sys_inst = (
                "You are an expert web developer and UI designer. Generate a complete, standalone, visually stunning "
                "HTML/CSS snippet based on the user's request, the conversation context, and the provided Lenny's Podcast evidence.\n\n"
                "REQUIREMENTS:\n"
                "1. Output clean, semantic HTML with an embedded or inline <style> block.\n"
                "2. Include clear headings (<h1>, <h2>), paragraphs (<p>), lists (<ul>, <ol>), tables or cards.\n"
                "3. Cite transcript evidence where appropriate (e.g., [Source X]).\n"
                "4. NEVER include <script>, <iframe>, event handlers (onclick, onerror), or javascript: URLs.\n"
                "5. Return ONLY the HTML markup."
            )
            user_msg = (
                f"TASK: Generate a complete HTML/CSS snippet.\n"
                f"USER PROMPT: {prompt}\n\n"
                f"CONVERSATION CONTEXT:\n{conversation_text}\n\n"
                f"PODCAST EVIDENCE:\n{evidence_block}\n\n"
                f"Generate the complete HTML/CSS snippet now."
            )
        else:
            sys_inst = (
                "You are an expert document writer and growth strategist. Generate a structured, publication-grade "
                "Markdown document based on the conversation context and Lenny's Podcast transcript evidence.\n\n"
                "REQUIREMENTS:\n"
                "1. Single document title (# Title).\n"
                "2. Multiple organized sections with Markdown headings (## Section Title).\n"
                "3. Skimmable formatting with bullet points and bold emphasis.\n"
                "4. Clear actionable takeaways for operators.\n"
                "5. Inline citations [Source X] grounded in the provided transcript evidence, followed by a ## References section.\n"
                "6. Return ONLY the clean Markdown document."
            )
            user_msg = (
                f"TASK: Generate a Markdown document.\n"
                f"USER PROMPT: {prompt}\n\n"
                f"CONVERSATION CONTEXT:\n{conversation_text}\n\n"
                f"PODCAST EVIDENCE:\n{evidence_block}\n\n"
                f"Generate the complete Markdown document now."
            )

        messages = [
            {"role": "system", "content": sys_inst},
            {"role": "user", "content": user_msg},
        ]

        logger.info("Generating %s artifact for session %s with prompt %r", norm_type, session_id, prompt[:60])
        result = self.chat_client.generate_chat_response(messages=messages)
        generated_content = result["content"].strip()

        # Derive title
        derived_title = title
        if not derived_title:
            t_match = re.search(r"^#\s+([^\n]+)", generated_content, re.MULTILINE)
            if t_match:
                derived_title = t_match.group(1).strip()
            elif norm_type == "html":
                h_match = re.search(r"<h[12][^>]*>(.*?)</h[12]>", generated_content, re.IGNORECASE)
                if h_match:
                    derived_title = re.sub(r"<[^>]+>", "", h_match.group(1)).strip()
                else:
                    derived_title = prompt[:60].strip()
            else:
                derived_title = prompt[:60].strip()

        chunk_dicts = [
            {
                "chunk_id": c.chunk_id,
                "chunk_index": c.chunk_index,
                "title": c.title,
                "guest": c.guest,
                "source_path": c.source_path,
                "timestamp": c.timestamp,
                "start_time_seconds": c.start_time_seconds,
            }
            for c in session_chunks
        ]

        provider_name = getattr(self.chat_client, "name", self.settings.chat_provider)
        model_name = getattr(self.chat_client, "model", self.settings.ollama_chat_model)

        return self.create_artifact(
            title=derived_title or "Conversation Artifact",
            content=generated_content,
            artifact_type=norm_type,
            session_id=session_id,
            sources=chunk_dicts,
            writing_brief={"prompt": prompt, "session_id": str(session_id)},
            model_metadata={
                "provider": provider_name,
                "model": model_name,
                "source": "conversation_context",
                "generated_at": time.time(),
            },
        )


