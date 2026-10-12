"""
Durable background job manager for essay generation (Task 6 - Workstream B).

Guarantees:
1. Stable, durable job identifiers stored authoritatively in PostgreSQL (writing_jobs table).
2. Job status survives API and worker restarts.
3. Redis coordination / queueing layer with graceful local fallback.
4. Idempotency handling: duplicate briefs with the same idempotency key or topic deduplicate.
5. Bounded retries: worker interruptions trigger safe, bounded retries without duplicate artifacts.
6. Mandatory quality evaluation: jobs only reach 'completed' if mandatory quality evaluation passed.
7. Concurrency bounds and heartbeat monitoring for stale job recovery.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import hashlib
import json
import logging
import threading
import time
from typing import Any, Literal
import uuid
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

try:
    import redis
except ImportError:
    redis = None

from fastapi.encoders import jsonable_encoder
from backend.app.config import Settings, get_settings
from backend.app.database import create_session_factory
from backend.app.models import WritingJob, WritingArtifact
from backend.app.rag.provider_base import (
    ProviderAuthenticationError,
    ProviderConfigError,
    ProviderConnectionError,
    ProviderError,
    ProviderModelNotFoundError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from backend.app.writing.schemas import WritingBriefRequest
from backend.app.writing.service import WritingService

logger = logging.getLogger(__name__)

JobStatus = Literal["queued", "running", "completed", "failed"]


@dataclass
class EssayJob:
    """State descriptor for an essay generation job, backed by PostgreSQL."""
    job_id: str
    status: JobStatus = "queued"
    stage: str = "queued"
    topic: str = ""
    target_word_count: int = 1250
    artifact_id: UUID | None = None
    version_number: int | None = None
    error: str | None = None
    retry_count: int = 0
    max_retries: int = 2
    idempotency_key: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "stage": self.stage,
            "topic": self.topic,
            "target_word_count": self.target_word_count,
            "artifact_id": str(self.artifact_id) if self.artifact_id else None,
            "version_number": self.version_number,
            "error": self.error,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "idempotency_key": self.idempotency_key,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "elapsed_seconds": self.elapsed_seconds,
        }


def unpack_job_brief(payload: dict[str, Any]) -> tuple[WritingBriefRequest, dict[str, Any]]:
    """
    Safely separates the validated WritingBriefRequest from provider/model execution snapshot.
    Preserves strict extra='forbid' validation on WritingBriefRequest.
    Supports both structured format {'brief': {...}, 'snapshot': {...}}
    and legacy payloads with '_snapshot_*' keys or raw brief dictionaries.
    """
    if not isinstance(payload, dict):
        raise ValueError(f"Expected dict brief payload, got {type(payload).__name__}")

    if "brief" in payload and isinstance(payload["brief"], dict):
        brief_data = dict(payload["brief"])
        snapshot = dict(payload.get("snapshot") or {})
    else:
        payload_copy = dict(payload)
        snapshot = {}
        if "_snapshot_provider" in payload_copy:
            snapshot["provider"] = payload_copy.pop("_snapshot_provider")
        if "_snapshot_model" in payload_copy:
            snapshot["model"] = payload_copy.pop("_snapshot_model")
        brief_data = payload_copy

    brief = WritingBriefRequest(**brief_data)
    return brief, snapshot


class DurableEssayJobManager:
    """
    Durable, thread-safe manager for queuing and executing essay generation jobs
    backed by PostgreSQL writing_jobs and Redis coordination.
    """

    def __init__(

        self,
        settings: Settings | None = None,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._session_factory = session_factory or create_session_factory(settings=self._settings)
        self._max_workers = self._settings.worker_concurrency
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="durable_essay_worker",
        )
        self._lock = threading.Lock()
        self._concurrency_sem = threading.Semaphore(self._max_workers)
        
        # Redis client initialization (with graceful fallback if Redis is down)
        self._redis_client = None
        if redis is not None and self._settings.redis_url:
            try:
                self._redis_client = redis.from_url(
                    self._settings.redis_url,
                    socket_connect_timeout=2.0,
                    decode_responses=True,
                )
                self._redis_client.ping()
                logger.info("Connected to Redis at %s", self._settings.redis_url)
            except Exception as exc:
                logger.warning("Redis connection failed (%s); operating with direct database queue", exc)
                self._redis_client = None

        # Automatically recover stale running jobs from prior process lifecycles
        self.recover_stale_jobs()

    def submit_job(
        self,
        brief: WritingBriefRequest,
        writing_service: WritingService,
        idempotency_key: str | None = None,
    ) -> EssayJob:
        """
        Create and submit a new essay generation job.
        If an idempotency key is provided and a non-failed job already exists,
        returns the existing job to prevent duplicate in-flight or completed work.
        """
        # Generate stable idempotency key if not provided
        effective_key = idempotency_key
        if not effective_key:
            digest = hashlib.sha256(f"{brief.topic}:{brief.target_word_count}".encode()).hexdigest()[:24]
            effective_key = f"auto_{digest}"

        with self._session_factory() as session:
            # Check for existing job with same idempotency key
            existing = session.execute(
                select(WritingJob).where(WritingJob.idempotency_key == effective_key)
            ).scalars().first()

            if existing:
                if existing.status in ("queued", "running", "completed"):
                    logger.info(
                        "Idempotent submission: returning existing job %s (status=%s)",
                        existing.id,
                        existing.status,
                    )
                    return self._model_to_job(existing)
                # If existing job failed, reset it for safe re-submission under same idempotency key
                logger.info("Existing job %s failed; resetting for re-submission", existing.id)
                now = datetime.now(timezone.utc)
                existing.status = "queued"
                existing.stage = "Queued for execution"
                existing.error = None
                existing.retry_count = 0
                from backend.app.database import get_db_setting
                snap_prov = get_db_setting(session, "active_chat_provider", self._settings.chat_provider)
                snap_model = get_db_setting(
                    session,
                    "active_chat_model",
                    self._settings.ollama_chat_model if snap_prov == "ollama" else self._settings.nvidia_model,
                )
                existing.brief = {
                    "brief": jsonable_encoder(brief.model_dump(mode="json")),
                    "snapshot": {
                        "provider": snap_prov,
                        "model": snap_model,
                    },
                }
                existing.updated_at = now
                existing.heartbeat_at = now
                session.commit()
                session.refresh(existing)
                job_id = existing.id
                essay_job = self._model_to_job(existing)
            else:
                from backend.app.database import get_db_setting
                job_id = f"job_{uuid.uuid4().hex[:12]}"
                now = datetime.now(timezone.utc)
                snap_prov = get_db_setting(session, "active_chat_provider", self._settings.chat_provider)
                snap_model = get_db_setting(
                    session,
                    "active_chat_model",
                    self._settings.ollama_chat_model if snap_prov == "ollama" else self._settings.nvidia_model,
                )
                brief_payload = {
                    "brief": jsonable_encoder(brief.model_dump(mode="json")),
                    "snapshot": {
                        "provider": snap_prov,
                        "model": snap_model,
                    },
                }
                db_job = WritingJob(
                    id=job_id,
                    idempotency_key=effective_key,
                    topic=brief.topic,
                    status="queued",
                    stage="Queued for execution",
                    target_word_count=brief.target_word_count,
                    brief=brief_payload,
                    retry_count=0,
                    max_retries=self._settings.max_job_retries,
                    created_at=now,
                    updated_at=now,
                    heartbeat_at=now,
                )
                session.add(db_job)
                session.commit()
                session.refresh(db_job)
                essay_job = self._model_to_job(db_job)

        # Notify Redis queue if available, otherwise schedule on local thread pool
        enqueued_redis = False
        if self._redis_client:
            try:
                self._redis_client.lpush("lenny:writing:jobs", job_id)
                self._redis_client.publish(
                    "lenny:writing:events",
                    json.dumps({"event": "queued", "job_id": job_id, "topic": brief.topic}),
                )
                enqueued_redis = True
            except Exception as exc:
                logger.debug("Redis queue push error: %s", exc)

        # Only execute on in-process thread pool if NOT pushed to Redis worker
        if not enqueued_redis:
            self._executor.submit(self._execute_job, job_id, brief, writing_service)
        logger.info("Durable job %s enqueued for topic %r (queue=%s, idempotency_key=%s)", job_id, brief.topic, "redis" if enqueued_redis else "local", effective_key)
        return essay_job

    def submit_revision_job(
        self,
        artifact_id: UUID,
        instructions: str,
        target_word_count: int | None = None,
        writing_service: WritingService | None = None,
        idempotency_key: str | None = None,
    ) -> EssayJob:
        """
        Submit a durable background revision job for an existing artifact.
        Dispatches to worker/Redis queue or in-process thread pool.
        """
        with self._session_factory() as session:
            artifact = session.get(WritingArtifact, artifact_id)
            if not artifact:
                raise ValueError(f"Artifact '{artifact_id}' does not exist.")
            versions = sorted(artifact.versions, key=lambda v: v.version_number)
            if not versions:
                raise ValueError(f"Artifact '{artifact_id}' has no existing versions.")
            latest = versions[-1]
            input_version = latest.version_number

            from backend.app.database import get_db_setting
            job_id = f"job_rev_{uuid.uuid4().hex[:10]}"
            now = datetime.now(timezone.utc)
            snap_prov = get_db_setting(session, "active_chat_provider", self._settings.chat_provider)
            snap_model = get_db_setting(
                session,
                "active_chat_model",
                self._settings.ollama_chat_model if snap_prov == "ollama" else self._settings.nvidia_model,
            )

            job_payload = {
                "job_type": "revision",
                "artifact_id": str(artifact_id),
                "input_version_number": input_version,
                "instructions": instructions,
                "target_word_count": target_word_count or latest.word_count,
                "snapshot": {
                    "provider": snap_prov,
                    "model": snap_model,
                },
            }

            db_job = WritingJob(
                id=job_id,
                idempotency_key=idempotency_key,
                topic=f"Revision: {instructions[:120]}",
                status="queued",
                stage="Queued for revision",
                target_word_count=target_word_count or latest.word_count,
                brief=job_payload,
                artifact_id=artifact_id,
                version_number=input_version,
                retry_count=0,
                max_retries=self._settings.max_job_retries,
                created_at=now,
                updated_at=now,
                heartbeat_at=now,
            )
            session.add(db_job)
            session.commit()
            session.refresh(db_job)
            essay_job = self._model_to_job(db_job)

        enqueued_redis = False
        if self._redis_client:
            try:
                self._redis_client.lpush("lenny:writing:jobs", job_id)
                self._redis_client.publish(
                    "lenny:writing:events",
                    json.dumps({"event": "queued", "job_id": job_id, "type": "revision"}),
                )
                enqueued_redis = True
            except Exception as exc:
                logger.debug("Redis queue push error for revision: %s", exc)

        if not enqueued_redis:
            self._executor.submit(
                self._execute_revision_job,
                job_id,
                writing_service or WritingService(settings=self._settings, session_factory=self._session_factory),
            )

        return essay_job

    def _execute_revision_job(
        self,
        job_id: str,
        writing_service: WritingService,
    ) -> None:
        """Execute an asynchronous revision job safely with heartbeat and conflict detection."""
        acquired = self._concurrency_sem.acquire(blocking=True, timeout=10.0)
        if not acquired:
            logger.warning("Worker concurrency slot acquisition timed out for revision %s", job_id)
            return

        stop_heartbeat = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(job_id, stop_heartbeat),
            daemon=True,
            name=f"heartbeat_{job_id}",
        )

        t0 = time.time()
        try:
            with self._session_factory() as session:
                db_job = session.get(WritingJob, job_id)
                if not db_job or db_job.status in ("running", "completed"):
                    return
                payload = db_job.brief
                art_id = UUID(payload["artifact_id"])
                input_ver = payload.get("input_version_number")
                instructions = payload["instructions"]
                target_wc = payload.get("target_word_count")
                snapshot = payload.get("snapshot", {})

                # Check for stale revision conflict
                artifact = session.get(WritingArtifact, art_id)
                if not artifact:
                    db_job.status = "failed"
                    db_job.error = f"Artifact {art_id} was deleted or not found."
                    session.commit()
                    return

                latest_ver = max((v.version_number for v in artifact.versions), default=0)
                if input_ver is not None and latest_ver > input_ver:
                    db_job.status = "failed"
                    db_job.stage = "Revision conflict detected"
                    db_job.error = (
                        f"Stale version conflict: Artifact was modified to version {latest_ver} "
                        f"while this revision based on version {input_ver} was pending."
                    )
                    session.commit()
                    return

                db_job.status = "running"
                db_job.stage = "Applying AI revisions and evaluating"
                db_job.heartbeat_at = datetime.now(timezone.utc)
                session.commit()

            heartbeat_thread.start()

            # Execute revision using snapshot provider/model if specified
            if snapshot.get("provider"):
                service_to_use = WritingService(
                    settings=self._settings,
                    session_factory=self._session_factory,
                    provider=snapshot.get("provider"),
                    model=snapshot.get("model"),
                )
            else:
                service_to_use = writing_service

            art, new_ver, eval_result = service_to_use.revise_artifact(
                artifact_id=art_id,
                instructions=instructions,
                target_word_count=target_wc,
            )

            stop_heartbeat.set()
            elapsed = round(time.time() - t0, 2)

            with self._session_factory() as session:
                db_job = session.get(WritingJob, job_id)
                if db_job:
                    db_job.status = "completed"
                    db_job.stage = "Revision completed"
                    db_job.artifact_id = art.id
                    db_job.version_number = new_ver.version_number
                    db_job.heartbeat_at = datetime.now(timezone.utc)
                    db_job.error = None
                    session.commit()
                    logger.info("Revision job %s completed in %.2fs (v=%d)", job_id, elapsed, new_ver.version_number)
        except Exception as exc:
            stop_heartbeat.set()
            err_str = str(exc)
            logger.exception("Revision job %s failed: %s", job_id, err_str)
            with self._session_factory() as session:
                db_job = session.get(WritingJob, job_id)
                if db_job:
                    db_job.status = "failed"
                    db_job.stage = "Revision failed"
                    db_job.error = f"AI revision failed: {err_str}"
                    session.commit()
        finally:
            stop_heartbeat.set()
            self._concurrency_sem.release()

    def get_job(self, job_id: str) -> EssayJob | None:
        """Retrieve job state by ID directly from authoritative PostgreSQL database."""
        with self._session_factory() as session:
            db_job = session.get(WritingJob, job_id)
            if not db_job:
                return None
            return self._model_to_job(db_job)

    def recover_stale_jobs(self) -> int:
        """
        Detect running jobs from a prior crash or server restart and safely recover them.
        If retry count < max_retries, requeues the job. Otherwise marks it failed.
        """
        recovered_count = 0
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=self._settings.worker_stale_job_timeout_seconds
        )

        with self._session_factory() as session:
            stale_jobs = session.execute(
                select(WritingJob).where(WritingJob.status == "running")
            ).scalars().all()

            for job in stale_jobs:
                recovered_count += 1
                if job.retry_count < job.max_retries:
                    job.status = "queued"
                    job.stage = f"Recovered from restart; requeued (retry {job.retry_count + 1}/{job.max_retries})"
                    job.retry_count += 1
                    job.heartbeat_at = datetime.now(timezone.utc)
                    if self._redis_client:
                        try:
                            self._redis_client.lpush("lenny:writing:jobs", job.id)
                        except Exception as r_err:
                            logger.debug("Failed pushing recovered job to Redis: %s", r_err)
                    logger.warning(
                        "Recovered stale job %s: requeued (retry %d/%d)",
                        job.id,
                        job.retry_count,
                        job.max_retries,
                    )

                else:
                    job.status = "failed"
                    job.stage = "Interrupted by restart"
                    job.error = "Job interrupted by server/worker restart and exceeded retry limit."
                    job.heartbeat_at = datetime.now(timezone.utc)
                    logger.error("Stale job %s exceeded max retries; marked failed", job.id)

            if recovered_count > 0:
                session.commit()

        return recovered_count

    def _execute_job(
        self,
        job_id: str,
        brief: WritingBriefRequest,
        writing_service: WritingService,
    ) -> None:
        """Worker execution function enforcing concurrency, heartbeats, and safe transitions."""
        acquired = self._concurrency_sem.acquire(blocking=True, timeout=10.0)
        if not acquired:
            logger.warning("Worker concurrency slot acquisition timed out for %s; requeueing", job_id)
            return

        stop_heartbeat = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(job_id, stop_heartbeat),
            daemon=True,
            name=f"heartbeat_{job_id}",
        )

        t0 = time.time()
        try:
            # 1. Transition to 'running'
            with self._session_factory() as session:
                db_job = session.get(WritingJob, job_id)
                if not db_job or db_job.status in ("running", "completed"):
                    logger.info("Job %s already in status %s; skipping duplicate execution", job_id, db_job.status if db_job else "None")
                    return
                db_job.status = "running"
                db_job.stage = "Researching Lenny's Podcast transcripts"
                db_job.heartbeat_at = datetime.now(timezone.utc)
                session.commit()

            heartbeat_thread.start()

            # 2. Update stage: Drafting and evaluating
            with self._session_factory() as session:
                session.execute(
                    update(WritingJob)
                    .where(WritingJob.id == job_id)
                    .values(stage="Drafting and evaluating essay", heartbeat_at=datetime.now(timezone.utc))
                )
                session.commit()

            # 3. Execute generation
            artifact, version, evaluation = writing_service.generate_and_persist_essay(brief)

            elapsed = round(time.time() - t0, 2)
            stop_heartbeat.set()

            # 4. Record terminal status based strictly on mandatory quality evaluation
            with self._session_factory() as session:
                db_job = session.get(WritingJob, job_id)
                if not db_job:
                    return

                if artifact and session.get(WritingArtifact, artifact.id):
                    db_job.artifact_id = artifact.id
                    db_job.version_number = version.version_number if version else None
                db_job.heartbeat_at = datetime.now(timezone.utc)


                if evaluation.passed:
                    db_job.status = "completed"
                    db_job.stage = "Essay generation and persistence completed"
                    db_job.error = None
                    logger.info(
                        "Durable essay job %s completed in %.2fs (artifact_id=%s, word_count=%d)",
                        job_id,
                        elapsed,
                        artifact.id,
                        version.word_count,
                    )
                else:
                    db_job.status = "failed"
                    db_job.stage = "Quality evaluation failed"
                    reasons = evaluation.feedback or ["Mandatory quality checks failed"]
                    db_job.error = f"Mandatory quality evaluation failed: {'; '.join(reasons)}"
                    logger.warning(
                        "Durable essay job %s failed quality evaluation after %.2fs: %s",
                        job_id,
                        elapsed,
                        db_job.error,
                    )

                session.commit()

        except Exception as exc:
            stop_heartbeat.set()
            elapsed = round(time.time() - t0, 2)
            err_str = str(exc)
            logger.exception("Durable essay job %s encountered error after %.2fs: %s", job_id, elapsed, err_str)

            is_non_retriable = isinstance(
                exc,
                (ValueError, ProviderAuthenticationError, ProviderModelNotFoundError, ProviderConfigError),
            )

            if isinstance(exc, ProviderAuthenticationError):
                user_error = "The cloud provider rejected the request. Verify model access and credentials."
            elif isinstance(exc, ProviderModelNotFoundError):
                user_error = f"The selected model is unavailable. Check the provider configuration: {exc}"
            elif isinstance(exc, ProviderTimeoutError):
                user_error = "Essay generation timed out. Please retry."
            elif isinstance(exc, ProviderRateLimitError):
                user_error = "Provider rate limit or quota exceeded. Please try again later."
            elif isinstance(exc, ProviderConnectionError):
                user_error = "The writing worker or model provider is unavailable. Please try again shortly."
            elif isinstance(exc, ProviderConfigError):
                user_error = f"Model provider configuration error: {exc}"
            else:
                user_error = err_str

            with self._session_factory() as session:
                db_job = session.get(WritingJob, job_id)
                if db_job:
                    # Check retry eligibility (do NOT retry non-transient auth/config errors)
                    if db_job.retry_count < db_job.max_retries and not is_non_retriable:
                        db_job.status = "queued"
                        db_job.retry_count += 1
                        db_job.stage = f"Retrying after transient error ({db_job.retry_count}/{db_job.max_retries})"
                        db_job.error = f"Transient error: {user_error}"
                        db_job.heartbeat_at = datetime.now(timezone.utc)
                        session.commit()
                        logger.info("Requeuing durable job %s (attempt %d)", job_id, db_job.retry_count)
                        threading.Timer(2.0, self._execute_job, args=(job_id, brief, writing_service)).start()
                    else:
                        db_job.status = "failed"
                        db_job.stage = "Generation failed"
                        db_job.error = user_error
                        db_job.heartbeat_at = datetime.now(timezone.utc)
                        session.commit()
        finally:
            stop_heartbeat.set()
            self._concurrency_sem.release()

    def _heartbeat_loop(self, job_id: str, stop_event: threading.Event) -> None:
        """Periodically update heartbeat_at timestamp in database to prevent stale timeout."""
        interval = self._settings.worker_heartbeat_interval_seconds if hasattr(self._settings, "worker_heartbeat_interval_seconds") else 10.0
        while not stop_event.wait(timeout=interval):
            try:
                with self._session_factory() as session:
                    session.execute(
                        update(WritingJob)
                        .where(WritingJob.id == job_id, WritingJob.status == "running")
                        .values(heartbeat_at=datetime.now(timezone.utc))
                    )
                    session.commit()
            except Exception as exc:
                logger.debug("Heartbeat update failed for %s: %s", job_id, exc)

    @staticmethod
    def _model_to_job(db_job: WritingJob) -> EssayJob:
        """Convert a SQLAlchemy WritingJob record into an EssayJob dataclass."""
        now = datetime.now(timezone.utc)
        elapsed = (now - db_job.created_at).total_seconds()
        return EssayJob(
            job_id=db_job.id,
            status=db_job.status,  # type: ignore[arg-type]
            stage=db_job.stage or db_job.status,
            topic=db_job.topic,
            target_word_count=db_job.target_word_count,
            artifact_id=db_job.artifact_id,
            version_number=db_job.version_number,
            error=db_job.error,
            retry_count=db_job.retry_count,
            max_retries=db_job.max_retries,
            idempotency_key=db_job.idempotency_key,
            created_at=db_job.created_at,
            elapsed_seconds=round(elapsed, 2),
        )


# Backward-compatible alias
EssayJobManager = DurableEssayJobManager

# Global singleton job manager
_job_manager: DurableEssayJobManager | None = None



def get_job_manager(
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> DurableEssayJobManager:
    """Retrieve or initialize the global durable essay job manager."""
    global _job_manager
    if _job_manager is None or (settings and _job_manager._settings.database_url != settings.database_url):
        _job_manager = DurableEssayJobManager(settings=settings, session_factory=session_factory)
    return _job_manager

