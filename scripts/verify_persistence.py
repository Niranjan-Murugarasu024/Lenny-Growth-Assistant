import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select
from backend.app.database import create_db_engine, create_session_factory
from backend.app.models import Episode, TranscriptChunk, IngestionRun

engine = create_db_engine()
Session = create_session_factory(engine)

with Session() as session:
    ep_count = session.scalar(select(func.count(Episode.id)))
    chunk_count = session.scalar(select(func.count(TranscriptChunk.id)))
    null_embeddings = session.scalar(select(func.count(TranscriptChunk.id)).where(TranscriptChunk.embedding.is_(None)))
    
    # Check duplicate source paths
    dup_sources = session.execute(
        select(Episode.source_path, func.count(Episode.id))
        .group_by(Episode.source_path)
        .having(func.count(Episode.id) > 1)
    ).all()
    
    # Check duplicate (episode_id, chunk_index)
    dup_chunks = session.execute(
        select(TranscriptChunk.episode_id, TranscriptChunk.chunk_index, func.count(TranscriptChunk.id))
        .group_by(TranscriptChunk.episode_id, TranscriptChunk.chunk_index)
        .having(func.count(TranscriptChunk.id) > 1)
    ).all()
    
    # Check 6 duplicate dialogue groups
    with open('data/manifest.json', 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    dup_groups = manifest.get('duplicate_dialogue_groups', [])
    
    print(f"Total episodes: {ep_count}")
    print(f"Total chunks: {chunk_count}")
    print(f"Null embeddings: {null_embeddings}")
    print(f"Duplicate source paths: {len(dup_sources)}")
    print(f"Duplicate (episode_id, chunk_index): {len(dup_chunks)}")
    print(f"Checking {len(dup_groups)} duplicate dialogue groups:")
    for g in dup_groups:
        episodes_in_g = session.execute(
            select(Episode.id, Episode.source_path, Episode.body_sha256)
            .where(Episode.source_path.in_(g['source_paths']))
        ).all()
        print(f"  Group body_sha256={g['body_sha256'][:8]}... found {len(episodes_in_g)}/{len(g['source_paths'])} episodes:")
        for ep in episodes_in_g:
            c_count = session.scalar(select(func.count(TranscriptChunk.id)).where(TranscriptChunk.episode_id == ep.id))
            print(f"    ID={ep.id} path={ep.source_path} chunks={c_count}")

    # Check Spotify null URLs/date handling
    spotify_eps = session.execute(
        select(Episode.id, Episode.source_path, Episode.source_url, Episode.youtube_video_id, Episode.publish_date)
        .where(Episode.youtube_video_id.is_(None))
    ).all()
    print(f"\nEpisodes with null youtube_video_id: {len(spotify_eps)}")
    for ep in spotify_eps:
        print(f"  ID={ep.id} path={ep.source_path} url={ep.source_url} date={ep.publish_date}")

    # Check indexes on transcript_chunks to ensure no approximate index (HNSW / IVFFlat) was created
    from sqlalchemy import text
    indexes = session.execute(text("""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = 'transcript_chunks';
    """)).all()
    print("\nIndexes on transcript_chunks:")
    for idx_name, idx_def in indexes:
        print(f"  {idx_name}: {idx_def}")
        if "hnsw" in idx_def.lower() or "ivfflat" in idx_def.lower():
            print("  WARNING: Approximate index detected!")

    # Check runs
    runs = session.execute(select(IngestionRun.id, IngestionRun.status, IngestionRun.total_episodes, IngestionRun.success_count, IngestionRun.skipped_count, IngestionRun.failed_count).order_by(IngestionRun.id.desc()).limit(5)).all()
    print("\nRecent Ingestion Runs:")
    for r in runs:
        print(f"  Run #{r.id}: status={r.status}, total={r.total_episodes}, success={r.success_count}, skipped={r.skipped_count}, failed={r.failed_count}")
