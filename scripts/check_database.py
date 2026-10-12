from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Ensure workspace root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pgvector.sqlalchemy  # noqa: F401
from sqlalchemy import inspect, text
from backend.app.config import get_settings
from backend.app.database import create_db_engine


def check_database() -> bool:
    """Run diagnostic verification of database, extension, and migrated schema."""
    settings = get_settings()

    print("=" * 65)
    print("THE LENNY GROWTH ASSISTANT — DATABASE HEALTH CHECK")
    print("=" * 65)
    print(f"Target URL: {settings.sanitized_database_url()}")
    print(f"Expected Model: {settings.embedding_model}")
    print(f"Expected Vector Dimensions: {settings.embedding_dimensions}")
    print("-" * 65)

    all_passed = True

    try:
        engine = create_db_engine(settings=settings)
        with engine.connect() as conn:
            # 1. Connectivity and Identity
            identity = conn.execute(
                text(
                    "SELECT current_database(), current_user, version(), "
                    "current_setting('server_version');"
                )
            ).fetchone()

            if identity:
                current_db, current_user, full_version, server_version = identity
                print("[PASS] Database Connection: Established successfully")
                print(f"       Current Database: {current_db}")
                print(f"       Current User:     {current_user}")
                print(f"       Server Version:   PostgreSQL {server_version}")

                if current_db != "lenny_growth":
                    print(f"[WARN] Expected DB 'lenny_growth', found {current_db!r}")
                if current_user != "lenny_app":
                    print(f"[WARN] Expected User 'lenny_app', found {current_user!r}")
            else:
                print("[FAIL] Database Identity: Unable to fetch connection identity")
                all_passed = False

            # 2. Vector Extension Verification
            ext_row = conn.execute(
                text(
                    "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
                )
            ).fetchone()

            if ext_row:
                ext_name, ext_version = ext_row
                print(f"[PASS] Vector Extension: '{ext_name}' v{ext_version} is installed")
            else:
                print("[FAIL] Vector Extension: 'vector' is NOT installed in database")
                all_passed = False

            # 3. Alembic Version
            elembic_row = conn.execute(
                text("SELECT version_num FROM alembic_version;")
            ).fetchone()
            if elembic_row:
                print(f"[PASS] Migration Version: Current revision is {elembic_row[0]!r}")
            else:
                print("[WARN] Migration Version: alembic_version table is empty")

            # 4. Schema Inspection
            inspector = inspect(engine)
            existing_tables = set(inspector.get_table_names())
            expected_tables = {"episodes", "transcript_chunks", "ingestion_runs"}

            missing_tables = expected_tables - existing_tables
            if not missing_tables:
                print("[PASS] Tables: All expected tables present "
                      f"({', '.join(sorted(expected_tables))})")
            else:
                print(f"[FAIL] Tables: Missing tables {missing_tables}")
                all_passed = False

            # Inspect episodes table
            if "episodes" in existing_tables:
                ep_cols = {col["name"]: col for col in inspector.get_columns("episodes")}
                req_ep_cols = {
                    "id", "source_path", "guest", "title", "source_platform",
                    "source_url", "youtube_video_id", "spotify_url", "spotify_id",
                    "publish_date", "duration_seconds", "raw_metadata",
                    "source_sha256", "body_sha256", "embedding_model",
                    "chunker_version", "created_at", "updated_at"
                }
                missing_ep_cols = req_ep_cols - set(ep_cols.keys())
                if not missing_ep_cols:
                    print(f"[PASS] 'episodes' schema: All {len(req_ep_cols)} columns present")
                else:
                    print(f"[FAIL] 'episodes' schema: Missing columns {missing_ep_cols}")
                    all_passed = False

                # Ensure youtube_video_id is not unique
                uniques = inspector.get_unique_constraints("episodes")
                unique_col_sets = [set(u.get("column_names", [])) for u in uniques]
                if {"youtube_video_id"} in unique_col_sets:
                    print("[FAIL] 'episodes' schema: youtube_video_id has unique constraint!")
                    all_passed = False
                else:
                    print("[PASS] 'episodes' constraints: youtube_video_id is non-unique as required")

            # Inspect transcript_chunks table
            if "transcript_chunks" in existing_tables:
                chunk_cols = {col["name"]: col for col in inspector.get_columns("transcript_chunks")}
                req_chunk_cols = {
                    "id", "episode_id", "chunk_index", "chunk_text", "chunk_sha256",
                    "token_count", "character_count", "speaker", "start_time_seconds",
                    "embedding", "embedding_model", "created_at"
                }
                missing_chunk_cols = req_chunk_cols - set(chunk_cols.keys())
                if not missing_chunk_cols:
                    print(f"[PASS] 'transcript_chunks' schema: All {len(req_chunk_cols)} columns present")
                else:
                    print(f"[FAIL] 'transcript_chunks' schema: Missing columns {missing_chunk_cols}")
                    all_passed = False

                # Check vector dimension
                dim_row = conn.execute(
                    text(
                        "SELECT atttypmod FROM pg_attribute "
                        "WHERE attrelid = 'transcript_chunks'::regclass "
                        "AND attname = 'embedding';"
                    )
                ).fetchone()
                if dim_row and dim_row[0] == 768:
                    print("[PASS] Vector Column: embedding is VECTOR(768)")
                else:
                    dim_val = dim_row[0] if dim_row else "not found"
                    print(f"[WARN] Vector Column: dimension attribute is {dim_val}")

                # Check foreign key and unique constraint
                fks = inspector.get_foreign_keys("transcript_chunks")
                ep_fk = any(
                    fk.get("referred_table") == "episodes"
                    and "episode_id" in fk.get("constrained_columns", [])
                    for fk in fks
                )
                if ep_fk:
                    print("[PASS] 'transcript_chunks' FK: episode_id -> episodes.id verified")
                else:
                    print("[FAIL] 'transcript_chunks' FK: Missing foreign key to episodes.id")
                    all_passed = False

                chunk_uniques = inspector.get_unique_constraints("transcript_chunks")
                has_ep_chunk_unique = any(
                    set(u.get("column_names", [])) == {"episode_id", "chunk_index"}
                    for u in chunk_uniques
                )
                if has_ep_chunk_unique:
                    print("[PASS] 'transcript_chunks' Unique Constraint: (episode_id, chunk_index) verified")
                else:
                    print("[FAIL] 'transcript_chunks' Unique Constraint: Missing unique on (episode_id, chunk_index)")
                    all_passed = False

            # Inspect ingestion_runs table
            if "ingestion_runs" in existing_tables:
                run_cols = {col["name"]: col for col in inspector.get_columns("ingestion_runs")}
                req_run_cols = {
                    "id", "started_at", "finished_at", "status", "total_episodes",
                    "success_count", "skipped_count", "failed_count", "error_summary"
                }
                missing_run_cols = req_run_cols - set(run_cols.keys())
                if not missing_run_cols:
                    print(f"[PASS] 'ingestion_runs' schema: All {len(req_run_cols)} columns present")
                else:
                    print(f"[FAIL] 'ingestion_runs' schema: Missing columns {missing_run_cols}")
                    all_passed = False

    except Exception as exc:
        print(f"[FAIL] Error during database health check: {exc}")
        all_passed = False

    print("-" * 65)
    if all_passed:
        print("RESULT: ALL DATABASE CHECKS PASSED SUCCESSFULLY.")
        print("=" * 65)
        return True
    else:
        print("RESULT: ONE OR MORE CHECKS FAILED.")
        print("=" * 65)
        return False


def main() -> None:
    success = check_database()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
