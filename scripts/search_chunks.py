from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure workspace root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import get_settings
from backend.app.retrieval.search import search_similar_chunks


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()

    parser = argparse.ArgumentParser(
        description="Search Lenny's Podcast transcript chunks using vector similarity"
    )
    parser.add_argument(
        "query",
        type=str,
        nargs="?",
        default=None,
        help="Natural language search query",
    )
    parser.add_argument(
        "--query",
        "-q",
        dest="query_opt",
        type=str,
        default=None,
        help="Search query text (alternative to positional argument)",
    )
    parser.add_argument(
        "--top-k",
        "-k",
        type=int,
        default=5,
        help="Number of closest matching chunks to retrieve (default: 5)",
    )
    parser.add_argument(
        "--diversify",
        "-d",
        dest="diversify",
        action="store_true",
        default=False,
        help="Group duplicate dialogue across identical episodes to diversify top-k results",
    )

    args = parser.parse_args(argv)
    query_text = args.query_opt or args.query

    if not query_text or not query_text.strip():
        parser.error("A search query must be provided.")

    query_text = query_text.strip()
    print("=" * 75)
    print("THE LENNY GROWTH ASSISTANT — VECTOR CHUNK RETRIEVAL")
    print("=" * 75)
    print(f"Query:           {query_text!r}")
    print(f"Embedding Model: {settings.embedding_model}")
    print(f"Vector Dim:      {settings.embedding_dimensions}")
    print(f"Top K:           {args.top_k}")
    print(f"Diversified:     {args.diversify}")
    print("-" * 75)

    try:
        results = search_similar_chunks(
            query=query_text,
            top_k=args.top_k,
            diversify_duplicates=args.diversify,
        )

        if not results:
            print("No matching transcript chunks found.")
            print("=" * 75)
            return 0

        print(f"Retrieved {len(results)} matching chunks:\n")
        for rank, res in enumerate(results, 1):
            ts_display = res.timestamp or "N/A"
            spk_display = res.speaker or "Unknown"
            print(f"[{rank}] Cosine Distance: {res.cosine_distance:.4f} | Guest: {res.guest}")
            print(f"    Episode:   {res.title}")
            print(f"    Source:    {res.source_path} (Chunk #{res.chunk_index})")
            if res.alternate_sources:
                print(f"    Also in:   {', '.join(res.alternate_sources)}")
            print(f"    Speaker:   {spk_display} | Start Time: {ts_display} ({res.start_time_seconds}s)")
            excerpt = res.chunk_text.replace("\n", " ").strip()
            if len(excerpt) > 280:
                excerpt = excerpt[:277] + "..."
            print(f"    Excerpt:   \"{excerpt}\"")
            print()

        print("=" * 75)
        return 0

    except Exception as exc:
        print(f"\nERROR: Search failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
