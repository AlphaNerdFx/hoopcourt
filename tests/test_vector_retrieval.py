"""Anti-bleed retrieval tests.

The central test here is deliberately built to FAIL against the implementation
in BUILD_SEQUENCE.md:1429-1507. A 2-chunk fixture (the spec's own test) cannot
distinguish a pre-filter from a post-filter; this one can.
"""
from __future__ import annotations

from sqlite_vec import serialize_float32

from src.db.schema import resolve_era_documents
from src.db.search import retrieve_by_documents, retrieve_segmented_context

HISTORICAL_DOCS = {"CBA 1995", "NBPA CBA 1999"}
MODERN_DOCS = {"CBA 2017", "2023 NBA CBA"}


def test_unfiltered_search_is_dominated_by_modern_chunks(adversarial_index):
    """Baseline: without era filtering, the modern era wins every slot."""
    conn, query, doc_ids = adversarial_index
    all_ids = list(doc_ids.values())
    results = retrieve_by_documents(conn, query, all_ids, k=5)
    assert {r["document"] for r in results} <= MODERN_DOCS, (
        "fixture is not adversarial enough -- modern chunks must dominate"
    )


def test_historical_query_returns_zero_modern_chunks(adversarial_index):
    """The project's central claim: no rule bleeding, ever.

    Fails outright under the spec's post-filter form, which returns 0 rows here.
    """
    conn, query, _ = adversarial_index
    results = retrieve_segmented_context(
        conn, query, {"route_action": "strict_season_filter", "target_year": 1996}, k=5
    )
    assert results, "era-filtered retrieval returned nothing (post-filter symptom)"
    assert len(results) == 5
    assert all(r["document"] == "CBA 1995" for r in results), (
        f"rule bleeding: {sorted({r['document'] for r in results})}"
    )


def test_modern_query_returns_zero_historical_chunks(adversarial_index):
    conn, query, _ = adversarial_index
    results = retrieve_segmented_context(
        conn, query, {"route_action": "default_modern", "target_year": 2024}, k=5
    )
    assert results and all(r["document"] == "2023 NBA CBA" for r in results)


def test_results_are_globally_sorted_by_distance(adversarial_index):
    """sqlite-vec returns k rows PER document, grouped and unsorted across them."""
    conn, query, _ = adversarial_index
    results = retrieve_segmented_context(
        conn, query, {"route_action": "strict_season_filter", "target_year": 2000}, k=4
    )
    distances = [r["distance"] for r in results]
    assert distances == sorted(distances), "outer ORDER BY is missing"
    assert len(results) == 4, "k must bound the final result set, not the per-doc set"


def test_era_boundaries_are_inclusive(adversarial_index):
    conn, _, doc_ids = adversarial_index
    assert resolve_era_documents(conn, 1995) == [doc_ids["CBA 1995"]]
    assert resolve_era_documents(conn, 1998) == [doc_ids["CBA 1995"]]
    assert resolve_era_documents(conn, 1999) == [doc_ids["NBPA CBA 1999"]]


def test_uncovered_era_returns_nothing_rather_than_nearest_match(adversarial_index):
    """A 1952 question has no source document. Silence beats a plausible answer."""
    conn, query, _ = adversarial_index
    assert resolve_era_documents(conn, 1952) == []
    assert retrieve_segmented_context(
        conn, query, {"route_action": "strict_season_filter", "target_year": 1952}, k=5
    ) == []


def test_ambiguous_season_suspends_search(adversarial_index):
    """PRD User Story 1: hold the search until the user disambiguates."""
    conn, query, _ = adversarial_index
    assert retrieve_segmented_context(
        conn, query,
        {"route_action": "require_season_clarification", "target_year": 2023}, k=5,
    ) == []


def test_spec_primary_key_filter_is_a_post_filter(adversarial_index):
    """Characterization test: documents *why* the schema deviates from the spec.

    If a future sqlite-vec makes the PK form a true pre-filter, this test fails
    and the deviation can be revisited.
    """
    conn, query, doc_ids = adversarial_index
    historical = [doc_ids[n] for n in HISTORICAL_DOCS]
    ph = ",".join("?" * len(historical))
    spec_rows = conn.execute(
        f"""SELECT chunk_id FROM vec_chunks
            WHERE embedding MATCH ? AND k = 5
              AND chunk_id IN (SELECT id FROM document_chunks WHERE doc_id IN ({ph}))""",
        (serialize_float32(query), *historical),
    ).fetchall()
    assert spec_rows == [], (
        "sqlite-vec now pre-filters on the primary key; revisit src/db/schema.py"
    )
