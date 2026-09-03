"""API contract tests.

These cover the assembly BUILD_SEQUENCE.md never wrote: the app, its routes, and
the three behaviours the PRD specifies as acceptance criteria -- the token gate,
the ambiguous-season clarification, and era-isolated sources.

A stub embedder keeps the suite offline and fast; retrieval correctness is
covered against real vectors in test_vector_retrieval.py.
"""
from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlite_vec import serialize_float32

from src.db.schema import EMBEDDING_DIM, initialize_database


class StubEmbedder:
    """Deterministic unit vectors; axis 0 = modern, axis 1 = historical."""

    def embed_query(self, text: str):
        v = [0.0] * EMBEDDING_DIM
        v[0] = 1.0
        return v


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "api.db"
    conn = initialize_database(str(db))
    # CBA 2011 spans to 2022 here so the fixture has continuous pre-2023 cover;
    # the real windows live in corpus_manifest.yaml.
    docs = [("2023 NBA CBA", "Current Governing", 2023, 2029, 0),
            ("CBA 2011", "Historical", 2011, 2022, 1)]
    for name, cat, s, e, axis in docs:
        cur = conn.execute(
            "INSERT INTO documents (doc_name, category, start_season, end_season,"
            " source_url) VALUES (?,?,?,?,'https://example.invalid')", (name, cat, s, e))
        doc_id = cur.lastrowid
        for i in range(5):
            vec = [0.0] * EMBEDDING_DIM
            vec[axis] = 1.0
            c = conn.execute(
                "INSERT INTO document_chunks (doc_id, chunk_hash, article_num,"
                " section_num, page_num, is_verified, text_content)"
                " VALUES (?,?,'VII','3',?,1,?)",
                (doc_id, hashlib.sha256(f"{name}{i}".encode()).hexdigest(), i + 1,
                 f"{name} provision {i} concerning the Salary Cap."))
            conn.execute("INSERT INTO vec_chunks (chunk_id, doc_id, embedding)"
                         " VALUES (?,?,?)", (c.lastrowid, doc_id, serialize_float32(vec)))
    conn.commit()
    conn.close()

    monkeypatch.setenv("NBA_LEGAL_DB", str(db))
    import importlib

    from src.api import main as main_mod
    importlib.reload(main_mod)
    monkeypatch.setattr(main_mod, "DB_PATH", str(db))
    # Substitute before the lifespan runs: otherwise startup loads the real
    # 440MB embedding model and every test pays for it.
    monkeypatch.setattr(main_mod, "Embedder", StubEmbedder)
    with TestClient(main_mod.app) as c:
        yield c


def test_health_reports_a_consistent_index(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["index"]["vectors"] == body["index"]["verified_chunks"] == 10
    assert body["index"]["orphaned_vectors"] == 0


def test_oversized_prompt_is_rejected_before_retrieval(client):
    r = client.post("/query", json={"query": "cap rules " * 900})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert detail["error"] == "prompt_too_long"
    assert detail["counted_tokens"] > detail["limit"] == 1000
    assert "1,000 tokens" in detail["message"]


def test_ambiguous_year_returns_409_with_both_options(client):
    """PRD User Story 1. 409 rather than the spec's HTTP 300, which is a
    redirect status that clients and proxies act on."""
    r = client.post("/query", json={"query": "luxury tax penalties in 2023?"})
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "season_ambiguous"
    assert body["options"] == ["2022-23", "2023-24"]
    assert body["resend_with"] == "clarified_season"


def test_clarified_season_resolves_and_returns_sources(client):
    r = client.post("/query", json={"query": "luxury tax penalties in 2023?",
                                    "clarified_season": "2022-23"})
    assert r.status_code == 200
    body = r.json()
    assert body["route_action"] == "strict_season_filter"
    assert body["target_year"] == 2022
    assert {s["document"] for s in body["sources"]} == {"CBA 2011"}


def test_historical_query_sources_contain_no_modern_document(client):
    r = client.post("/query", json={"query": "What was the salary cap in 2013?"})
    body = r.json()
    assert body["sources"]
    assert all(s["document"] == "CBA 2011" for s in body["sources"])
    assert body["grounded"] is True


def test_sources_carry_a_resolvable_citation(client):
    r = client.post("/query", json={"query": "What was the salary cap in 2013?"})
    src = r.json()["sources"][0]
    assert src["citation"].startswith("CBA 2011, Article VII, Section 3, p.")
    assert src["page"] >= 1


def test_uncovered_era_is_ungrounded_rather_than_answered(client):
    r = client.post("/query", json={"query": "What was the salary cap in 1952?"})
    body = r.json()
    assert body["sources"] == []
    assert body["grounded"] is False
    assert body["answer"] is None


def test_invalid_clarified_season_is_rejected_by_schema(client):
    assert client.post("/query", json={"query": "tax in 2023?",
                                       "clarified_season": "nonsense"}).status_code == 422


def test_empty_query_is_rejected(client):
    assert client.post("/query", json={"query": ""}).status_code == 422


def test_health_reports_the_corpus_derived_ambiguous_years(client):
    """The fixture has CBA 2011 (2011-2022) and the 2023 CBA (2023-2029), so the
    boundaries are 2011 and 2023 -- derived, not hardcoded."""
    body = client.get("/health").json()
    assert 2023 in body["ambiguous_years"]
    assert 2011 in body["ambiguous_years"], (
        "a non-2023 document boundary must also be flagged")
    assert 2015 not in body["ambiguous_years"], "interior years are unambiguous"


def test_non_2023_boundary_year_asks_for_clarification(client):
    """Regression for D10: only 2023 used to be guarded, so this returned a
    confident answer for whichever season happened to match the window."""
    r = client.post("/query", json={"query": "What was the luxury tax in 2011?"})
    assert r.status_code == 409, "a boundary year must not be answered silently"
    body = r.json()
    assert body["year"] == 2011
    assert body["options"] == ["2010-11", "2011-12"]


def test_interior_year_is_answered_without_a_clarification_round_trip(client):
    r = client.post("/query", json={"query": "What was the luxury tax in 2015?"})
    assert r.status_code == 200
    assert r.json()["target_year"] == 2015
