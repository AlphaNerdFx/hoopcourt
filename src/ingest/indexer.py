"""Populate the relational tables and the vector index.

This is the step BUILD_SEQUENCE.md never had: without it the schema, the router
and the search function have nothing to operate on.

Only verified chunks reach ``vec_chunks``, which *is* the active RAG index -- so
the withhold-until-approved rule of CLAUDE.md sec.7.3 holds by construction. Text
extracted directly from a born-digital PDF is verified on arrival: the rule
exists to gate OCR guesswork and injected scan content, and there is neither
here (see scripts/audit_corpus.py).
"""
from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence

from sqlite_vec import serialize_float32

from src.ingest.chunker import Chunk
from src.ingest.embedder import Embedder


def upsert_document(
    conn: sqlite3.Connection,
    doc_name: str,
    category: str,
    start_season: int,
    end_season: int,
    source_url: str,
    source_tier: str = "primary",
) -> int:
    """Insert or update a document row, returning its id.

    ``source_tier`` declares what a citation from this document is worth --
    the governing text, a court opinion describing it, or a curated summary.
    """
    conn.execute(
        """INSERT INTO documents (doc_name, category, start_season, end_season,
                                  source_url, source_tier)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(doc_name) DO UPDATE SET
               category=excluded.category, start_season=excluded.start_season,
               end_season=excluded.end_season, source_url=excluded.source_url,
               source_tier=excluded.source_tier""",
        (doc_name, category, start_season, end_season, source_url, source_tier),
    )
    return conn.execute(
        "SELECT id FROM documents WHERE doc_name = ?", (doc_name,)
    ).fetchone()["id"]


def clear_document(conn: sqlite3.Connection, doc_id: int) -> int:
    """Delete a document's chunks. The trigger clears the vectors with them."""
    n = conn.execute(
        "SELECT count(*) FROM document_chunks WHERE doc_id = ?", (doc_id,)
    ).fetchone()[0]
    conn.execute("DELETE FROM document_chunks WHERE doc_id = ?", (doc_id,))
    return n


def index_chunks(
    conn: sqlite3.Connection,
    doc_id: int,
    chunks: Sequence[Chunk],
    embedder: Embedder,
    is_verified: int = 1,
    batch_size: int = 32,
    show_progress: bool = False,
) -> int:
    """Embed and insert chunks. Returns the number indexed."""
    if not chunks:
        return 0

    vectors = embedder.embed_passages(
        [c.text for c in chunks], batch_size=batch_size, show_progress=show_progress
    )
    indexed = 0
    # strict: a length mismatch here would silently drop chunks.
    for chunk, vector in zip(chunks, vectors, strict=True):
        try:
            cur = conn.execute(
                """INSERT INTO document_chunks
                   (doc_id, chunk_hash, article_num, section_num, page_num,
                    is_verified, text_content)
                   VALUES (?,?,?,?,?,?,?)""",
                (doc_id, chunk.chunk_hash, chunk.article, chunk.section,
                 chunk.page_num, is_verified, chunk.text),
            )
        except sqlite3.IntegrityError:
            continue  # duplicate chunk_hash: identical boilerplate, already stored
        if is_verified:
            conn.execute(
                "INSERT INTO vec_chunks (chunk_id, doc_id, embedding) VALUES (?,?,?)",
                (cur.lastrowid, doc_id, serialize_float32(vector)),
            )
        indexed += 1
    return indexed


# "foreachSeasonoftheContract" -- see DECISIONS.md D11. A fused span tokenizes
# into noise, so the chunk is retrievable by doc_id and unfindable by meaning.
RE_FUSED = re.compile(r"[a-z][A-Z][a-z]")
FUSED_PER_CHUNK_LIMIT = 3

# Capitalised name particles intercap legitimately and are not extraction
# failures. Court opinions are full of them, because they are full of party
# names: a single Robertson plaintiff list reading "Jon McGlocklin, McCoy
# McLemore" trips the detector three times in one sentence and pushes a
# judicial-only build to 1.26%, over the 1% gate. Measured on the public-domain
# index the release workflow builds: 3 chunks flagged, all the same passage,
# 0 once these are ignored.
#
# Removing them costs nothing for PDFs either. "McGlocklin" in a PDF is a name
# there too.
RE_NAME_PARTICLE = re.compile(r"\b(?:Mc|Mac|De|Di|La|Le|Van|Von|O')[A-Z][a-z]")


def fused_spans(text: str) -> list[str]:
    """Runs that look like two words joined, ignoring proper-noun intercaps."""
    return RE_FUSED.findall(RE_NAME_PARTICLE.sub("", text))


def index_integrity(conn: sqlite3.Connection) -> dict[str, int]:
    """Counts used by the build gate and the /health endpoint."""
    q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    return {
        "documents": q("SELECT count(*) FROM documents"),
        "chunks": q("SELECT count(*) FROM document_chunks"),
        "verified_chunks": q("SELECT count(*) FROM document_chunks WHERE is_verified=1"),
        "vectors": q("SELECT count(*) FROM vec_chunks"),
        "orphaned_vectors": q(
            "SELECT count(*) FROM vec_chunks WHERE chunk_id NOT IN "
            "(SELECT id FROM document_chunks)"
        ),
    }


def text_quality(conn: sqlite3.Connection) -> dict[str, object]:
    """Count chunks whose words fused during extraction.

    Row counts alone cannot tell you the index is usable: the CBA 2017 defect
    produced the right number of correctly-cited chunks whose text was noise.
    Every build reports this so the failure is visible at build time rather than
    as quietly worse answers for one era.
    """
    worst: dict[str, int] = {}
    fused_chunks = 0
    total = 0
    for row in conn.execute(
        "SELECT d.doc_name AS doc, c.text_content AS text "
        "FROM document_chunks c JOIN documents d ON d.id = c.doc_id"
    ):
        total += 1
        if len(fused_spans(row["text"])) >= FUSED_PER_CHUNK_LIMIT:
            fused_chunks += 1
            worst[row["doc"]] = worst.get(row["doc"], 0) + 1
    return {
        "chunks": total,
        "fused_chunks": fused_chunks,
        "fused_pct": round(100 * fused_chunks / total, 2) if total else 0.0,
        "by_document": dict(sorted(worst.items(), key=lambda kv: -kv[1])),
    }
