"""The query that gets embedded is not always the query that was typed.

An explicit year is consumed twice by the naive path: once by the era filter,
which is its job, and again by the embedding, where it matches any passage that
mentions that year. Governing documents state a rule once and then work through
dated examples of it, so the second use ranks the examples above the rule.

Measured before this existed: "What was the maximum annual salary a player could
receive in 2024?" returned five apron and trade worked examples, and Article II
Section 7, the provision stating the rule, did not appear in the top 5 at all.
With the year removed it ranks 2nd, and the full evaluation goes from 41/43 to
43/43 against strictly tightened recall terms.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.router import retrieval_text  # noqa: E402

FILTERED = {"route_action": "strict_season_filter", "target_year": 2024}


@pytest.mark.parametrize("query,expected", [
    ("What was the maximum annual salary a player could receive in 2024?",
     "What was the maximum annual salary a player could receive?"),
    ("What was the salary cap in 1995?", "What was the salary cap?"),
    ("What did the 2011 CBA say about the amnesty clause?",
     "What did the CBA say about the amnesty clause?"),
])
def test_the_year_and_its_preposition_are_removed(query, expected):
    assert retrieval_text(query, FILTERED) == expected


def test_a_query_with_no_year_is_untouched():
    q = "Explain Bird rights."
    assert retrieval_text(q, FILTERED) == q


@pytest.mark.parametrize("action", [
    "default_modern", "historical_keyword_override", "require_season_clarification",
])
def test_only_a_season_filtered_route_is_rewritten(action):
    """If the year was not used for routing it may carry meaning of its own, and
    removing it would silently change the question."""
    q = "What happened to the cap in 1998?"
    assert retrieval_text(q, {"route_action": action}) == q


def test_a_query_that_is_only_a_year_still_retrieves_something():
    """Stripping everything would embed an empty string, which matches nothing
    in particular and would return an arbitrary top-k."""
    assert retrieval_text("2024", FILTERED) == "2024"
    assert retrieval_text("in 2024?", FILTERED) == "in 2024?"


def test_no_dangling_punctuation_or_preposition_survives():
    out = retrieval_text("What was the luxury tax rate in 2015?", FILTERED)
    assert " ?" not in out
    assert not out.rstrip("?").rstrip().endswith(" in")
    assert out.endswith("?")


def test_every_year_goes_when_several_are_present():
    """The era filter resolved one season, so a second year points at documents
    that are not candidates. Leaving it in would rank on a mention of an era
    this query cannot reach."""
    out = retrieval_text("Compare the 1995 and 2005 luxury tax.", FILTERED)
    assert "1995" not in out and "2005" not in out
    assert "luxury tax" in out


def test_content_words_survive():
    out = retrieval_text("What was the maximum annual salary in 2024?", FILTERED)
    for word in ("maximum", "annual", "salary"):
        assert word in out
