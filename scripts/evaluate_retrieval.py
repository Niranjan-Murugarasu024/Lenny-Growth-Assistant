#!/usr/bin/env python
"""
Comprehensive Retrieval Benchmark & Evaluation Script (Task 6.1 - Phase 6).

Evaluates transcript retrieval performance across 16 labeled queries spanning 7 categories:
1. Conceptual queries.
2. Named guests and exact episode titles.
3. Named frameworks and terminology.
4. Specific factual advice.
5. Multi-hop and synthesis questions.
6. Duplicate dialogue passages.
7. Out-of-domain and ambiguous queries.

Computes explicit information retrieval metrics:
- Recall@k: Fraction of queries where at least one ground-truth guest/title appears in top-k.
- MRR (Mean Reciprocal Rank): 1/rank of first relevant ground truth result.
- Mean Cosine Distance.
- Latency (ms) comparison.
- Abstention behavior for out-of-domain queries.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.retrieval.search import search_similar_chunks, search_hybrid_chunks


BENCHMARK_QUERIES: list[dict[str, Any]] = [
    # 1. Conceptual queries
    {
        "id": "q01_conceptual_pmf",
        "category": "Conceptual",
        "query": "What is product market fit and how do you know when you have it?",
        "ground_truth_guests": ["Rahul Vohra", "Marc Andreessen", "Andy Johns", "Peter Thiel"],
        "expected_themes": ["product-market fit", "retention", "growth", "engine"],
        "is_out_of_domain": False,
    },
    {
        "id": "q02_conceptual_retention",
        "category": "Conceptual",
        "query": "How do cohort retention curves indicate durable product health?",
        "ground_truth_guests": ["Casey Winters", "Brian Balfour", "Elena Verna", "Jackson Shuttleworth"],
        "expected_themes": ["retention", "cohort", "curve", "churn"],
        "is_out_of_domain": False,
    },
    # 2. Named guests and exact episode titles
    {
        "id": "q03_named_chesky",
        "category": "Named Guest & Title",
        "query": "Brian Chesky 11-star experience",
        "ground_truth_guests": ["Brian Chesky"],
        "ground_truth_titles": ["Brian Chesky’s new playbook", "Brian Chesky's new playbook"],
        "expected_themes": ["Brian Chesky", "Airbnb", "11-star", "experience"],
        "is_out_of_domain": False,
    },
    {
        "id": "q04_named_karpathy",
        "category": "Named Guest & Title",
        "query": "Andrej Karpathy Building Software 2.0 and AI agents",
        "ground_truth_guests": ["Andrej Karpathy"],
        "expected_themes": ["Andrej Karpathy", "Software 2.0", "AI"],
        "is_out_of_domain": False,
    },
    {
        "id": "q05_exact_title_duolingo",
        "category": "Named Guest & Title",
        "query": "Behind the product: Duolingo streaks Jackson Shuttleworth",
        "ground_truth_guests": ["Jackson Shuttleworth"],
        "ground_truth_titles": ["Behind the product: Duolingo streaks"],
        "expected_themes": ["Duolingo", "streaks", "retention"],
        "is_out_of_domain": False,
    },
    # 3. Named frameworks and terminology
    {
        "id": "q06_framework_lno",
        "category": "Framework & Terminology",
        "query": "Shreyas Doshi LNO framework leverage neutral overhead",
        "ground_truth_guests": ["Shreyas Doshi", "Shreyas Doshi Live"],
        "expected_themes": ["Shreyas Doshi", "LNO", "leverage", "overhead"],
        "is_out_of_domain": False,
    },
    {
        "id": "q07_framework_superhuman",
        "category": "Framework & Terminology",
        "query": "Superhuman Rahul Vohra product-market fit engine 40 percent very disappointed",
        "ground_truth_guests": ["Rahul Vohra"],
        "expected_themes": ["Rahul Vohra", "Superhuman", "40%", "disappointed"],
        "is_out_of_domain": False,
    },
    {
        "id": "q08_framework_growth_teams",
        "category": "Framework & Terminology",
        "query": "How to build a high-performing growth team Adam Fishman",
        "ground_truth_guests": ["Adam Fishman"],
        "expected_themes": ["Adam Fishman", "growth team", "acquisition", "retention"],
        "is_out_of_domain": False,
    },
    # 4. Specific factual questions
    {
        "id": "q09_factual_pricing",
        "category": "Factual Advice",
        "query": "Pricing your AI product Lessons from 400+ companies Madhavan Ramanujam",
        "ground_truth_guests": ["Madhavan Ramanujam", "Julia Schottenstein"],
        "expected_themes": ["Madhavan Ramanujam", "pricing", "monetization"],
        "is_out_of_domain": False,
    },
    {
        "id": "q10_factual_first_pm",
        "category": "Factual Advice",
        "query": "When should a startup founder hire their very first product manager?",
        "ground_truth_guests": ["Ken Norton", "Marty Cagan", "Shreyas Doshi", "Albert Cheng"],
        "expected_themes": ["first product manager", "founder", "hire"],
        "is_out_of_domain": False,
    },
    # 5. Multi-hop or synthesis questions
    {
        "id": "q11_multihop_growth_loops",
        "category": "Multi-hop Synthesis",
        "query": "How do virality loops differ from paid performance acquisition in compounding retention?",
        "ground_truth_guests": ["Brian Balfour", "Elena Verna", "Casey Winters", "Adam Fishman"],
        "expected_themes": ["viral", "paid", "loops", "compounding", "retention"],
        "is_out_of_domain": False,
    },
    {
        "id": "q12_multihop_founder_mode",
        "category": "Multi-hop Synthesis",
        "query": "Founder mode and micromanagement versus high level vision and delegation",
        "ground_truth_guests": ["Brian Chesky", "Ron Conway", "Paul Graham"],
        "expected_themes": ["founder mode", "details", "micromanagement", "leadership"],
        "is_out_of_domain": False,
    },
    # 6. Duplicate passages / dialogue nuances
    {
        "id": "q13_dialogue_10star",
        "category": "Duplicate & Dialogue",
        "query": "Designing backwards from a 10 star experience to a 5 star reality",
        "ground_truth_guests": ["Brian Chesky"],
        "expected_themes": ["10 star", "experience", "reality", "Airbnb"],
        "is_out_of_domain": False,
    },
    {
        "id": "q14_dialogue_taste",
        "category": "Duplicate & Dialogue",
        "query": "Product taste intuition and making product decisions when A/B test data is inconclusive",
        "ground_truth_guests": ["Shreyas Doshi", "Brian Chesky", "Dylan Field"],
        "expected_themes": ["taste", "intuition", "conviction", "data"],
        "is_out_of_domain": False,
    },
    # 7. Out-of-domain and ambiguous queries
    {
        "id": "q15_out_of_domain_quantum",
        "category": "Out-of-Domain",
        "query": "Quantum computing Shor algorithm for RSA cryptography prime factorization",
        "ground_truth_guests": [],
        "expected_themes": [],
        "is_out_of_domain": True,
    },
    {
        "id": "q16_ambiguous_short",
        "category": "Ambiguous Short",
        "query": "Scale fast",
        "ground_truth_guests": [],
        "expected_themes": ["scale", "growth"],
        "is_out_of_domain": True,
    },
]


def run_benchmark(mode: str = "hybrid", top_k: int = 5) -> dict[str, Any]:
    print("=" * 80)
    print(f"BENCHMARK RETRIEVAL MODE: {mode.upper()} (top_k={top_k}, total_queries={len(BENCHMARK_QUERIES)})")
    print("=" * 80)

    total_latency_ms = 0.0
    reciprocal_ranks: list[float] = []
    recall_hits = 0
    labeled_query_count = 0
    ood_distances: list[float] = []
    category_metrics: dict[str, dict[str, Any]] = {}

    for item in BENCHMARK_QUERIES:
        q_id = item["id"]
        category = item["category"]
        query = item["query"]
        ground_truth_guests = [g.lower() for g in item.get("ground_truth_guests", [])]
        ground_truth_titles = [t.lower() for t in item.get("ground_truth_titles", [])]
        expected_themes = item.get("expected_themes", [])
        is_ood = item.get("is_out_of_domain", False)

        if category not in category_metrics:
            category_metrics[category] = {"count": 0, "hits": 0, "mrr_sum": 0.0, "latency_sum": 0.0}
        category_metrics[category]["count"] += 1

        t0 = time.perf_counter()
        if mode == "hybrid":
            results = search_hybrid_chunks(query=query, top_k=top_k, diversify_duplicates=True)
        else:
            results = search_similar_chunks(query=query, top_k=top_k, diversify_duplicates=True)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        total_latency_ms += elapsed_ms
        category_metrics[category]["latency_sum"] += elapsed_ms

        top_distance = results[0].cosine_distance if results else 1.0
        avg_distance = sum(r.cosine_distance for r in results) / len(results) if results else 1.0

        if is_ood:
            ood_distances.append(top_distance)
            print(f"\n[{category}] '{query}' ({elapsed_ms:.1f}ms)")
            print(f"  Out-of-Domain check: top_distance={top_distance:.4f}, avg_distance={avg_distance:.4f} (abstention target >= 0.30)")
            continue

        labeled_query_count += 1

        # Check ground truth match in ranked results
        first_hit_rank = None
        for rank, r in enumerate(results, start=1):
            guest_match = any(gt in r.guest.lower() for gt in ground_truth_guests)
            title_match = any(gt in r.title.lower() for gt in ground_truth_titles)
            if guest_match or title_match:
                first_hit_rank = rank
                break

        if first_hit_rank is not None:
            recall_hits += 1
            rr = 1.0 / first_hit_rank
            reciprocal_ranks.append(rr)
            category_metrics[category]["hits"] += 1
            category_metrics[category]["mrr_sum"] += rr
        else:
            reciprocal_ranks.append(0.0)

        # Keyword theme match
        text_corpus = " ".join([f"{r.guest} {r.title} {r.chunk_text}" for r in results]).lower()
        matched_themes = [t for t in expected_themes if t.lower() in text_corpus]

        top_guest = results[0].guest if results else "N/A"
        top_title = results[0].title if results else "N/A"
        print(f"\n[{category}] '{query}' ({elapsed_ms:.1f}ms)")
        print(f"  Top Match (rank 1): {top_guest} — {top_title} (dist={top_distance:.4f})")
        if first_hit_rank:
            print(f"  Ground Truth Hit at Rank {first_hit_rank} (RR={1.0 / first_hit_rank:.3f})")
        else:
            print(f"  Ground Truth Hit: None in top-{top_k} (RR=0.000)")
        print(f"  Themes Matched ({len(matched_themes)}/{len(expected_themes)}): {matched_themes}")

    avg_latency = total_latency_ms / len(BENCHMARK_QUERIES)
    recall_at_k = recall_hits / labeled_query_count if labeled_query_count else 0.0
    mrr = sum(reciprocal_ranks) / labeled_query_count if labeled_query_count else 0.0
    avg_ood_distance = sum(ood_distances) / len(ood_distances) if ood_distances else 0.0

    print("\n" + "=" * 80)
    print(f"BENCHMARK SUMMARY — {mode.upper()} RETRIEVAL")
    print("=" * 80)
    print(f"Total Queries Evaluated: {len(BENCHMARK_QUERIES)} ({labeled_query_count} labeled, {len(ood_distances)} OOD/ambiguous)")
    print(f"Recall@{top_k}: {recall_at_k * 100:.1f}% ({recall_hits}/{labeled_query_count})")
    print(f"MRR (Mean Reciprocal Rank): {mrr:.4f}")
    print(f"Average Latency: {avg_latency:.1f} ms/query")
    print(f"Out-of-Domain Separation (Avg Top Distance): {avg_ood_distance:.4f}")
    print("\nCategory Breakdown:")
    for cat, m in category_metrics.items():
        if cat in ("Out-of-Domain", "Ambiguous Short"):
            continue
        c_recall = (m["hits"] / m["count"]) * 100 if m["count"] else 0
        c_mrr = m["mrr_sum"] / m["count"] if m["count"] else 0
        c_lat = m["latency_sum"] / m["count"] if m["count"] else 0
        print(f"  - {cat:28s}: Recall={c_recall:5.1f}%, MRR={c_mrr:.3f}, Latency={c_lat:.1f}ms")

    return {
        "mode": mode,
        "top_k": top_k,
        "recall_at_k": recall_at_k,
        "mrr": mrr,
        "avg_latency_ms": avg_latency,
        "avg_ood_distance": avg_ood_distance,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate retrieval pipeline")
    parser.add_argument("--mode", default="both", choices=["semantic", "hybrid", "both"])
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    if args.mode in ("semantic", "both"):
        sem_res = run_benchmark(mode="semantic", top_k=args.top_k)
    if args.mode in ("hybrid", "both"):
        hyb_res = run_benchmark(mode="hybrid", top_k=args.top_k)

    if args.mode == "both":
        print("\n" + "=" * 80)
        print("COMPARATIVE EVALUATION: SEMANTIC vs. HYBRID RRF")
        print("=" * 80)
        print(f"{'Metric':<25} | {'Semantic (pgvector)':<22} | {'Hybrid (RRF)':<20}")
        print("-" * 75)
        print(f"{f'Recall@{args.top_k}':<25} | {sem_res['recall_at_k']*100:6.1f}%{' '*15} | {hyb_res['recall_at_k']*100:6.1f}%")
        print(f"{'MRR':<25} | {sem_res['mrr']:6.4f}{' '*16} | {hyb_res['mrr']:6.4f}")
        print(f"{'Avg Latency':<25} | {sem_res['avg_latency_ms']:6.1f} ms{' '*14} | {hyb_res['avg_latency_ms']:6.1f} ms")
        print(f"{'OOD Distance':<25} | {sem_res['avg_ood_distance']:6.4f}{' '*16} | {hyb_res['avg_ood_distance']:6.4f}")
        print("=" * 80)


if __name__ == "__main__":
    main()
