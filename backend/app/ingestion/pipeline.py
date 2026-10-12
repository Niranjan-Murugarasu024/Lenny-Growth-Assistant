from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import get_settings
from backend.app.database import create_session_factory
from backend.app.ingestion.chunker import TokenCounter, chunk_transcript
from backend.app.ingestion.embedder import OllamaEmbedder
from backend.app.ingestion.parser import parse_transcript_source
from backend.app.models import Episode, IngestionRun, TranscriptChunk

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Summary of ingestion pipeline execution."""

    run_id: int | None
    status: str
    total_episodes: int
    success_count: int
    skipped_count: int
    failed_count: int
    error_summary: dict[str, str] = field(default_factory=dict)
    episode_details: list[dict[str, Any]] = field(default_factory=list)


def _metadata_has_changed(existing: Episode, parsed: Any) -> bool:
    """Check if episode metadata or raw source hash changed while dialogue stayed identical."""
    if existing.source_sha256 != parsed.source_sha256:
        return True
    if existing.guest != parsed.guest:
        return True
    if existing.title != parsed.title:
        return True
    if existing.source_platform != parsed.source_platform:
        return True
    if existing.source_url != parsed.source_url:
        return True
    if existing.youtube_video_id != parsed.youtube_video_id:
        return True
    if existing.spotify_url != parsed.spotify_url:
        return True
    if existing.spotify_id != parsed.spotify_id:
        return True
    if existing.publish_date != parsed.publish_date:
        return True
    if existing.duration_seconds != parsed.duration_seconds:
        return True
    if (existing.raw_metadata or {}) != (parsed.raw_metadata or {}):
        return True
    return False


def discover_transcript_files(episodes_dir: Path | str) -> list[Path]:
    """Discover all transcript.md source files beneath the episodes directory."""
    ep_path = Path(episodes_dir).resolve()
    if not ep_path.is_dir():
        return []
    return sorted(ep_path.rglob("transcript.md"))


def run_ingestion_pipeline(
    archive_root: Path | str,
    episodes_dir: Path | str,
    session_factory: sessionmaker[Session] | None = None,
    embedder: OllamaEmbedder | None = None,
    tokenizer: TokenCounter | None = None,
    limit: int | None = None,
    episode_names: list[str] | None = None,
    target_tokens: int | None = None,
    overlap_tokens: int | None = None,
    chunker_version: str = "v1",
    dry_run: bool = False,
) -> PipelineResult:
    """
    Execute corpus ingestion pipeline from parsing through chunking, embedding, and DB persistence.

    Enforces idempotency, preserves duplicate-dialogue pairs, makes Ollama calls outside
    transactions, and guarantees atomic rollback on per-episode failures.
    """
    settings = get_settings()
    archive_root_path = Path(archive_root).resolve()
    episodes_dir_path = Path(episodes_dir).resolve()

    if not archive_root_path.is_dir():
        raise FileNotFoundError(f"Archive root not found: {archive_root_path}")
    if not episodes_dir_path.is_dir():
        raise FileNotFoundError(f"Episodes directory not found: {episodes_dir_path}")

    # Discover target transcript files
    all_transcripts = discover_transcript_files(episodes_dir_path)
    if episode_names:
        name_set = {n.strip().lower() for n in episode_names if n.strip()}
        transcript_files = [
            f for f in all_transcripts
            if f.parent.name.lower() in name_set or f.parent.name in episode_names
        ]
    else:
        transcript_files = all_transcripts
        if limit is not None and limit > 0:
            transcript_files = transcript_files[:limit]

    total_episodes = len(transcript_files)
    logger.info("Starting ingestion pipeline for %d episodes (dry_run=%s)", total_episodes, dry_run)

    # In dry-run mode, skip database session and Ollama embeddings
    if dry_run:
        from backend.app.ingestion.cli import run_dry_run
        dry_report = run_dry_run(
            archive_root=archive_root_path,
            episodes_dir=episodes_dir_path,
            limit=limit,
            target_tokens=target_tokens or settings.chunk_target_tokens,
            overlap_tokens=overlap_tokens or settings.chunk_overlap_tokens,
            episode_names=episode_names,
        )
        return PipelineResult(
            run_id=None,
            status="dry_run",
            total_episodes=dry_report["episodes_processed"],
            success_count=dry_report["episodes_processed"] - len(dry_report["parsing_errors"]),
            skipped_count=len(dry_report["skipped_files"]),
            failed_count=len(dry_report["parsing_errors"]),
            error_summary={e["source_path"]: e["error"] for e in dry_report["parsing_errors"]},
        )

    db_factory = session_factory or create_session_factory()
    active_embedder = embedder or OllamaEmbedder()
    active_tokenizer = tokenizer or TokenCounter()
    tgt = target_tokens if target_tokens is not None else settings.chunk_target_tokens
    ovr = overlap_tokens if overlap_tokens is not None else settings.chunk_overlap_tokens

    # Create IngestionRun record
    run_id: int | None = None
    with db_factory() as session:
        with session.begin():
            run_record = IngestionRun(
                status="running",
                total_episodes=total_episodes,
                success_count=0,
                skipped_count=0,
                failed_count=0,
                error_summary={},
            )
            session.add(run_record)
        run_id = run_record.id

    success_count = 0
    skipped_count = 0
    failed_count = 0
    error_summary: dict[str, str] = {}
    episode_details: list[dict[str, Any]] = []

    for ep_idx, file_path in enumerate(transcript_files, 1):
        source_rel: str = ""
        try:
            # 1. Parse transcript source
            parsed = parse_transcript_source(file_path, archive_root_path)
            source_rel = parsed.source_path

            if parsed.parse_error and not parsed.frontmatter_found:
                raise ValueError(f"Parsing failed: {parsed.parse_error}")

            if not parsed.dialogue_body.strip():
                logger.warning("Skipping episode with empty dialogue body: %s", source_rel)
                skipped_count += 1
                episode_details.append({
                    "source_path": source_rel,
                    "status": "skipped",
                    "reason": "empty_dialogue_body",
                })
                continue

            # 2. Check existing episode in DB for idempotency
            with db_factory() as session:
                existing = session.query(Episode).filter_by(source_path=source_rel).first()

            if existing is not None:
                body_unchanged = (existing.body_sha256 == parsed.body_sha256)
                model_unchanged = (existing.embedding_model == active_embedder.model)
                chunker_unchanged = (existing.chunker_version == chunker_version)

                if body_unchanged and model_unchanged and chunker_unchanged:
                    # Dialogue & embeddings are identical; check if metadata changed
                    if _metadata_has_changed(existing, parsed):
                        logger.info("Metadata-only change detected for %s; updating metadata", source_rel)
                        with db_factory() as session:
                            with session.begin():
                                ep_to_update = session.query(Episode).filter_by(source_path=source_rel).one()
                                ep_to_update.guest = parsed.guest
                                ep_to_update.title = parsed.title
                                ep_to_update.source_platform = parsed.source_platform
                                ep_to_update.source_url = parsed.source_url
                                ep_to_update.youtube_video_id = parsed.youtube_video_id
                                ep_to_update.spotify_url = parsed.spotify_url
                                ep_to_update.spotify_id = parsed.spotify_id
                                ep_to_update.publish_date = parsed.publish_date
                                ep_to_update.duration_seconds = parsed.duration_seconds
                                ep_to_update.raw_metadata = parsed.raw_metadata
                                ep_to_update.source_sha256 = parsed.source_sha256

                        success_count += 1
                        episode_details.append({
                            "source_path": source_rel,
                            "status": "metadata_refreshed",
                        })
                        continue
                    else:
                        # Completely identical — skip
                        logger.info("[%d/%d] Skipped unchanged episode: %s", ep_idx, total_episodes, source_rel)
                        skipped_count += 1
                        episode_details.append({
                            "source_path": source_rel,
                            "status": "skipped",
                            "reason": "unchanged",
                        })
                        continue

            # 3. Generate chunks
            chunks = chunk_transcript(
                parsed=parsed,
                target_tokens=tgt,
                overlap_tokens=ovr,
                tokenizer=active_tokenizer,
                chunker_version=chunker_version,
            )

            if not chunks:
                logger.warning("No chunks generated for %s; skipping", source_rel)
                skipped_count += 1
                episode_details.append({
                    "source_path": source_rel,
                    "status": "skipped",
                    "reason": "no_chunks_generated",
                })
                continue

            # 4. Generate embeddings (executed OUTSIDE the database transaction)
            chunk_texts = [c.chunk_text for c in chunks]
            embeddings = active_embedder.embed_documents(chunk_texts)

            if len(embeddings) != len(chunks):
                raise ValueError(
                    f"Embedding count mismatch: generated {len(chunks)} chunks but received {len(embeddings)} vectors"
                )

            # 5. Persist episode and chunks transactionally
            with db_factory() as session:
                with session.begin():
                    ep = session.query(Episode).filter_by(source_path=source_rel).first()
                    if ep is None:
                        ep = Episode(
                            source_path=source_rel,
                            guest=parsed.guest,
                            title=parsed.title,
                            source_platform=parsed.source_platform,
                            source_url=parsed.source_url,
                            youtube_video_id=parsed.youtube_video_id,
                            spotify_url=parsed.spotify_url,
                            spotify_id=parsed.spotify_id,
                            publish_date=parsed.publish_date,
                            duration_seconds=parsed.duration_seconds,
                            raw_metadata=parsed.raw_metadata,
                            source_sha256=parsed.source_sha256,
                            body_sha256=parsed.body_sha256,
                            embedding_model=active_embedder.model,
                            chunker_version=chunker_version,
                        )
                        session.add(ep)
                        session.flush()
                    else:
                        ep.guest = parsed.guest
                        ep.title = parsed.title
                        ep.source_platform = parsed.source_platform
                        ep.source_url = parsed.source_url
                        ep.youtube_video_id = parsed.youtube_video_id
                        ep.spotify_url = parsed.spotify_url
                        ep.spotify_id = parsed.spotify_id
                        ep.publish_date = parsed.publish_date
                        ep.duration_seconds = parsed.duration_seconds
                        ep.raw_metadata = parsed.raw_metadata
                        ep.source_sha256 = parsed.source_sha256
                        ep.body_sha256 = parsed.body_sha256
                        ep.embedding_model = active_embedder.model
                        ep.chunker_version = chunker_version
                        session.flush()

                        # Remove existing chunks for this episode
                        session.query(TranscriptChunk).filter_by(episode_id=ep.id).delete()
                        session.flush()

                    # Insert new chunks with embeddings
                    for c_data, emb in zip(chunks, embeddings):
                        chunk_obj = TranscriptChunk(
                            episode_id=ep.id,
                            chunk_index=c_data.chunk_index,
                            chunk_text=c_data.chunk_text,
                            chunk_sha256=c_data.chunk_sha256,
                            token_count=c_data.token_count,
                            character_count=c_data.character_count,
                            speaker=c_data.speaker,
                            start_time_seconds=c_data.start_time_seconds,
                            embedding=emb,
                            embedding_model=active_embedder.model,
                        )
                        session.add(chunk_obj)

            success_count += 1
            episode_details.append({
                "source_path": source_rel,
                "status": "ingested",
                "chunks_count": len(chunks),
            })
            logger.info("[%d/%d] Successfully ingested %s (%d chunks)", ep_idx, total_episodes, source_rel, len(chunks))

        except Exception as exc:
            failed_count += 1
            err_msg = str(exc)
            key = source_rel or str(file_path)
            error_summary[key] = err_msg
            episode_details.append({
                "source_path": key,
                "status": "failed",
                "error": err_msg,
            })
            # Log failure without dumping raw transcript text
            logger.error("Failed to ingest episode '%s': %s", key, err_msg)

    # 6. Finalize IngestionRun record
    final_status = (
        "completed"
        if failed_count == 0
        else ("failed" if success_count == 0 and skipped_count == 0 else "completed_with_errors")
    )

    if run_id is not None:
        with db_factory() as session:
            with session.begin():
                run_rec = session.query(IngestionRun).filter_by(id=run_id).one()
                run_rec.finished_at = datetime.now(timezone.utc)
                run_rec.status = final_status
                run_rec.success_count = success_count
                run_rec.skipped_count = skipped_count
                run_rec.failed_count = failed_count
                run_rec.error_summary = error_summary

    return PipelineResult(
        run_id=run_id,
        status=final_status,
        total_episodes=total_episodes,
        success_count=success_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        error_summary=error_summary,
        episode_details=episode_details,
    )
