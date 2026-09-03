"""Relational + vector schema for the Hoopcourt index.

Differs from CLAUDE.md sec.4 in three deliberate, verified ways:

1. ``vec_chunks`` declares ``doc_id`` as a **metadata column**. This is the
   anti-bleed mechanism. The spec's form -- filtering the PK via
   ``chunk_id IN (subquery)`` -- is applied by sqlite-vec *after* ``k``, making
   it a post-filter: exactly the approach IMPLEMENTATION_PLAN.md:235 rejected
   ("if modern chunks dominate similarity scores, the filtered results will be
   empty"). Measured on sqlite-vec v0.1.9: with 200 chunks and a query hugging
   the modern cluster, the spec's form returns 0 rows while a metadata filter
   returns the correct historical top-k. See tests/test_vector_retrieval.py.

2. ``article_num`` / ``section_num`` are restored from the PRD schema. Legal
   citations must resolve to a section, not merely a page.

3. Only verified chunks are inserted into ``vec_chunks``. It *is* the active
   RAG index, so the withhold-until-approved rule of CLAUDE.md sec.7.3 is
   enforced by construction rather than by a filter someone can forget.

4. ``documents.source_tier`` declares what kind of authority a citation carries.
   Pre-1995 seasons have no surviving public CBA text, so their coverage rests on
   court opinions and curated timeline entries. Rendered in the same citation
   shape those look identical to the governing document and are not: one is the
   rule, the other is a summary someone wrote. The tier keeps that visible.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from src.db.connection import get_vector_db_connection

EMBEDDING_DIM = 768  # BAAI/bge-base-en-v1.5

# What kind of authority a document's citations carry.
#   primary   the governing document itself (CBAs, Constitutions, the Rulebook)
#   judicial  a court opinion -- a primary legal source, but it *describes* the
#             rule rather than being it
#   timeline  a curated, cited entry written for this project
PRIMARY_TIERS = ("primary", "judicial")
TIMELINE_TIER = "timeline"
ALL_TIERS = ("primary", "judicial", "timeline")

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_name      TEXT UNIQUE NOT NULL,
    category      TEXT NOT NULL CHECK (category IN
                      ('Historical', 'Current Operational', 'Current Governing')),
    start_season  INTEGER NOT NULL,
    end_season    INTEGER NOT NULL,
    source_url    TEXT NOT NULL,
    source_tier   TEXT NOT NULL DEFAULT 'primary' CHECK (source_tier IN
                      ('primary', 'judicial', 'timeline')),
    CHECK (start_season <= end_season)
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id        INTEGER NOT NULL,
    chunk_hash    TEXT UNIQUE NOT NULL,
    article_num   TEXT,
    section_num   TEXT,
    page_num      INTEGER NOT NULL,
    is_verified   INTEGER NOT NULL DEFAULT 0 CHECK (is_verified IN (0, 1)),
    text_content  TEXT NOT NULL,
    FOREIGN KEY (doc_id) REFERENCES documents (id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
    chunk_id   INTEGER PRIMARY KEY,
    doc_id     INTEGER,
    embedding  float[{EMBEDDING_DIM}] distance_metric=cosine
);

CREATE TABLE IF NOT EXISTS historical_concept_mapper (
    concept_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    archaic_term           TEXT UNIQUE NOT NULL,
    modern_analogy         TEXT NOT NULL,
    simplified_explanation TEXT NOT NULL,
    valid_from_year        INTEGER NOT NULL,
    valid_to_year          INTEGER NOT NULL
);

-- Keeps the vector index from outliving the text it describes.
CREATE TRIGGER IF NOT EXISTS sync_vec_index_on_chunk_deletion
AFTER DELETE ON document_chunks
BEGIN
    DELETE FROM vec_chunks WHERE chunk_id = OLD.id;
END;

CREATE INDEX IF NOT EXISTS idx_documents_seasons
    ON documents (start_season, end_season);
CREATE INDEX IF NOT EXISTS idx_documents_tier ON documents (source_tier);
CREATE INDEX IF NOT EXISTS idx_chunks_doc      ON document_chunks (doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_verified ON document_chunks (is_verified);
"""


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Bring an existing index up to the current schema. Returns what changed.

    ``SCHEMA_SQL`` is all ``CREATE ... IF NOT EXISTS``, so a new column never
    reaches a database that already exists -- and rebuilding the shipped index to
    add one costs about eighty minutes of CPU embedding. Additive migrations run
    here instead.
    """
    applied: list[str] = []
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(documents)")}
    if "source_tier" not in columns:
        # SQLite cannot add a CHECK constraint to an existing table via ALTER,
        # so the column carries the default and the constraint is enforced on
        # rebuild. Existing rows are all governing documents.
        conn.execute("ALTER TABLE documents ADD COLUMN source_tier TEXT "
                     "NOT NULL DEFAULT 'primary'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_tier "
                     "ON documents (source_tier)")
        applied.append("documents.source_tier added (existing rows -> 'primary')")
    if applied:
        conn.commit()
    return applied


def initialize_database(db_path: str | Path = ":memory:") -> sqlite3.Connection:
    """Create (idempotently) every table, trigger and index, and return the conn."""
    conn = get_vector_db_connection(db_path)
    conn.executescript(SCHEMA_SQL)
    migrate(conn)
    conn.commit()
    return conn


def resolve_era_documents(
    conn: sqlite3.Connection,
    season: int,
    tiers: tuple[str, ...] | None = None,
) -> list[int]:
    """Document ids valid for ``season``. The relational half of the pre-filter.

    ``tiers`` selects which kinds of source may answer. Retrieval runs this twice
    -- once for PRIMARY_TIERS and once for TIMELINE_TIER -- so curated summaries
    never compete with the governing text for the same top-k slots.
    """
    if tiers is None:
        sql = ("SELECT id FROM documents WHERE start_season <= ? AND end_season >= ? "
               "ORDER BY id")
        params: tuple = (season, season)
    else:
        placeholders = ",".join("?" * len(tiers))
        sql = (f"SELECT id FROM documents WHERE start_season <= ? AND end_season >= ? "
               f"AND source_tier IN ({placeholders}) ORDER BY id")
        params = (season, season, *tiers)
    return [row["id"] for row in conn.execute(sql, params)]


def ambiguous_seasons(conn: sqlite3.Connection) -> set[int]:
    """Four-digit years whose two possible seasons resolve to different documents.

    "2023" may mean the 2022-23 season or 2023-24, and in this corpus those reach
    different CBAs -- which is why CLAUDE.md sec.5.2 requires a clarification
    prompt. But 2023 is not special: every document-window boundary creates the
    same ambiguity. Measured against the shipped manifest, **fourteen** years are
    ambiguous, of which the spec names one. "What was the salary cap in 2011?"
    silently resolves to CBA 2011 even though the 2010-11 season is governed by
    CBA 2005 -- a wrong answer delivered with a real-looking citation, which is
    the precise failure mode this project exists to prevent.

    Deriving the set from the corpus rather than hardcoding it means adding or
    re-scoping a document cannot leave a stale boundary silently unguarded.
    """
    # Primary tier only. "Did you mean 2022-23 or 2023-24?" is worth asking
    # because a different *governing document* applies. A timeline entry
    # beginning in 1984 changes no such thing, and counting the ~50 of them
    # would make almost every year in the historical range ambiguous -- turning
    # a precision feature into a wall of clarification prompts.
    rows = conn.execute(
        "SELECT start_season, end_season FROM documents WHERE source_tier = 'primary'"
    ).fetchall()
    if not rows:
        return set()
    windows = [(r["start_season"], r["end_season"]) for r in rows]
    lo = min(s for s, _ in windows)
    hi = max(e for _, e in windows)

    def covering(year: int) -> frozenset[int]:
        return frozenset(i for i, (s, e) in enumerate(windows) if s <= year <= e)

    # Year Y is ambiguous when season (Y-1..Y) and season (Y..Y+1) -- keyed by
    # their starting years Y-1 and Y -- are governed by different documents.
    return {y for y in range(lo, hi + 2) if covering(y - 1) != covering(y)}


def coverage_bounds(conn: sqlite3.Connection) -> tuple[int, int] | None:
    """The first and last season any source in the index speaks to."""
    row = conn.execute(
        "SELECT min(start_season) AS lo, max(end_season) AS hi FROM documents"
    ).fetchone()
    if not row or row["lo"] is None:
        return None
    return int(row["lo"]), int(row["hi"])


def nearest_covered_season(conn: sqlite3.Connection, season: int) -> int | None:
    """The covered season closest to ``season``, for an informative refusal.

    Telling someone "nothing covers 1952, the earliest is 1946" is useless if
    1946 is in fact covered and 1952 is not -- so this looks for the nearest
    season that actually resolves to a document, rather than assuming coverage
    is one contiguous block.
    """
    bounds = coverage_bounds(conn)
    if bounds is None:
        return None
    lo, hi = bounds
    for offset in range(0, (hi - lo) + 1):
        for candidate in (season - offset, season + offset):
            if lo <= candidate <= hi and resolve_era_documents(conn, candidate):
                return candidate
    return None
