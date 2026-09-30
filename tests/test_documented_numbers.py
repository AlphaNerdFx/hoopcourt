"""Guard the numbers the prose states against the numbers the code produces.

Drift in this repo is not uniform, and the pattern is worth stating because it
tells you which claims need a guard and which never did.

Every number that *counts rows in a stored artifact* was accurate when measured
on 2026-09-29: 46 documents, 5,724 chunks, 45 evaluation questions. Those change
only when a reviewed file changes, and the review catches them.

Every number that has to be *computed* had drifted. ``ambiguous_seasons()``
returns 15 seasons; CLAUDE.md sec.5.2, DECISIONS.md D10 and the function's own
docstring all say fourteen. The collected suite is 481 tests; four documents say
460 or 461. Nothing re-derives a computed number when the corpus or the suite
changes, so it is wrong in every copy at once.

This guard runs only where the full index exists, which is a developer machine:
CI builds a judicial-tier-only `ci.db` and legitimately has different counts, so
these tests skip there. That is the correct behaviour -- a guard that fired on
CI's smaller index would be asserting the wrong numbers -- but it means this is
a local check, not a merge gate. It fires exactly where the index is rebuilt,
which is where the counts actually move.

The fix is not "assert every number in the docs". A test count asserted in prose
fails on every PR that adds a test, which manufactures more drift noise than it
removes. Guard the numbers that are load-bearing *and* stable: the ones derived
from the index, which moves only when the corpus manifest moves.
"""
from __future__ import annotations

import pathlib

import pytest

from src.db.connection import get_vector_db_connection
from src.db.schema import ambiguous_seasons

INDEX = pathlib.Path(__file__).resolve().parents[1] / "nba_legal.db"

needs_index = pytest.mark.skipif(
    not INDEX.exists(), reason="index not present (it is gitignored)"
)

# What the prose currently claims, and how to obtain the live value.
# Keep this table small: a claim belongs here only if being wrong would mislead
# someone reading the design docs, not merely be untidy.
CLAIMS = {
    "ambiguous boundary seasons": (
        15,
        lambda conn: len(ambiguous_seasons(conn)),
        "CLAUDE.md sec.5.2, DECISIONS.md D10, src/db/schema.py docstring",
    ),
    "indexed documents": (
        46,
        lambda conn: conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        "CLAUDE.md sec.8, CHANGELOG.md, docs/ai/HANDOVER.md",
    ),
    "indexed chunks": (
        5724,
        lambda conn: conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0],
        "CLAUDE.md sec.8, CHANGELOG.md, docs/architecture/DECISIONS.md",
    ),
}


@needs_index
@pytest.fixture
def index_conn():
    conn = get_vector_db_connection(INDEX)
    yield conn
    conn.close()


@needs_index
@pytest.mark.parametrize("claim", sorted(CLAIMS))
def test_the_documented_number_matches_the_live_one(claim, index_conn):
    documented, derive, stated_in = CLAIMS[claim]
    actual = derive(index_conn)
    # The failure has to name the files, not just the mismatch. This number lives
    # in several documents at once, which is the whole reason the guard exists: a
    # bare `assert 15 == 14` sends the next reader grepping for the copies.
    assert actual == documented, (
        f"documented {claim} is {documented}, live index says {actual}.\n"
        f"Stated in: {stated_in}.\n"
        f"If the corpus was rebuilt this is expected -- update those files and "
        f"the CLAIMS table together. If it was not, something changed the index."
    )


# The evaluation set is a file in this repo, not a derived value, so this check
# needs no index and runs in CI -- unlike the three above. It earns its place
# because the count is quoted in eight documents: adding six routing questions
# for the F1 fix staled every one of them in a single commit. A stored count is
# only safe until the stored thing changes, and then every copy rots at once.
EVAL_QUESTIONS = 51
EVAL_QUESTIONS_STATED_IN = (
    "docs/operations/STATUS.md (the SSOT), README.md, CLAUDE.md sec.8 phase 3, "
    "docs/project/ROADMAP.md, docs/evaluation/GENERATION_MEASUREMENT.md, "
    "docs/sessions/HANDOVER.md"
)


def test_the_documented_evaluation_size_matches_the_question_file():
    import yaml
    path = pathlib.Path(__file__).resolve().parent / "eval" / "questions.yaml"
    actual = len(yaml.safe_load(path.read_text(encoding="utf-8"))["questions"])
    assert actual == EVAL_QUESTIONS, (
        f"documented evaluation size is {EVAL_QUESTIONS}, {path.name} holds {actual}.\n"
        f"Stated in: {EVAL_QUESTIONS_STATED_IN}.\n"
        "Update those and this constant together."
    )
