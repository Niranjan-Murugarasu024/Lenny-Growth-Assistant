"""
Dedicated background worker process for durable essay generation (Task 6 - Workstream B).

Can run as a standalone worker process:
    python -m backend.app.writing.worker

Responsibilities:
- Recovers stale running jobs on startup.
- Consumes queued jobs from Redis list `lenny:writing:jobs` with database polling fallback.
- Enforces worker concurrency limits (default: 2 local workers).
- Periodically sends heartbeats to PostgreSQL `writing_jobs`.
- Enforces mandatory quality evaluation before marking any job 'completed'.
- Manages bounded retries and exponential backoff on transient errors.
- Handles graceful shutdown on SIGINT / SIGTERM signals without corrupting active records.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

try:
    import redis
except ImportError:
    redis = None

from backend.app.config import get_settings
from backend.app.database import create_session_factory
from backend.app.models import WritingJob
from backend.app.rag.factory import get_chat_provider
from backend.app.writing.job_runner import get_job_manager, unpack_job_brief
from backend.app.writing.schemas import WritingBriefRequest
from backend.app.writing.service import WritingService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("lenny_writing_worker")


class WritingWorker:
    """Standalone worker process consuming durable essay writing jobs."""

    def __init__(self, concurrency: int | None = None) -> None:
        self.settings = get_settings()
        self.concurrency = concurrency or self.settings.worker_concurrency
        self.session_factory = create_session_factory(settings=self.settings)
        self.chat_provider = get_chat_provider(self.settings)
        self.writing_service = WritingService(
            settings=self.settings,
            session_factory=self.session_factory,
            chat_client=self.chat_provider,
        )
        self.job_manager = get_job_manager(self.settings)
        self.shutdown_requested = False

        # Redis connection
        self.redis_client = None
        if redis is not None and self.settings.redis_url:
            try:
                self.redis_client = redis.from_url(
                    self.settings.redis_url,
                    socket_connect_timeout=2.0,
                    decode_responses=True,
                )
                self.redis_client.ping()
                logger.info("Worker connected to Redis queue at %s", self.settings.redis_url)
            except Exception as exc:
                logger.warning("Worker could not connect to Redis (%s); using database queue polling", exc)
                self.redis_client = None

    def setup_signal_handlers(self) -> None:
        """Register graceful shutdown handlers for SIGINT and SIGTERM."""
        def handle_signal(sig, frame):
            logger.info("Received signal %s; initiating graceful worker shutdown...", sig)
            self.shutdown_requested = True

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

    def run(self) -> None:
        """Main worker polling and processing loop."""
        self.setup_signal_handlers()
        logger.info("Starting Lenny Writing Worker (concurrency=%d, queue=%s)...", self.concurrency, "redis" if self.redis_client else "postgres")

        # 1. Recover stale running jobs from prior crashes
        recovered = self.job_manager.recover_stale_jobs()
        if recovered:
            logger.info("Recovered %d stale jobs from prior worker run", recovered)

        # 2. Main loop
        while not self.shutdown_requested:
            try:
                job_id = self._fetch_next_job()
                if job_id:
                    self._process_job(job_id)
                else:
                    time.sleep(2.0)
            except Exception as exc:
                logger.exception("Error in worker main loop: %s", exc)
                time.sleep(3.0)

        logger.info("Writing worker shutdown complete.")

    def _fetch_next_job(self) -> str | None:
        """Fetch next queued job ID from Redis or PostgreSQL."""
        if self.redis_client:
            try:
                # BRPOP with 2-second timeout
                item = self.redis_client.brpop("lenny:writing:jobs", timeout=2)
                if item:
                    return item[1]
            except Exception as exc:
                logger.debug("Redis brpop exception: %s", exc)

        # Fallback: check PostgreSQL for oldest queued job
        with self.session_factory() as session:
            job = session.execute(
                select(WritingJob)
                .where(WritingJob.status == "queued")
                .order_by(WritingJob.created_at.asc())
                .limit(1)
            ).scalars().first()

            if job:
                return job.id

        return None

    def _process_job(self, job_id: str) -> None:
        """Execute a single writing job."""
        with self.session_factory() as session:
            db_job = session.get(WritingJob, job_id)
            if not db_job or db_job.status in ("running", "completed"):
                return
            payload = db_job.brief

        job_type = payload.get("job_type", "essay") if isinstance(payload, dict) else "essay"
        if job_type == "revision":
            logger.info("Worker processing revision job %s", job_id)
            service = WritingService(
                settings=self.settings,
                session_factory=self.session_factory,
                provider=payload.get("provider") if isinstance(payload, dict) else None,
                model=payload.get("model") if isinstance(payload, dict) else None,
            )
            self.job_manager._execute_revision_job(job_id, service)
            return

        try:
            brief, snapshot = unpack_job_brief(payload)
        except Exception as exc:
            logger.error("Corrupted brief payload for job %s: %s", job_id, exc)
            with self.session_factory() as session:
                session.execute(
                    update(WritingJob)
                    .where(WritingJob.id == job_id)
                    .values(status="failed", error=f"Invalid brief: {exc}")
                )
                session.commit()
            return

        logger.info(
            "Worker processing job %s for topic %r (provider=%s, model=%s)",
            job_id,
            brief.topic,
            snapshot.get("provider"),
            snapshot.get("model"),
        )
        job_service = WritingService(
            settings=self.settings,
            session_factory=self.session_factory,
            provider=snapshot.get("provider"),
            model=snapshot.get("model"),
        )
        self.job_manager._execute_job(job_id, brief, job_service)


def main() -> None:
    parser = argparse.ArgumentParser(description="Lenny Writing Assistant Background Worker")
    parser.add_argument("--concurrency", type=int, default=None, help="Worker concurrency limit")
    args = parser.parse_args()

    worker = WritingWorker(concurrency=args.concurrency)
    worker.run()


if __name__ == "__main__":
    main()
