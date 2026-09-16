"""The evaluation runner must be able to measure both shipped answer styles.

For most of this project's life `run_eval.py` passed `style="scholar"` and
nothing else. Casual Fan mode shipped the whole time, so every reported figure
for "citation validity" described one of the two styles while being read as
describing the system. That is how a mode which could never score a single
citation -- it lists sources in a trailing block, and the verifier read only
bracketed text -- survived every measurement that was published.

The lesson these tests pin: what is not exercised is not measured, and a green
suite says nothing whatever about it.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
from sqlite_vec import serialize_float32

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.schema import EMBEDDING_DIM, initialize_database  # noqa: E402
from tests.eval import run_eval  # noqa: E402


class StubEmbedder:
    def embed_query(self, text: str):
        v = [0.0] * EMBEDDING_DIM
        v[0] = 1.0
        return v


class RecordingGenerator:
    """Records the style it was asked for; answers with a citation it was given."""

    name = "recording"

    def __init__(self):
        self.styles: list[str] = []

    def generate(self, query, chunks, route, style="scholar", analogy=None):
        self.styles.append(style)
        from src.model.prompt_templates import citation_locator

        return ("An answer long enough to be judged substantive by the citation "
                f"checker, resting on [{citation_locator(chunks[0])}] and nothing "
                "else at all.")


@pytest.fixture
def indexed_db(tmp_path):
    """A one-document index covering the season the probe question asks about."""
    db = tmp_path / "style.db"
    conn = initialize_database(str(db))
    cur = conn.execute(
        "INSERT INTO documents (doc_name, category, start_season, end_season,"
        " source_url) VALUES ('CBA 2011','Historical',2011,2016,'https://example.invalid')")
    doc_id = cur.lastrowid
    for i in range(3):
        v = [0.0] * EMBEDDING_DIM
        v[0] = 1.0
        c = conn.execute(
            "INSERT INTO document_chunks (doc_id, chunk_hash, article_num,"
            " section_num, page_num, is_verified, text_content)"
            " VALUES (?,?,'VII','2',?,1,?)",
            (doc_id, hashlib.sha256(f"s{i}".encode()).hexdigest(), i + 1,
             f"Provision {i} concerning the Salary Cap for the Season."))
        conn.execute("INSERT INTO vec_chunks (chunk_id, doc_id, embedding)"
                     " VALUES (?,?,?)", (c.lastrowid, doc_id, serialize_float32(v)))
    conn.commit()
    conn.close()
    return str(db)


@pytest.fixture
def question():
    return [{
        "id": "style-probe", "category": "grounded_citation",
        "question": "What was the Salary Cap in 2015?",
        "expect_terms_any": ["Salary"],
    }]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No 440MB download inside a unit test."""
    monkeypatch.setattr(run_eval, "Embedder", StubEmbedder)


@pytest.mark.parametrize("style", ["scholar", "casual"])
def test_the_requested_style_reaches_the_generator(indexed_db, question, style):
    gen = RecordingGenerator()
    run_eval.evaluate(indexed_db, question, verbose=False, generator=gen, style=style)
    assert gen.styles, "generation never ran; the probe retrieved nothing"
    assert set(gen.styles) == {style}


def test_scholar_remains_the_default(indexed_db, question):
    """Changing the default would silently change what every past number means."""
    gen = RecordingGenerator()
    run_eval.evaluate(indexed_db, question, verbose=False, generator=gen)
    assert set(gen.styles) == {"scholar"}
