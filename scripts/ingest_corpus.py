from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure workspace root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import get_settings
from backend.app.database import create_session_factory
from backend.app.ingestion.pipeline import run_ingestion_pipeline
from backend.app.models import Episode, IngestionRun, TranscriptChunk

DEFAULT_ARCHIVE_ROOT = PROJECT_ROOT / "data" / "raw" / "lennys-podcast-transcripts"
DEFAULT_EPISODES_DIR = DEFAULT_ARCHIVE_ROOT / "episodes"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ingest_corpus")


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()

    parser = argparse.ArgumentParser(
        description="Ingest Lenny's Podcast transcripts into PostgreSQL with vector embeddings"
    )
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=DEFAULT_ARCHIVE_ROOT,
        help="Path to raw transcript archive root (default: data/raw/lennys-podcast-transcripts)",
    )
    parser.add_argument(
        "--episodes-dir",
        type=Path,
        default=DEFAULT_EPISODES_DIR,
        help="Path to episodes directory (default: data/raw/lennys-podcast-transcripts/episodes)",
    )
    parser.add_argument(
        "--episodes",
        nargs="*",
        default=None,
        help="Specific episode directory names to ingest (e.g., ada-chen-rekhi nickey-skarstad)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of episodes to process",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Run parsing and chunking without connecting to DB or Ollama",
    )
    parser.add_argument(
        "--target-tokens",
        type=int,
        default=settings.chunk_target_tokens,
        help=f"Target chunk size in tokens (default: {settings.chunk_target_tokens})",
    )
    parser.add_argument(
        "--overlap-tokens",
        type=int,
        default=settings.chunk_overlap_tokens,
        help=f"Chunk overlap in tokens (default: {settings.chunk_overlap_tokens})",
    )

    args = parser.parse_args(argv)

    print("=" * 70)
    print("THE LENNY GROWTH ASSISTANT — TRANSCRIPT INGESTION PIPELINE")
    print("=" * 70)
    print(f"Archive Root:     {args.archive_root}")
    print(f"Target Tokens:    {args.target_tokens}")
    print(f"Overlap Tokens:   {args.overlap_tokens}")
    print(f"Mode:             {'DRY-RUN' if args.dry_run else 'LIVE DATABASE INGESTION'}")
    if args.episodes:
        print(f"Episodes Filter:  {', '.join(args.episodes)}")
    if args.limit:
        print(f"Limit:            {args.limit}")
    print("-" * 70)

    try:
        result = run_ingestion_pipeline(
            archive_root=args.archive_root,
            episodes_dir=args.episodes_dir,
            limit=args.limit,
            episode_names=args.episodes,
            target_tokens=args.target_tokens,
            overlap_tokens=args.overlap_tokens,
            dry_run=args.dry_run,
        )

        print("-" * 70)
        print("PIPELINE EXECUTION SUMMARY:")
        print(f"  Ingestion Run ID:   {result.run_id or 'N/A (dry-run)'}")
        print(f"  Final Status:       {result.status}")
        print(f"  Total Episodes:     {result.total_episodes}")
        print(f"  Successfully Done:  {result.success_count}")
        print(f"  Skipped (Idempotent): {result.skipped_count}")
        print(f"  Failed:             {result.failed_count}")

        if result.error_summary:
            print("\n  Failures:")
            for ep_key, err in result.error_summary.items():
                print(f"    - {ep_key}: {err}")

        # If live ingestion succeeded, print DB verification metrics
        if not args.dry_run and result.run_id is not None:
            session_factory = create_session_factory()
            with session_factory() as session:
                total_db_episodes = session.query(Episode).count()
                total_db_chunks = session.query(TranscriptChunk).count()
                chunks_with_vectors = (
                    session.query(TranscriptChunk)
                    .filter(TranscriptChunk.embedding.isnot(None))
                    .count()
                )
                run_rec = session.query(IngestionRun).filter_by(id=result.run_id).first()

            print("\nDATABASE STATUS AFTER INGESTION:")
            print(f"  Total Episodes in DB:     {total_db_episodes}")
            print(f"  Total Chunks in DB:       {total_db_chunks}")
            print(f"  Chunks with Valid Vector: {chunks_with_vectors} / {total_db_chunks}")
            if run_rec:
                print(f"  Ingestion Run Status:     {run_rec.status}")

        print("=" * 70)
        return 0 if result.failed_count == 0 else 1

    except Exception as exc:
        logger.exception("Pipeline execution failed: %s", exc)
        print(f"\nFATAL: Pipeline execution failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
