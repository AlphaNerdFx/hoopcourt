"""Property-based tests: invariants that must hold for inputs nobody wrote.

Every other test in this suite is example-based. Someone thought of a case and
wrote it down, which means the suite is exactly as imaginative as its author was
on the day. These state a property instead and let Hypothesis search for a
counterexample, then shrink it to the smallest one.

Chosen for the three places where an invariant is load-bearing rather than
merely true:

* the chunker, because "no chunk spans two Sections" is what makes a citation
  describe the text it labels (DECISIONS.md, and tests/test_chunker.py covers
  the examples);
* the router, because it must return exactly one era for ANY string a user can
  type, and a crash there is a 500 on a question;
* ambiguous_seasons, because a boundary it misses is a wrong-era answer
  delivered with a real-looking citation.

Deadlines are disabled throughout. Hypothesis times each example and fails on a
slow one, which on a shared CI runner measures the runner rather than the code.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.router import (  # noqa: E402
    RE_YEAR,
    TemporalRouter,
    current_season,
)
from src.db.schema import ambiguous_seasons, initialize_database  # noqa: E402
from src.ingest.chunker import (  # noqa: E402
    MAX_CHARS,
    MIN_CHARS,
    RE_SECTION_HEADING,
    chunk_pages,
)
from src.parser.extract import ExtractedPage  # noqa: E402

ROUTE_ACTIONS = {
    "strict_season_filter",
    "require_season_clarification",
    "historical_keyword_override",
    "default_modern",
}

# A fixed clock, so `default_modern` does not change under the tests in October.
@pytest.fixture(autouse=True)
def _fixed_season(monkeypatch):
    monkeypatch.setenv("NBA_CURRENT_SEASON", "2025")


SLOW_OK = settings(deadline=None, max_examples=150,
                   suppress_health_check=[HealthCheck.function_scoped_fixture])


# ---------------------------------------------------------------------------
# The router: one era for any string, and never an exception
# ---------------------------------------------------------------------------

@given(st.text(max_size=300))
@SLOW_OK
def test_router_always_returns_one_known_route(query):
    """Any string a user can type must resolve to exactly one era.

    The handler has no fallback: a raised exception here is a 500 on a question.
    """
    route = TemporalRouter.resolve_query_route(query, None, {2011, 2023, 2024})
    assert set(route) >= {"route_action", "target_year", "trigger_keyword", "era"}
    assert route["route_action"] in ROUTE_ACTIONS
    assert isinstance(route["target_year"], int)


@given(st.text(max_size=300))
@SLOW_OK
def test_router_is_deterministic(query):
    """Same input, same era. Retrieval is cached against nothing, so a router
    that varied would make an answer depend on when it was asked."""
    amb = {2011, 2023}
    assert (TemporalRouter.resolve_query_route(query, None, amb)
            == TemporalRouter.resolve_query_route(query, None, amb))


@given(st.text(max_size=200), st.integers(min_value=1946, max_value=2029))
@SLOW_OK
def test_clarified_season_always_wins(query, year):
    """Branch A outranks every heuristic below it. A user who has already been
    asked which season they meant must not be second-guessed by a keyword."""
    route = TemporalRouter.resolve_query_route(
        query, f"{year}-{str(year + 1)[2:]}", {2011, 2023, 2024})
    assert route["route_action"] == "strict_season_filter"
    assert route["target_year"] == year


@given(st.integers(min_value=1900, max_value=2099))
@SLOW_OK
def test_an_unambiguous_explicit_year_is_used_verbatim(year):
    """An explicit year is the user stating the answer, so it outranks the
    trigger terms below it. Guarded with an empty ambiguous set so the
    clarification branch cannot intercept."""
    route = TemporalRouter.resolve_query_route(
        f"What was the rule in {year}?", None, set())
    assert route["route_action"] == "strict_season_filter"
    assert route["target_year"] == year


@given(st.text(max_size=200))
@SLOW_OK
def test_a_query_with_no_year_never_takes_the_explicit_year_branch(query):
    """If the year regex does not match, branch B must not fire. This is the
    property that lets the later branches be reasoned about at all."""
    assume(not RE_YEAR.search(query))
    route = TemporalRouter.resolve_query_route(query, None, set())
    assert route["route_action"] != "require_season_clarification"
    if route["route_action"] == "default_modern":
        assert route["target_year"] == current_season()


# ---------------------------------------------------------------------------
# The chunker: a chunk must describe the text it labels
# ---------------------------------------------------------------------------

# Sentence-shaped text, because the oversized splitter breaks on sentence
# boundaries and purely random characters would never exercise that path.
_SENTENCE = st.builds(
    lambda words, n: " ".join(words) + ". ",
    st.lists(st.sampled_from(
        ["the", "Team", "Player", "Salary", "Cap", "Contract", "Season",
         "shall", "pay", "exceed", "percent", "Agreement", "provision"]),
        min_size=3, max_size=12),
    st.integers(),
)


@st.composite
def _pages(draw):
    """Pages shaped like a governing document: Article headings, Sections, prose."""
    n_pages = draw(st.integers(min_value=1, max_value=4))
    pages = []
    for i in range(n_pages):
        lines = []
        if draw(st.booleans()):
            lines.append("ARTICLE " + draw(st.sampled_from(["I", "II", "III", "IV"])))
        for sec in range(draw(st.integers(min_value=0, max_value=3))):
            lines.append(f"Section {sec + 1}.")
            for _ in range(draw(st.integers(min_value=1, max_value=6))):
                lines.append(draw(_SENTENCE))
        for _ in range(draw(st.integers(min_value=0, max_value=4))):
            lines.append(draw(_SENTENCE))
        pages.append(ExtractedPage(page_num=i + 1, printed_page=str(i + 1),
                                   article=None, section=None,
                                   text="\n".join(lines)))
    return pages


@given(_pages())
@SLOW_OK
def test_no_chunk_exceeds_the_hard_cap(pages):
    """MAX_CHARS is not a preference. The context budget is five chunks plus the
    system prompt plus a 1,000-token question inside an 8,192-token window, and
    a chunk over the cap makes truncation arithmetically certain."""
    for chunk in chunk_pages("prop", pages):
        assert len(chunk.text) <= MAX_CHARS, f"{len(chunk.text)} > {MAX_CHARS}"


@given(_pages())
@SLOW_OK
def test_no_chunk_is_below_the_boilerplate_floor(pages):
    """Below MIN_CHARS a chunk is a page header or a stray line, and indexing it
    spends a top-k slot on nothing."""
    for chunk in chunk_pages("prop", pages):
        assert len(chunk.text) >= MIN_CHARS, repr(chunk.text)


@given(_pages())
@SLOW_OK
def test_a_chunk_carries_at_most_one_section_heading_and_it_comes_first(pages):
    """The citation guarantee, stated as a property.

    A chunk that begins inside Section 4 and ends inside Section 6 must claim
    one of them, and whichever it claims, part of its text contradicts the
    citation. The chunker flushes on a Section heading so this cannot happen;
    this asserts the consequence rather than the mechanism.
    """
    for chunk in chunk_pages("prop", pages):
        lines = chunk.text.split("\n")
        heads = [i for i, ln in enumerate(lines)
                 if RE_SECTION_HEADING.match(ln.strip())]
        assert len(heads) <= 1, f"{len(heads)} section headings in one chunk"
        if heads:
            assert heads[0] == 0, "a section heading that is not the first line"


@given(_pages())
@SLOW_OK
def test_every_chunk_cites_a_page_that_exists(pages):
    """A citation naming a page the document does not have is worse than none."""
    valid = {p.page_num for p in pages}
    for chunk in chunk_pages("prop", pages):
        assert chunk.page_num in valid


@given(_pages())
@SLOW_OK
def test_chunking_is_deterministic(pages):
    """chunk_hash is UNIQUE in the schema and is how a rebuild avoids duplicating
    work, so the same input must produce the same hashes."""
    first = [c.chunk_hash for c in chunk_pages("prop", pages)]
    second = [c.chunk_hash for c in chunk_pages("prop", pages)]
    assert first == second


# ---------------------------------------------------------------------------
# ambiguous_seasons: a boundary it misses is a wrong-era answer
# ---------------------------------------------------------------------------

def _conn_with(windows):
    conn = initialize_database(":memory:")
    for i, (lo, hi) in enumerate(windows):
        conn.execute(
            "INSERT INTO documents (doc_name, category, start_season, end_season,"
            " source_url, source_tier) VALUES (?,?,?,?,?,?)",
            (f"d{i}", "Historical", lo, hi, "https://example.invalid", "primary"))
    conn.commit()
    return conn


@given(st.integers(min_value=1946, max_value=2020),
       st.integers(min_value=0, max_value=30))
@SLOW_OK
def test_one_document_is_ambiguous_exactly_at_its_two_edges(start, length):
    """Closed form, independent of the implementation.

    With a single document covering [s, e], the seasons keyed y-1 and y differ
    exactly when y is s or e+1. Deriving the expected answer a different way
    from the code is what stops this being a restatement of the implementation.
    """
    end = start + length
    got = ambiguous_seasons(_conn_with([(start, end)]))
    assert got == {start, end + 1}


@given(st.lists(st.tuples(st.integers(min_value=1946, max_value=2020),
                          st.integers(min_value=0, max_value=20)),
                min_size=1, max_size=6))
@SLOW_OK
def test_every_boundary_is_a_year_some_window_starts_or_ends_at(windows):
    """No year is ambiguous unless a document window begins or ends beside it.

    An extra boundary would be a needless 409; this asserts the set cannot
    invent one.
    """
    spans = [(s, s + n) for s, n in windows]
    got = ambiguous_seasons(_conn_with(spans))
    edges = {s for s, _ in spans} | {e + 1 for _, e in spans}
    assert got <= edges


@given(st.lists(st.tuples(st.integers(min_value=1946, max_value=2020),
                          st.integers(min_value=0, max_value=20)),
                min_size=1, max_size=6))
@SLOW_OK
def test_timeline_documents_never_create_a_boundary(windows):
    """Ambiguity is derived from primary-tier windows only, deliberately:
    counting the curated entries would make almost every historical year
    ambiguous and turn a precision feature into a wall of prompts."""
    spans = [(s, s + n) for s, n in windows]
    conn = initialize_database(":memory:")
    for i, (lo, hi) in enumerate(spans):
        conn.execute(
            "INSERT INTO documents (doc_name, category, start_season, end_season,"
            " source_url, source_tier) VALUES (?,?,?,?,?,?)",
            (f"t{i}", "Historical", lo, hi, "https://example.invalid", "timeline"))
    conn.commit()
    assert ambiguous_seasons(conn) == set()
