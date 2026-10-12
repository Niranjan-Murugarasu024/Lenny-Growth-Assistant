from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

# Ensure workspace root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import get_settings
from backend.app.ingestion.chunker import TokenCounter, chunk_transcript
from backend.app.ingestion.parser import parse_transcript_source

DEFAULT_ARCHIVE_ROOT = PROJECT_ROOT / "data" / "raw" / "lennys-podcast-transcripts"
DEFAULT_EPISODES_DIR = DEFAULT_ARCHIVE_ROOT / "episodes"


def calculate_percentiles(values: list[int], percentiles: list[float]) -> dict[str, float]:
    """Calculate specified percentiles from a list of integer values."""
    if not values:
        return {f"p{int(p*100)}": 0.0 for p in percentiles}

    sorted_vals = sorted(values)
    n = len(sorted_vals)
    results = {}
    for p in percentiles:
        k = (n - 1) * p
        f = int(k)
        c = f + 1 if f + 1 < n else f
        d = k - f
        val = sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * d
        results[f"p{int(p*100)}"] = round(val, 1)
    return results


def run_dry_run(
    archive_root: Path,
    episodes_dir: Path,
    limit: int | None = None,
    target_tokens: int = 450,
    overlap_tokens: int = 60,
    episode_names: list[str] | None = None,
) -> dict[str, Any]:
    """
    Execute dry-run ingestion parsing and chunking without connecting to PostgreSQL or Ollama.
    """
    archive_root = Path(archive_root).resolve()
    episodes_dir = Path(episodes_dir).resolve()

    if not archive_root.is_dir():
        raise FileNotFoundError(f"Archive root not found: {archive_root}")
    if not episodes_dir.is_dir():
        raise FileNotFoundError(f"Episodes directory not found: {episodes_dir}")

    all_transcripts = sorted(episodes_dir.rglob("transcript.md"))
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

    print("=" * 70)
    print("THE LENNY GROWTH ASSISTANT — INGESTION DRY-RUN")
    print("=" * 70)
    print(f"Archive Root:   {archive_root}")
    print(f"Target Tokens:  {target_tokens}")
    print(f"Overlap Tokens: {overlap_tokens}")
    print(f"Episodes Found: {len(transcript_files)} (limit: {limit or 'none'})")
    print("-" * 70)

    tokenizer = TokenCounter()

    total_chunks = 0
    all_token_counts: list[int] = []
    over_limit_chunks = 0
    parsing_errors: list[dict[str, str]] = []
    skipped_files: list[str] = []
    episode_summaries: list[dict[str, Any]] = []

    for path in transcript_files:
        try:
            parsed = parse_transcript_source(path, archive_root)
            if parsed.parse_error and not parsed.frontmatter_found:
                parsing_errors.append({
                    "source_path": parsed.source_path,
                    "error": parsed.parse_error,
                })

            if not parsed.dialogue_body.strip():
                skipped_files.append(parsed.source_path)
                continue

            chunks = chunk_transcript(
                parsed,
                target_tokens=target_tokens,
                overlap_tokens=overlap_tokens,
                tokenizer=tokenizer,
            )

            ep_tokens = [c.token_count for c in chunks]
            ep_over = sum(1 for c in chunks if c.token_count > target_tokens)

            total_chunks += len(chunks)
            all_token_counts.extend(ep_tokens)
            over_limit_chunks += ep_over

            episode_summaries.append({
                "source_path": parsed.source_path,
                "guest": parsed.guest,
                "chunks": len(chunks),
                "min_tokens": min(ep_tokens) if ep_tokens else 0,
                "max_tokens": max(ep_tokens) if ep_tokens else 0,
                "avg_tokens": round(sum(ep_tokens) / len(ep_tokens), 1) if ep_tokens else 0.0,
                "over_limit": ep_over,
                "platform": parsed.source_platform,
            })

            print(
                f"  [OK] {parsed.source_path[:42]:<42} | "
                f"Chunks: {len(chunks):>3} | "
                f"Avg Tokens: {episode_summaries[-1]['avg_tokens']:>5.1f} | "
                f"Platform: {parsed.source_platform}"
            )

        except Exception as exc:
            parsing_errors.append({
                "source_path": str(path),
                "error": str(exc),
            })
            print(f"  [ERROR] {path}: {exc}")

    print("-" * 70)
    percentiles = calculate_percentiles(all_token_counts, [0.50, 0.90, 0.95, 0.99])

    avg_tokens = (
        round(sum(all_token_counts) / len(all_token_counts), 1)
        if all_token_counts
        else 0.0
    )

    report: dict[str, Any] = {
        "episodes_processed": len(transcript_files),
        "total_chunks": total_chunks,
        "token_statistics": {
            "min": min(all_token_counts) if all_token_counts else 0,
            "max": max(all_token_counts) if all_token_counts else 0,
            "avg": avg_tokens,
            "median_p50": percentiles.get("p50", 0.0),
            "p90": percentiles.get("p90", 0.0),
            "p95": percentiles.get("p95", 0.0),
            "p99": percentiles.get("p99", 0.0),
        },
        "over_limit_chunks": over_limit_chunks,
        "parsing_errors": parsing_errors,
        "skipped_files": skipped_files,
    }

    print("DRY-RUN SUMMARY:")
    print(f"  Episodes Processed: {report['episodes_processed']}")
    print(f"  Total Chunks:       {report['total_chunks']}")
    print(f"  Token Min / Max:    {report['token_statistics']['min']} / {report['token_statistics']['max']}")
    print(f"  Token Avg:          {report['token_statistics']['avg']}")
    print(f"  Percentiles (Tokens): p50={percentiles.get('p50')}, p90={percentiles.get('p90')}, p95={percentiles.get('p95')}, p99={percentiles.get('p99')}")
    print(f"  Over-limit Chunks:  {report['over_limit_chunks']}")
    print(f"  Parsing Errors:     {len(report['parsing_errors'])}")
    print(f"  Skipped Files:      {len(report['skipped_files'])}")
    print("=" * 70)

    return report


def main(argv: list[str] | None = None) -> None:
    settings = get_settings()

    parser = argparse.ArgumentParser(
        description="Dry-run ingestion parser and structure-aware chunker"
    )
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=DEFAULT_ARCHIVE_ROOT,
        help="Path to raw transcript archive root",
    )
    parser.add_argument(
        "--episodes-dir",
        type=Path,
        default=DEFAULT_EPISODES_DIR,
        help="Path to episodes directory",
    )
    parser.add_argument(
        "--episodes",
        nargs="*",
        default=None,
        help="Specific episode directory names to process",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of episodes to process in dry run",
    )
    parser.add_argument(
        "--target-tokens",
        type=int,
        default=settings.chunk_target_tokens,
        help="Target chunk size in tokens (default: 450)",
    )
    parser.add_argument(
        "--overlap-tokens",
        type=int,
        default=settings.chunk_overlap_tokens,
        help="Target chunk overlap in tokens (default: 60)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Execute dry-run without database or embedding calls",
    )

    args = parser.parse_args(argv)

    try:
        run_dry_run(
            archive_root=args.archive_root,
            episodes_dir=args.episodes_dir,
            limit=args.limit,
            target_tokens=args.target_tokens,
            overlap_tokens=args.overlap_tokens,
            episode_names=args.episodes,
        )
    except Exception as exc:
        print(f"Dry-run failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
