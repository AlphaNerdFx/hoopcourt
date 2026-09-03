"""Era-isolated vector retrieval -- the anti-bleed core.

Two measured facts about sqlite-vec v0.1.9 shape this module:

* A metadata-column constraint (``doc_id IN (...)``) is a genuine **pre-filter**:
  candidates are restricted before the KNN runs. A primary-key constraint
  (``chunk_id IN (...)``, the form in BUILD_SEQUENCE.md:1429) is a **post-filter**
  applied after ``k``, and silently returns nothing when another era dominates
  the similarity ranking.

* With an IN-list of N documents, sqlite-vec returns ``k`` rows **per document**,
  grouped by document and *not* globally sorted by distance. The outer
  ``ORDER BY distance ASC LIMIT k`` is therefore load-bearing, not cosmetic:
  without it the caller gets the wrong top-k in the wrong order.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from typing import Any

from sqlite_vec import serialize_float32

from src.db.schema import (
    PRIMARY_TIERS,
    TIMELINE_TIER,
    resolve_era_documents,
)


def retrieve_by_documents(
    conn: sqlite3.Connection,
    query_embedding: Sequence[float],
    doc_ids: Sequence[int],
    k: int = 5,
) -> list[dict[str, Any]]:
    """Top-``k`` chunks restricted to ``doc_ids``, nearest first."""
    if not doc_ids:
        # No document covers the requested era. Returning nothing is correct:
        # the grounding rule (CLAUDE.md sec.2.2) prefers silence to invention.
        return []

    placeholders = ",".join("?" * len(doc_ids))
    sql = f"""
        SELECT c.id            AS chunk_id,
               c.text_content  AS text,
               c.article_num   AS article,
               c.section_num   AS section,
               c.page_num      AS page,
               d.doc_name      AS document,
               d.source_tier   AS source_tier,
               d.start_season  AS start_season,
               d.end_season    AS end_season,
               knn.distance    AS distance
        FROM (
            SELECT chunk_id, distance
            FROM vec_chunks
            WHERE embedding MATCH ?
              AND k = ?
              AND doc_id IN ({placeholders})
        ) AS knn
        JOIN document_chunks c ON c.id = knn.chunk_id
        JOIN documents       d ON d.id = c.doc_id
        ORDER BY knn.distance ASC
        LIMIT ?
    """
    params = (serialize_float32(list(query_embedding)), k, *doc_ids, k)
    return [dict(row) for row in conn.execute(sql, params)]


def retrieve_segmented_context(
    conn: sqlite3.Connection,
    query_embedding: Sequence[float],
    route_data: dict[str, Any],
    k: int = 5,
    tiers: tuple[str, ...] | None = PRIMARY_TIERS,
) -> list[dict[str, Any]]:
    """Resolve the routing decision to an era window, then retrieve within it.

    ``route_data`` comes from ``src.api.router.TemporalRouter.resolve_query_route``.

    ``tiers`` defaults to the authoritative sources -- the governing documents
    and court opinions. Curated timeline entries are fetched by a separate call
    so that a hand-written summary can never displace the governing text in the
    same top-k: summaries are dense and query-shaped, and would win.
    """
    action = route_data.get("route_action")
    target_year = route_data.get("target_year")

    if action == "require_season_clarification":
        # The caller must resolve the ambiguity before any search happens
        # (PRD User Story 1). Searching a guessed season is the bug, not a fallback.
        return []

    if target_year is None:
        return []

    doc_ids = resolve_era_documents(conn, int(target_year), tiers)
    return retrieve_by_documents(conn, query_embedding, doc_ids, k=k)


# A vector search always returns its k nearest rows, however far away they are.
# With only ~21 timeline entries that is a real problem: "what were the luxury
# tax rules in 1952?" returned the reserve-clause entry, because it was merely
# the closest of a small set, and an irrelevant entry in context is an invitation
# to answer from it. Measured over relevant and irrelevant queries, the nearest
# distances separate cleanly: 0.240-0.338 when an entry genuinely answers, and
# 0.457-0.621 when nothing does. 0.40 sits in that gap.
TIMELINE_MAX_DISTANCE = 0.40


def retrieve_timeline(
    conn: sqlite3.Connection,
    query_embedding: Sequence[float],
    route_data: dict[str, Any],
    k: int = 3,
    max_distance: float = TIMELINE_MAX_DISTANCE,
) -> list[dict[str, Any]]:
    """The curated-timeline channel: answers *when a rule changed*.

    Runs even when the governing text exists, because "when was the salary cap
    introduced?" carries no year and no trigger term, routes to the current
    season, and retrieves 2023 CBA text that never states the answer. A separate
    always-run channel covers that without letting summaries outrank the rule.
    """
    rows = retrieve_segmented_context(
        conn, query_embedding, route_data, k=k, tiers=(TIMELINE_TIER,)
    )
    rows = [r for r in rows if r["distance"] <= max_distance]
    if rows:
        return rows

    # Nothing dated to the routed era. Only now widen to the whole timeline,
    # because "when was the salary cap introduced?" carries no year, routes to
    # the current season, and the entry that answers it is scoped 1983-1994.
    #
    # The fallback is deliberately conditional. Searching the whole timeline
    # unconditionally would let a 1985 entry answer a 1975 question, which is
    # the anachronism this project exists to prevent. It can only fire when the
    # routed era has no timeline entry of its own to contradict, which in this
    # corpus means a season from 1995 onward.
    all_timeline = [r["id"] for r in conn.execute(
        "SELECT id FROM documents WHERE source_tier = ? ORDER BY id",
        (TIMELINE_TIER,))]
    if not all_timeline:
        return []
    wide = retrieve_by_documents(conn, query_embedding, all_timeline, k=k)
    return [r for r in wide if r["distance"] <= max_distance]
