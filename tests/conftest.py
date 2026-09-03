"""Shared fixtures. Deterministic, offline, no model downloads."""
from __future__ import annotations

import hashlib
import random

import pytest
from sqlite_vec import serialize_float32

from src.db.schema import EMBEDDING_DIM, initialize_database

MODERN_AXIS, HISTORICAL_AXIS = 0, 1


def unit_vector(axis: int, jitter: float, rng: random.Random) -> list[float]:
    v = [0.0] * EMBEDDING_DIM
    v[axis] = 1.0
    return [x + rng.uniform(-jitter, jitter) for x in v]


@pytest.fixture
def conn():
    c = initialize_database(":memory:")
    yield c
    c.close()


@pytest.fixture
def adversarial_index(conn):
    """A corpus built to make rule-bleeding *easy*, so the test can prove it doesn't.

    Modern chunks sit almost exactly on the query vector; historical chunks sit
    on an orthogonal axis. Any retrieval path that ranks globally before
    filtering by era will surface modern text for a historical query.
    """
    rng = random.Random(1972)
    docs = [
        ("CBA 1995", "Historical", 1995, 1998, MODERN_AXIS is None),
        ("NBPA CBA 1999", "Historical", 1999, 2004, None),
        ("CBA 2017", "Current Operational", 2017, 2022, None),
        ("2023 NBA CBA", "Current Governing", 2023, 2029, None),
    ]
    doc_ids = {}
    for name, category, start, end, _ in docs:
        cur = conn.execute(
            "INSERT INTO documents (doc_name, category, start_season, end_season, source_url)"
            " VALUES (?,?,?,?,?)",
            (name, category, start, end, f"https://example.invalid/{name}"),
        )
        doc_ids[name] = cur.lastrowid

    historical = {"CBA 1995", "NBPA CBA 1999"}
    for name, doc_id in doc_ids.items():
        axis = HISTORICAL_AXIS if name in historical else MODERN_AXIS
        # Modern chunks hug the query axis far more tightly than historical ones.
        jitter = 0.05 if name in historical else 0.001
        for i in range(50):
            text = f"{name} provision {i}: maximum contract length and cap rules."
            digest = hashlib.sha256(f"{name}:{i}".encode()).hexdigest()
            cur = conn.execute(
                "INSERT INTO document_chunks"
                " (doc_id, chunk_hash, article_num, section_num, page_num,"
                "  is_verified, text_content) VALUES (?,?,?,?,?,1,?)",
                (doc_id, digest, "VII", str(i), i + 1, text),
            )
            conn.execute(
                "INSERT INTO vec_chunks (chunk_id, doc_id, embedding) VALUES (?,?,?)",
                (cur.lastrowid, doc_id, serialize_float32(unit_vector(axis, jitter, rng))),
            )
    conn.commit()
    # Query vector sits on the MODERN axis: modern chunks are the nearest
    # neighbours by construction.
    query = unit_vector(MODERN_AXIS, 0.0, rng)
    return conn, query, doc_ids
