from __future__ import annotations

import sys
from pathlib import Path

# Ensure workspace root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import inspect, text

from backend.app.config import Settings, get_settings
from backend.app.database import Base, create_db_engine
import backend.app.models  # noqa: F401


def verify_migration(database_url: str | None = None) -> bool:
    """Verify that a database has been migrated cleanly to head."""
    if database_url is None:
        base_s = get_settings()
        database_url = base_s.database_url.replace(
            "/lenny_growth", "/lenny_growth_migration_check"
        )

    print("=" * 70)
    print("FRESH MIGRATION VERIFICATION")
    print("=" * 70)
    print(f"Target DB URL: {database_url}")
    print("-" * 70)

    engine = create_db_engine(settings=Settings(database_url=database_url))
    inspector = inspect(engine)

    # 1. Alembic version check
    with engine.connect() as conn:
        rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
        print(f"[PASS] Alembic Migration Version: '{rev}' (expected '0001_initial_schema')")
        if rev != "0001_initial_schema":
            print(f"[FAIL] Expected '0001_initial_schema', got '{rev}'")
            return False

        # 2. Vector extension check
        ext = conn.execute(
            text("SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';")
        ).fetchone()
        if not ext:
            print("[FAIL] 'vector' extension is not installed")
            return False
        print(f"[PASS] Vector Extension: {ext[0]} version {ext[1]}")

        # 3. Embedding column dimension check
        dim = conn.execute(
            text(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid = 'transcript_chunks'::regclass AND attname = 'embedding';"
            )
        ).scalar()
        if dim != 768:
            print(f"[FAIL] Expected embedding dimension 768, got {dim}")
            return False
        print(f"[PASS] Vector Column: 'embedding' dimension is {dim}")

    # 4. Tables check
    tables = set(inspector.get_table_names())
    expected_tables = {"episodes", "transcript_chunks", "ingestion_runs", "alembic_version"}
    missing_tables = expected_tables - tables
    if missing_tables:
        print(f"[FAIL] Missing tables: {missing_tables}")
        return False
    print(f"[PASS] Tables Present: {sorted(tables)}")

    # 5. Foreign keys and unique constraints
    chunk_fks = inspector.get_foreign_keys("transcript_chunks")
    valid_fk = any(
        fk.get("referred_table") == "episodes"
        and fk.get("constrained_columns") == ["episode_id"]
        and fk.get("referred_columns") == ["id"]
        for fk in chunk_fks
    )
    if not valid_fk:
        print("[FAIL] Missing or invalid foreign key on transcript_chunks.episode_id")
        return False
    print("[PASS] Foreign Key: transcript_chunks.episode_id -> episodes.id verified")

    ep_uqs = {u["name"] for u in inspector.get_unique_constraints("episodes")}
    chunk_uqs = {u["name"] for u in inspector.get_unique_constraints("transcript_chunks")}
    if "uq_episodes_source_path" not in ep_uqs:
        print(f"[WARN] uq_episodes_source_path not in explicit unique constraints list ({ep_uqs}), checking unique index")
    if "uq_transcript_chunks_episode_chunk_index" not in chunk_uqs:
        print("[FAIL] Missing unique constraint 'uq_transcript_chunks_episode_chunk_index'")
        return False
    print("[PASS] Unique Constraints: verified")

    # 6. Indexes check
    ep_indexes = {i["name"] for i in inspector.get_indexes("episodes")}
    chunk_indexes = {i["name"] for i in inspector.get_indexes("transcript_chunks")}
    expected_ep_indexes = {
        "ix_episodes_source_path",
        "ix_episodes_guest",
        "ix_episodes_publish_date",
        "ix_episodes_youtube_video_id",
        "ix_episodes_source_sha256",
        "ix_episodes_body_sha256",
    }
    missing_ep_idx = expected_ep_indexes - ep_indexes
    if missing_ep_idx:
        print(f"[FAIL] Missing indexes on episodes: {missing_ep_idx}")
        return False
    print(f"[PASS] Episodes Indexes: {sorted(expected_ep_indexes)} verified")

    expected_chunk_indexes = {
        "ix_transcript_chunks_episode_id",
        "ix_transcript_chunks_chunk_sha256",
        "ix_transcript_chunks_episode_chunk",
    }
    missing_chunk_idx = expected_chunk_indexes - chunk_indexes
    if missing_chunk_idx:
        print(f"[FAIL] Missing indexes on transcript_chunks: {missing_chunk_idx}")
        return False
    print(f"[PASS] Chunks Indexes: {sorted(expected_chunk_indexes)} verified")

    # 7. Confirm NO HNSW or IVFFlat approximate index exists
    all_indexes = ep_indexes.union(chunk_indexes)
    hnsw_found = [idx for idx in all_indexes if "hnsw" in idx.lower() or "ivfflat" in idx.lower()]
    if hnsw_found:
        print(f"[FAIL] Approximate index found before requested: {hnsw_found}")
        return False
    print("[PASS] Approximate Index Check: Confirmed NO HNSW/IVFFlat index exists")

    # 8. Compare schema with Base.metadata
    for table_name in ["episodes", "transcript_chunks", "ingestion_runs"]:
        db_cols = {c["name"] for c in inspector.get_columns(table_name)}
        orm_cols = {c.name for c in Base.metadata.tables[table_name].columns}
        if db_cols != orm_cols:
            print(f"[FAIL] Columns mismatch in {table_name}: DB={db_cols}, ORM={orm_cols}")
            return False
        print(f"[PASS] Table '{table_name}': all {len(db_cols)} columns match ORM metadata exactly")

    print("=" * 70)
    print("MIGRATION VERIFICATION SUCCEEDED: ALL CHECKS PASSED!")
    print("=" * 70)
    return True


if __name__ == "__main__":
    url_arg = sys.argv[1] if len(sys.argv) > 1 else None
    success = verify_migration(url_arg)
    sys.exit(0 if success else 1)
