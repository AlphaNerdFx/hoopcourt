#!/usr/bin/env python3
"""Time the hot paths this project owns, and write the result as JSON.

Deliberately measures only code written here. The embedding model is the
dominant cost of a real request and is excluded on purpose: it is a third-party
CPU-bound tensor op whose runtime on a shared CI runner varies by more than any
regression this gate is meant to catch, so including it would make the gate
measure the runner rather than the change. Nothing here imports torch or
sentence-transformers, which also keeps a benchmark run to a few seconds.

Each case is sized so one round takes roughly 50-200ms. That matters: a
percentage threshold over a 5us operation measures scheduler noise, so the
iteration counts are the thing that makes a 30% gate meaningful at all.

    python scripts/benchmark.py --out bench.json
"""
from __future__ import annotations

import argparse
import json
import platform
import random
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.api.router import (  # noqa: E402
    TemporalRouter,
    expand_aliases,
    retrieval_text,
)
from src.db.schema import (  # noqa: E402
    EMBEDDING_DIM,
    ambiguous_seasons,
    initialize_database,
)
from src.db.search import retrieve_by_documents  # noqa: E402
from src.ingest.chunker import chunk_pages  # noqa: E402
from src.model.verify import verify_citations  # noqa: E402
from src.parser.extract import ExtractedPage  # noqa: E402

# One fixed workload, so two runs compare like with like.
QUERIES = [
    "What are the shot clock rules?",
    "What was the maximum annual salary a player could receive in 2024?",
    "How did the coin flip decide the first pick in the draft?",
    "What was the reserve clause?",
    "What were the rules in the seventies?",
    "What is the Stepien Rule?",
    "When was the salary cap introduced?",
    "What happened to ABA teams in the merger?",
]
ANSWER = (
    "The Maximum Annual Salary is set out in [2023 NBA CBA, Article II, Section 7, "
    "p. 60], and the apron consequences follow in [2023 NBA CBA, Article VII, "
    "Section 2, p. 218]. An earlier formulation appears in [CBA 2017, p. 31].\n\n"
    "Sources: 2023 NBA CBA, Article II, Section 7, p. 60"
)
CONTEXT = [
    {"document": "2023 NBA CBA", "article": "II", "section": "7", "page": 60,
     "source_tier": "primary", "text": "The Maximum Annual Salary for a player..."},
    {"document": "2023 NBA CBA", "article": "VII", "section": "2", "page": 218,
     "source_tier": "primary", "text": "Second Apron Level consequences..."},
]


def _seeded_vector(rng: random.Random) -> list[float]:
    return [rng.uniform(-1.0, 1.0) for _ in range(EMBEDDING_DIM)]


def _build_synthetic_index(docs: int = 12, chunks_per_doc: int = 60) -> tuple:
    """An in-memory index with the real schema and deterministic vectors.

    Exercises the true retrieval path -- the metadata pre-filter and the outer
    ORDER BY -- without needing the corpus, which CI does not have.
    """
    from sqlite_vec import serialize_float32

    rng = random.Random(20260925)
    conn = initialize_database(":memory:")
    doc_ids = []
    for d in range(docs):
        cur = conn.execute(
            "INSERT INTO documents (doc_name, category, start_season, end_season, "
            "source_url, source_tier) VALUES (?,?,?,?,?,?)",
            (f"doc {d}", "Historical", 1990 + d, 1995 + d, "https://example.invalid",
             "primary"),
        )
        doc_id = cur.lastrowid
        doc_ids.append(doc_id)
        for c in range(chunks_per_doc):
            ch = conn.execute(
                "INSERT INTO document_chunks (doc_id, chunk_hash, article_num, "
                "section_num, page_num, is_verified, text_content) VALUES (?,?,?,?,?,?,?)",
                (doc_id, f"h{d}-{c}", "II", "7", c + 1, 1, f"chunk {c} of doc {d}"),
            )
            conn.execute(
                "INSERT INTO vec_chunks (chunk_id, doc_id, embedding) VALUES (?,?,?)",
                (ch.lastrowid, doc_id, serialize_float32(_seeded_vector(rng))),
            )
    conn.commit()
    return conn, doc_ids, _seeded_vector(rng)


def _windows_conn() -> sqlite3.Connection:
    """A document table with overlapping windows, for the boundary derivation."""
    conn = initialize_database(":memory:")
    windows = [(1995, 1998), (1999, 2004), (2005, 2010), (2011, 2016), (2017, 2022),
               (2023, 2029), (2012, 2018), (2019, 2023), (2024, 2029), (2025, 2025)]
    for i, (lo, hi) in enumerate(windows):
        conn.execute(
            "INSERT INTO documents (doc_name, category, start_season, end_season, "
            "source_url, source_tier) VALUES (?,?,?,?,?,?)",
            (f"w{i}", "Historical", lo, hi, "https://example.invalid", "primary"))
    conn.commit()
    return conn


def _synthetic_pages(n: int = 12) -> list:
    """Pages shaped like a CBA: running Article headings, numbered Sections."""
    pages = []
    for i in range(n):
        body = [f"ARTICLE {'I' * (i % 3 + 1)}"]
        for sec in range(1, 5):
            body.append(f"Section {sec}. Notwithstanding any other provision of this "
                        f"Agreement, the Maximum Annual Salary for a player with "
                        f"fewer than seven (7) Years of Service shall not exceed "
                        f"twenty-five percent (25%) of the Salary Cap in effect at "
                        f"the time such Contract is executed.")
            body.append("(a) The foregoing shall apply for each Season of the "
                        "Contract; and (b) any excess shall be disregarded.")
        pages.append(ExtractedPage(page_num=i + 1, printed_page=str(i + 1),
                                   article=None, section=None, text="\n".join(body)))
    return pages


def build_cases() -> dict:
    vec_conn, doc_ids, probe = _build_synthetic_index()
    win_conn = _windows_conn()
    pages = _synthetic_pages()

    def route_all():
        for q in QUERIES:
            TemporalRouter.resolve_query_route(q, None, {2011, 2023, 2024})

    def shape_all():
        for q in QUERIES:
            route = TemporalRouter.resolve_query_route(q, None, set())
            retrieval_text(q, route)

    def alias_all():
        for q in QUERIES:
            expand_aliases(q)

    def chunk_document():
        chunk_pages("bench", pages)

    def vector_search():
        retrieve_by_documents(vec_conn, probe, doc_ids[:6], k=5)

    def verify():
        verify_citations(ANSWER, CONTEXT)

    def boundaries():
        ambiguous_seasons(win_conn)

    # iters chosen so one round lands near 90ms; see the module docstring.
    return {
        "route_queries":     (route_all, 500),
        "shape_query":       (shape_all, 200),
        "expand_aliases":    (alias_all, 500),
        "chunk_document":    (chunk_document, 100),
        "vector_search":     (vector_search, 50),
        "verify_citations":  (verify, 500),
        "ambiguous_seasons": (boundaries, 800),
    }


def run(rounds: int, warmup: int) -> dict:
    results = {}
    for name, (fn, iters) in build_cases().items():
        for _ in range(warmup):
            fn()
        samples = []
        for _ in range(rounds):
            start = time.perf_counter_ns()
            for _ in range(iters):
                fn()
            samples.append((time.perf_counter_ns() - start) / iters)
        # The gate reads min_ns, not the mean. Benchmark noise is one-sided:
        # nothing makes a loop finish faster than the machine can run it, so the
        # fastest round is the least contaminated estimate of the real cost.
        # A mean or median on a shared runner carries whatever else the runner
        # was doing, which is exactly the variance a percentage gate cannot
        # distinguish from a regression.
        results[name] = {
            "min_ns": round(min(samples), 1),
            "median_ns": round(statistics.median(samples), 1),
            "stdev_pct": (round(100 * statistics.stdev(samples) / statistics.mean(samples), 2)
                          if len(samples) > 1 else 0.0),
            "rounds": rounds,
            "iters": iters,
        }
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, help="write JSON here")
    ap.add_argument("--rounds", type=int, default=9)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--label", default="", help="recorded in the output, e.g. base/head")
    args = ap.parse_args()

    payload = {
        "label": args.label,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "benchmarks": run(args.rounds, args.warmup),
    }
    text = json.dumps(payload, indent=1)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    width = max(len(n) for n in payload["benchmarks"])
    for name, r in payload["benchmarks"].items():
        print(f"{name:<{width}}  {r['min_ns']:>12,.1f} ns/op (min)  "
              f"median {r['median_ns']:>12,.1f}  spread +/-{r['stdev_pct']:>5.2f}%  "
              f"x{r['iters']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
