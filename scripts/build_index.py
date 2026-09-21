#!/usr/bin/env python3
"""Compile the local vector index from the corpus described by corpus_manifest.yaml.

This is the ingestion pipeline BUILD_SEQUENCE.md never specified: extract ->
chunk -> embed -> index. Nothing else in the system works until this has run.

The database it produces is derived from copyrighted documents and is therefore
never committed or redistributed; each user builds their own from sources they
fetched themselves (see DATA_SOURCES.md).

    python scripts/build_index.py --db nba_legal.db
    python scripts/build_index.py --only "CBA 1995" --only "2023 NBA CBA"
"""
from __future__ import annotations

import argparse
import itertools
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.schema import initialize_database  # noqa: E402
from src.ingest.chunker import (  # noqa: E402
    Chunk,  # noqa: E402
    chunk_pages,
    dedupe,
)
from src.ingest.embedder import Embedder  # noqa: E402
from src.ingest.indexer import (  # noqa: E402
    clear_document,
    index_chunks,
    index_integrity,
    text_quality,
    upsert_document,
)
from src.ingest.timeline import entry_stats, load_timeline  # noqa: E402
from src.parser.extract import extract_document  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def index_timeline(conn, timeline_path: Path, embedder) -> tuple[int, list[str]]:
    """Index the curated timeline: one documents row per entry.

    Per-entry rows give each claim its own validity window, so the existing era
    pre-filter isolates them exactly as it isolates real documents -- no change
    to src/db/search.py, which is the point.
    """
    if not timeline_path.exists():
        return 0, []
    entries = load_timeline(timeline_path)
    names = [e.doc_name for e in entries]
    total = 0
    for e in entries:
        doc_id = upsert_document(conn, e.doc_name, "Historical",
                                 e.start_season, e.end_season, e.source_url,
                                 source_tier="timeline")
        clear_document(conn, doc_id)
        chunk = Chunk(doc_name=e.doc_name, text=e.render(), article=None,
                      section=None, page_num=1, chunk_hash=e.chunk_hash())
        total += index_chunks(conn, doc_id, [chunk], embedder)
    conn.commit()
    stats = entry_stats(entries)
    print(f"  {'curated timeline':<42} {stats['span'][0]}-{stats['span'][1]}  "
          f"{total:>5} chunks  ({stats['high_confidence']} high / "
          f"{stats['medium_confidence']} medium confidence)")
    return total, names


def prune_unlisted(conn, manifest: list[dict],
                   extra_listed: list[str] | None = None) -> list[tuple[str, int]]:
    """Delete indexed documents the manifest no longer lists.

    Renaming a document in the manifest creates a NEW row (doc_name is the unique
    key) and silently strands the old one: renaming the Uniform Player Contract
    left 35 chunks in the index under the previous name, still retrievable and no
    longer described by anything. The FK cascade and the vec trigger clean up the
    chunks and vectors once the parent row goes.
    """
    listed = {d["doc_name"] for d in manifest} | set(extra_listed or ())
    removed = []
    for row in conn.execute("SELECT id, doc_name FROM documents").fetchall():
        if row["doc_name"] in listed:
            continue
        n = conn.execute("SELECT count(*) FROM document_chunks WHERE doc_id = ?",
                         (row["id"],)).fetchone()[0]
        conn.execute("DELETE FROM documents WHERE id = ?", (row["id"],))
        removed.append((row["doc_name"], n))
    return removed


def build(db_path: str, manifest_path: Path, data_dir: Path,
          only: list[str] | None, max_pages: int | None,
          prune: bool = True, timeline_path: Path | None = None,
          with_timeline: bool = True, tiers: list[str] | None = None) -> int:
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))["documents"]
    full_manifest = manifest
    if only or tiers:
        wanted = {o.lower() for o in (only or ())}
        tier_set = set(tiers or ())
        manifest = [d for d in manifest
                    if d["doc_name"].lower() in wanted
                    or (d.get("source_tier") or "primary") in tier_set]
        if not manifest:
            print(f"no manifest entry matched only={only} tier={tiers}",
                  file=sys.stderr)
            return 1

    timeline_path = timeline_path or (ROOT / "historical_timeline.yaml")
    conn = initialize_database(db_path)
    embedder = Embedder()
    missing: list[str] = []
    total_chunks = 0
    started = time.time()

    for entry in manifest:
        pdf = data_dir / entry["file"]
        name = entry["doc_name"]
        if not pdf.exists():
            missing.append(f"{name}  ({entry['file']})")
            continue

        t0 = time.time()
        doc_id = upsert_document(
            conn, name, entry["category"],
            int(entry["start_season"]), int(entry["end_season"]), entry["source_url"],
            source_tier=entry.get("source_tier", "primary"),
        )
        removed = clear_document(conn, doc_id)  # idempotent rebuild

        pages = extract_document(pdf)
        if max_pages:
            # islice STOPS the generator; a filtering comprehension would still
            # walk every page of a 676-page PDF just to discard it.
            pages = itertools.islice(pages, max_pages)
        chunks = dedupe(chunk_pages(name, pages))
        n = index_chunks(conn, doc_id, chunks, embedder)
        conn.commit()
        total_chunks += n

        note = f"  (replaced {removed})" if removed else ""
        tier = entry.get("source_tier", "primary")
        tag = "" if tier == "primary" else f"  [{tier}]"
        print(f"  {name[:42]:<42} {entry['start_season']}-{entry['end_season']}  "
              f"{n:>5} chunks  {time.time()-t0:>6.1f}s{tag}{note}", flush=True)

    # Always refreshed unless suppressed: 21 entries cost seconds, and skipping
    # it on --only runs would let prune_unlisted mistake the timeline rows for
    # documents that had been removed from the manifest.
    timeline_names: list[str] = []
    if with_timeline:
        n_tl, timeline_names = index_timeline(conn, timeline_path, embedder)
        total_chunks += n_tl

    # Pruning uses the FULL manifest, so a --only run never mistakes the
    # documents it skipped for documents that were removed.
    if prune:
        removed = prune_unlisted(conn, full_manifest, timeline_names)
        conn.commit()
        for name, n in removed:
            print(f"  pruned {name!r} ({n} stale chunks) -- no longer in the manifest")

    print(f"\nindexed {total_chunks} chunks in {time.time()-started:.1f}s")
    if missing:
        print(f"\n{len(missing)} document(s) not found under {data_dir}/ "
              f"-- run scripts/fetch_corpus.py:")
        for m in missing:
            print(f"    - {m}")

    stats = index_integrity(conn)
    print("\nintegrity:")
    for key, value in stats.items():
        print(f"  {key:<18} {value}")

    quality = text_quality(conn)
    print("\ntext quality:")
    print(f"  fused_chunks       {quality['fused_chunks']} "
          f"({quality['fused_pct']}%)")
    for doc, n in list(quality["by_document"].items())[:5]:
        print(f"    {doc:<38} {n}")

    problems = []
    if quality["fused_pct"] > 1.0:
        problems.append(
            f"{quality['fused_pct']}% of chunks have fused words -- lower "
            f"X_TOLERANCE in src/parser/extract.py (DECISIONS.md D11)")
    if stats["verified_chunks"] != stats["vectors"]:
        problems.append("verified chunk count != vector count (index desync)")
    if stats["orphaned_vectors"]:
        problems.append(f"{stats['orphaned_vectors']} orphaned vectors")
    if not stats["vectors"]:
        problems.append("index is empty")
    if problems:
        print("\nFAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nOK: index is consistent.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="nba_legal.db")
    ap.add_argument("--manifest", type=Path, default=ROOT / "corpus_manifest.yaml")
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    ap.add_argument("--only", action="append", help="doc_name; repeatable")
    ap.add_argument("--tier", action="append",
                    choices=["primary", "judicial", "timeline"],
                    help="build every document of this source_tier; repeatable. "
                         "Exists because doc_name carries spaces and parentheses "
                         "(\"Haywood v. NBA (U.S. 1971)\"), and a caller "
                         "generating --only flags inside a shell command "
                         "substitution cannot quote them: the shell does not "
                         "re-parse quotes it produced itself, so the name word "
                         "splits into unrecognised arguments. A tier is one "
                         "token and cannot split.")
    ap.add_argument("--max-pages", type=int, help="cap pages per document (smoke tests)")
    ap.add_argument("--timeline", type=Path, default=ROOT / "historical_timeline.yaml")
    ap.add_argument("--no-timeline", action="store_true",
                    help="skip re-indexing the curated timeline")
    ap.add_argument("--no-prune", action="store_true",
                    help="keep indexed documents the manifest no longer lists")
    args = ap.parse_args()
    return build(args.db, args.manifest, args.data_dir, args.only, args.max_pages,
                 prune=not args.no_prune, timeline_path=args.timeline,
                 with_timeline=not args.no_timeline, tiers=args.tier)


if __name__ == "__main__":
    raise SystemExit(main())
