"""Schema, constraint and index-synchronisation tests."""
from __future__ import annotations

import sqlite3

import pytest
from sqlite_vec import serialize_float32

from src.db.connection import engine_versions, get_vector_db_connection
from src.db.schema import EMBEDDING_DIM, SCHEMA_SQL, initialize_database, migrate


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


# --------------------------------------------------------------- migration

# The shape of an index built before source_tier existed.
_LEGACY_DOCUMENTS = """
CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT, doc_name TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL CHECK (category IN
        ('Historical', 'Current Operational', 'Current Governing')),
    start_season INTEGER NOT NULL, end_season INTEGER NOT NULL,
    source_url TEXT NOT NULL, CHECK (start_season <= end_season));
"""
_BOGUS_TIER = ("INSERT INTO documents (doc_name, category, start_season, end_season,"
               " source_url, source_tier) VALUES ('bogus', 'Historical', 1, 2, 'u',"
               " 'bogus')")


def _legacy_index(path, *, with_tier_column):
    """An on-disk index as an older build left it. With the column but no CHECK
    it is exactly the shape measured in the shipped nba_legal.db."""
    conn = get_vector_db_connection(path)
    conn.execute(_LEGACY_DOCUMENTS)
    if with_tier_column:
        conn.execute("ALTER TABLE documents ADD COLUMN source_tier TEXT "
                     "NOT NULL DEFAULT 'primary'")
    conn.executescript(SCHEMA_SQL)  # everything else; documents already exists
    return conn


def _objects(conn):
    return {(r["type"], r["name"]) for r in conn.execute(
        "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        " AND name NOT LIKE 'vec_chunks_%'")}


def test_migrating_a_pre_tier_index_yields_a_table_that_rejects_an_invalid_tier(tmp_path):
    conn = get_vector_db_connection(tmp_path / "old.db")
    conn.execute(_LEGACY_DOCUMENTS)
    conn.commit()
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError, match="source_tier"):
        conn.execute(_BOGUS_TIER)


def test_a_column_only_index_gains_the_check_ALTER_cannot_add(tmp_path):
    conn = _legacy_index(tmp_path / "old.db", with_tier_column=True)
    conn.execute(_BOGUS_TIER)  # the defect: accepted before the migration
    conn.rollback()
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError, match="source_tier"):
        conn.execute(_BOGUS_TIER)


def test_the_rebuild_preserves_rows_foreign_key_cascade_trigger_and_indexes(tmp_path):
    conn = _legacy_index(tmp_path / "old.db", with_tier_column=True)
    keep, chunk = _seed_one(conn)
    doomed = conn.execute(
        "INSERT INTO documents (doc_name, category, start_season, end_season,"
        " source_url, source_tier) VALUES ('opinion', 'Historical', 1960, 1970, 'u',"
        " 'judicial')").lastrowid
    conn.execute("DELETE FROM documents WHERE id = ?", (doomed,))
    conn.commit()
    before_rows = conn.execute("SELECT * FROM documents ORDER BY id").fetchall()
    before_objects = _objects(conn)
    before_seq = conn.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = 'documents'").fetchone()[0]

    assert migrate(conn)

    assert [tuple(r) for r in conn.execute("SELECT * FROM documents ORDER BY id")] == [
        tuple(r) for r in before_rows]
    assert conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0] == 1, (
        "DROP TABLE ran with foreign keys on and cascaded the chunks away")
    assert _objects(conn) == before_objects
    fk = conn.execute("PRAGMA foreign_key_list(document_chunks)").fetchone()
    assert (fk["table"], fk["on_delete"]) == ("documents", "CASCADE")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    # The counter survives, so a deleted document's id is not reissued while
    # vec_chunks may still carry it.
    assert conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'documents'"
                        ).fetchone()[0] == before_seq

    # Cascade and trigger still fire against the rebuilt table.
    conn.execute("DELETE FROM documents WHERE id = ?", (keep,))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM vec_chunks WHERE chunk_id = ?",
                        (chunk,)).fetchone()[0] == 0


def test_a_migrated_index_has_the_same_objects_as_a_fresh_one(tmp_path):
    conn = _legacy_index(tmp_path / "old.db", with_tier_column=True)
    migrate(conn)
    assert _objects(conn) == _objects(initialize_database(":memory:"))


def test_migrate_is_idempotent_and_reports_no_second_change(tmp_path):
    conn = _legacy_index(tmp_path / "old.db", with_tier_column=True)
    _seed_one(conn)
    assert migrate(conn)
    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'documents'"
                       ).fetchone()[0]
    assert migrate(conn) == []
    assert conn.execute("SELECT sql FROM sqlite_master WHERE name = 'documents'"
                        ).fetchone()[0] == ddl
    assert migrate(initialize_database(":memory:")) == []


def test_a_row_with_an_invalid_tier_fails_the_migration_and_changes_nothing(tmp_path):
    # Coercing to 'primary' would present a junk tier with a CBA's authority, so
    # the migration refuses and names the row instead.
    conn = _legacy_index(tmp_path / "old.db", with_tier_column=True)
    _seed_one(conn)
    conn.execute(_BOGUS_TIER)
    conn.commit()
    before = _objects(conn)
    with pytest.raises(ValueError, match="bogus"):
        migrate(conn)
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0] == 1
    assert _objects(conn) == before
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


# ---- operational coverage (F5) ----------------------------------------------
# On 2026-10-01 the season rolled over and four documents scoped 2025-2025 left
# the candidate set at once, taking every "shot clock" passage with them, while
# resolve_era_documents still returned six documents so coverage looked complete.
# These pin the discriminator that notices it.

# Named apart from _doc above deliberately: that one defaults to Historical and
# takes no tier, and shadowing it made two unrelated tests fail on a NULL doc_id.
def _tiered_doc(conn, name, start, end, tier="primary",
                category="Current Governing"):
    return conn.execute(
        "INSERT INTO documents (doc_name, category, start_season, end_season,"
        " source_url, source_tier) VALUES (?,?,?,?,'https://example.invalid',?)",
        (name, category, start, end, tier)).lastrowid


def test_a_corpus_with_no_annual_reissue_reports_no_latest_annual_season(conn):
    from src.db.schema import latest_annual_season
    _tiered_doc(conn, "2023 NBA CBA", 2023, 2029)
    assert latest_annual_season(conn) is None


def test_the_latest_annual_season_ignores_multi_season_documents(conn):
    # category cannot be the discriminator: the CBA is "Current Governing" too.
    from src.db.schema import latest_annual_season
    _tiered_doc(conn, "2023 NBA CBA", 2023, 2029)
    _tiered_doc(conn, "Official 2025-26 Rulebook", 2025, 2025)
    assert latest_annual_season(conn) == 2025


def test_a_timeline_entry_does_not_count_as_an_annual_reissue(conn):
    # Timeline entries are one season wide by construction, so counting them
    # would report the corpus as current on the strength of a curated note.
    from src.db.schema import latest_annual_season
    _tiered_doc(conn, "Shot clock (1954)", 1954, 1954, tier="timeline",
         category="Historical")
    assert latest_annual_season(conn) is None


def test_a_season_the_newest_annual_reissue_covers_is_not_stale(conn):
    from src.db.schema import stale_operational_season
    _tiered_doc(conn, "Official 2025-26 Rulebook", 2025, 2025)
    assert stale_operational_season(conn, 2025) is None


def test_a_season_past_the_newest_annual_reissue_is_stale(conn):
    from src.db.schema import stale_operational_season
    _tiered_doc(conn, "Official 2025-26 Rulebook", 2025, 2025)
    assert stale_operational_season(conn, 2026) == 2025


def test_a_historical_season_is_not_reported_stale(conn):
    # 1995 has no annual document either, but that is ordinary era coverage --
    # not the corpus having aged out underneath a question about now. Reporting
    # it would fire on every historical query.
    from src.db.schema import stale_operational_season
    _tiered_doc(conn, "Official 2025-26 Rulebook", 2025, 2025)
    _tiered_doc(conn, "Draft Probabilities 2003", 2003, 2003, category="Historical")
    assert stale_operational_season(conn, 1995) is None


def test_a_corpus_with_no_annual_reissue_never_reports_staleness(conn):
    from src.db.schema import stale_operational_season
    _tiered_doc(conn, "2023 NBA CBA", 2023, 2029)
    assert stale_operational_season(conn, 2099) is None
