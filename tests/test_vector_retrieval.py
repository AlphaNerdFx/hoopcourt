"""Anti-bleed retrieval tests.

The central test here is deliberately built to FAIL against the implementation
in BUILD_SEQUENCE.md:1429-1507. A 2-chunk fixture (the spec's own test) cannot
distinguish a pre-filter from a post-filter; this one can.
"""
from __future__ import annotations

import sqlite3

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


def _spec_form_rows(conn, query, historical):
    """The specification's filter: constrain the PRIMARY KEY via a subquery."""
    ph = ",".join("?" * len(historical))
    return conn.execute(
        f"""SELECT chunk_id FROM vec_chunks
            WHERE embedding MATCH ? AND k = 5
              AND chunk_id IN (SELECT id FROM document_chunks WHERE doc_id IN ({ph}))""",
        (serialize_float32(query), *historical),
    ).fetchall()


def test_primary_key_filter_behaviour_depends_on_the_sqlite_planner(
        adversarial_index, record_property):
    """Characterisation: the spec's PK form is not portable, which is the point.

    Originally this asserted the PK form returns zero rows, and it did on the
    machine where D2 was measured (SQLite 3.37.2, sqlite-vec v0.1.9): the filter
    is applied after `k`, so when modern chunks dominate the ranking the
    historical ones are gone before the constraint runs.

    CI then failed it on the SAME sqlite-vec version. The difference is the
    SQLite build: a newer query planner pushes the `chunk_id IN (...)`
    constraint into the virtual-table scan, so the PK form happens to work
    there.

    That makes the PK form's correctness a property of whichever SQLite the user
    happens to have, which is a worse position than it failing everywhere. This
    test therefore records the behaviour rather than demanding one of them, and
    the next test asserts the thing that must hold on every build.
    """
    conn, query, doc_ids = adversarial_index
    historical = [doc_ids[n] for n in HISTORICAL_DOCS]
    rows = _spec_form_rows(conn, query, historical)
    behaviour = "pre-filter" if rows else "post-filter"

    # record_property reaches the report even under `-q`. The `print` this
    # replaced did not, so the observation the test exists to capture was
    # invisible in every run of it. TESTING.md rule 2.
    record_property("sqlite_version", sqlite3.sqlite_version)
    record_property("pk_filter_behaviour", behaviour)
    record_property("pk_filter_rows", len(rows))

    if rows:
        # This build pushed the constraint into the virtual-table scan. Then it
        # has to have pushed it *correctly*. A third outcome -- rows from the
        # wrong era -- is the bleed D2 exists to prevent and would be worse than
        # either known behaviour, so it is the thing worth asserting here.
        ph = ",".join("?" * len(historical))
        allowed = {r[0] for r in conn.execute(
            f"SELECT id FROM document_chunks WHERE doc_id IN ({ph})", historical)}
        leaked = {r[0] for r in rows} - allowed
        assert not leaked, (
            f"PK form acted as a pre-filter but leaked chunks {sorted(leaked)} "
            f"from outside the requested era")
    else:
        # This build applied `k` first. That reading only means anything if the
        # search can find historical chunks at all, so pin the fixture: the
        # metadata form, same connection, same query, must return them.
        assert retrieve_by_documents(conn, query, historical, k=5), (
            "the PK form returned nothing and so did the metadata form, so this "
            "is a broken fixture rather than a post-filter")


def test_metadata_column_filter_is_correct_on_every_sqlite(adversarial_index):
    """The invariant D2 actually rests on, and the reason the schema uses it.

    Unlike the PK form, constraining a declared metadata column restricts
    candidates before the search on every build tested. Era isolation cannot be
    contingent on the user's SQLite version.
    """
    conn, query, doc_ids = adversarial_index
    historical = [doc_ids[n] for n in HISTORICAL_DOCS]
    rows = retrieve_by_documents(conn, query, historical, k=5)
    assert rows, "the metadata-column pre-filter returned nothing"
    reached = {r["document"] for r in rows}
    assert reached <= set(HISTORICAL_DOCS), (
        f"era bleed: reached {sorted(reached)}, expected a subset of "
        f"{sorted(HISTORICAL_DOCS)}"
    )
