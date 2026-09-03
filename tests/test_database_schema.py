"""Schema, constraint and index-synchronisation tests."""
from __future__ import annotations

import sqlite3

import pytest
from sqlite_vec import serialize_float32

from src.db.connection import engine_versions
from src.db.schema import EMBEDDING_DIM, initialize_database


def _seed_one(conn, season=2023):
    cur = conn.execute(
        "INSERT INTO documents (doc_name, category, start_season, end_season, source_url)"
        " VALUES ('doc', 'Current Governing', ?, ?, 'https://example.invalid')",
        (season, season + 6),
    )
    doc_id = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO document_chunks (doc_id, chunk_hash, page_num, is_verified, text_content)"
        " VALUES (?, 'hash-1', 1, 1, 'text')",
        (doc_id,),
    )
    chunk_id = cur.lastrowid
    conn.execute(
        "INSERT INTO vec_chunks (chunk_id, doc_id, embedding) VALUES (?,?,?)",
        (chunk_id, doc_id, serialize_float32([0.1] * EMBEDDING_DIM)),
    )
    conn.commit()
    return doc_id, chunk_id


def test_schema_is_idempotent():
    conn = initialize_database(":memory:")
    conn.executescript(__import__("src.db.schema", fromlist=["SCHEMA_SQL"]).SCHEMA_SQL)


def test_trigger_removes_orphaned_vectors(conn):
    _, chunk_id = _seed_one(conn)
    conn.execute("DELETE FROM document_chunks WHERE id = ?", (chunk_id,))
    conn.commit()
    assert conn.execute(
        "SELECT count(*) FROM vec_chunks WHERE chunk_id = ?", (chunk_id,)
    ).fetchone()[0] == 0


def test_document_delete_cascades_all_the_way_to_the_vector_index(conn):
    """documents -> document_chunks is an FK cascade; chunks -> vectors is the trigger.

    This asserts the two mechanisms actually chain, which is the failure mode
    that leaves dead references in the index.
    """
    doc_id, chunk_id = _seed_one(conn)
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.commit()
    assert conn.execute("SELECT count(*) FROM document_chunks").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM vec_chunks").fetchone()[0] == 0


def test_index_and_text_counts_stay_equal_after_churn(conn):
    doc_id, _ = _seed_one(conn)
    for i in range(2, 12):
        cur = conn.execute(
            "INSERT INTO document_chunks (doc_id, chunk_hash, page_num, is_verified,"
            " text_content) VALUES (?,?,?,1,'t')", (doc_id, f"hash-{i}", i))
        conn.execute("INSERT INTO vec_chunks (chunk_id, doc_id, embedding) VALUES (?,?,?)",
                     (cur.lastrowid, doc_id, serialize_float32([0.2] * EMBEDDING_DIM)))
    conn.execute("DELETE FROM document_chunks WHERE page_num % 2 = 0")
    conn.commit()
    assert (conn.execute("SELECT count(*) FROM document_chunks").fetchone()[0]
            == conn.execute("SELECT count(*) FROM vec_chunks").fetchone()[0])


def test_duplicate_chunk_hash_is_rejected(conn):
    doc_id, _ = _seed_one(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO document_chunks (doc_id, chunk_hash, page_num, text_content)"
            " VALUES (?, 'hash-1', 9, 't')", (doc_id,))


def test_invalid_category_is_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO documents (doc_name, category, start_season, end_season, source_url)"
            " VALUES ('x', 'Made Up', 2000, 2001, 'u')")


def test_inverted_season_range_is_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO documents (doc_name, category, start_season, end_season, source_url)"
            " VALUES ('x', 'Historical', 2005, 1999, 'u')")


def test_foreign_keys_are_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO document_chunks (doc_id, chunk_hash, page_num, text_content)"
            " VALUES (99999, 'h', 1, 't')")


def test_engine_versions_reported(conn):
    v = engine_versions(conn)
    assert v["sqlite"] and v["sqlite_vec"].startswith("v")


# --------------------------------------------------------------- ambiguity


def _doc(conn, name, start, end, category="Historical"):
    return conn.execute(
        "INSERT INTO documents (doc_name, category, start_season, end_season,"
        " source_url) VALUES (?,?,?,?,'https://example.invalid')",
        (name, category, start, end),
    ).lastrowid


def test_ambiguous_seasons_finds_every_document_boundary(conn):
    """Not just 2023. Each boundary between consecutive windows is ambiguous:
    "2011" may mean 2010-11 (CBA 2005) or 2011-12 (CBA 2011)."""
    from src.db.schema import ambiguous_seasons

    _doc(conn, "CBA 2005", 2005, 2010)
    _doc(conn, "CBA 2011", 2011, 2016)
    _doc(conn, "CBA 2017", 2017, 2022)
    conn.commit()
    ambiguous = ambiguous_seasons(conn)

    assert {2005, 2011, 2017} <= ambiguous, "each boundary must be flagged"
    for interior in (2007, 2013, 2019):
        assert interior not in ambiguous, f"{interior} is unambiguous"


def test_ambiguous_seasons_ignores_years_where_the_answer_does_not_change(conn):
    from src.db.schema import ambiguous_seasons

    _doc(conn, "Long CBA", 1995, 2005)
    conn.commit()
    ambiguous = ambiguous_seasons(conn)
    assert all(y not in ambiguous for y in range(1996, 2005))


def test_ambiguous_seasons_handles_overlapping_document_types(conn):
    """A Constitution and a CBA can both be valid in one season; only a change in
    the covering SET makes a year ambiguous."""
    from src.db.schema import ambiguous_seasons

    _doc(conn, "CBA", 2017, 2022)
    _doc(conn, "Constitution", 2019, 2023, category="Current Governing")
    conn.commit()
    ambiguous = ambiguous_seasons(conn)
    assert 2019 in ambiguous, "the Constitution starting mid-CBA is a boundary"
    assert 2021 not in ambiguous


def test_ambiguous_seasons_on_an_empty_index_is_empty(conn):
    from src.db.schema import ambiguous_seasons

    assert ambiguous_seasons(conn) == set()


# ------------------------------------------------------------ text quality


def test_text_quality_flags_fused_words(conn):
    """Row counts cannot tell you the index is usable: the CBA 2017 defect
    produced correctly-cited chunks whose text was noise (DECISIONS.md D11)."""
    from src.ingest.indexer import text_quality

    doc_id = _doc(conn, "Fused Doc", 2017, 2022)
    clean_id = _doc(conn, "Clean Doc", 2011, 2016)
    rows = [
        (doc_id, "a", "shall apply foreachSeasonoftheContract andTheTeamShallPay"),
        (doc_id, "b", "moreFusedText hereAgain andAgainStill"),
        (clean_id, "c", "The Team shall pay the player in accordance with Section 7."),
        (clean_id, "d", "Minimum Annual Salary Scale for the 2018-19 Salary Cap Year."),
    ]
    for did, h, text in rows:
        conn.execute(
            "INSERT INTO document_chunks (doc_id, chunk_hash, page_num, is_verified,"
            " text_content) VALUES (?,?,1,1,?)", (did, h, text))
    conn.commit()

    q = text_quality(conn)
    assert q["chunks"] == 4
    assert q["fused_chunks"] == 2
    assert q["fused_pct"] == 50.0
    assert q["by_document"] == {"Fused Doc": 2}


def test_text_quality_is_clean_on_normal_legal_prose(conn):
    from src.ingest.indexer import text_quality

    doc_id = _doc(conn, "Normal", 2023, 2029, category="Current Governing")
    for i, text in enumerate([
        "Notwithstanding any other provision of this Agreement, the Maximum "
        "Annual Salary shall not exceed thirty-five percent (35%) of the Cap.",
        "Section 7. Maximum Annual Salary. (a) No Player Contract entered into "
        "on or after the effective date shall provide for Salary in excess of.",
        "The NBA and the Players Association agree that BRI shall be computed.",
    ]):
        conn.execute(
            "INSERT INTO document_chunks (doc_id, chunk_hash, page_num, is_verified,"
            " text_content) VALUES (?,?,1,1,?)", (doc_id, f"h{i}", text))
    conn.commit()
    q = text_quality(conn)
    assert q["fused_chunks"] == 0 and q["by_document"] == {}


def test_text_quality_on_empty_index(conn):
    from src.ingest.indexer import text_quality

    q = text_quality(conn)
    assert q == {"chunks": 0, "fused_chunks": 0, "fused_pct": 0.0, "by_document": {}}
