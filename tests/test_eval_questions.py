"""Validate the evaluation set itself.

The eval is the requirement, so a malformed question silently measures the wrong
thing. Six temporal-isolation questions originally shipped with no era in the
question text: the router correctly defaulted to the current season, and the
assertions then reported a rule-bleed that had not happened. These checks make
that class of mistake fail loudly at test time instead of looking like a bug in
the router.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

QUESTIONS = yaml.safe_load(
    (Path(__file__).parent / "eval" / "questions.yaml").read_text(encoding="utf-8")
)["questions"]

CATEGORIES = {"temporal_isolation", "grounded_citation", "refusal", "trigger_routing"}
ROUTES = {"strict_season_filter", "default_modern", "historical_keyword_override",
          "require_season_clarification"}
RE_YEAR = re.compile(r"\b(19|20)\d{2}\b")


def by_category(name):
    return [q for q in QUESTIONS if q["category"] == name]


def test_ids_are_unique():
    ids = [q["id"] for q in QUESTIONS]
    assert len(ids) == len(set(ids))


def test_every_category_is_populated():
    for category in CATEGORIES:
        assert by_category(category), f"no questions for {category}"


@pytest.mark.parametrize("q", QUESTIONS, ids=lambda q: q["id"])
def test_question_is_well_formed(q):
    assert q["category"] in CATEGORIES
    assert q["question"].strip().endswith("?")
    assert q["expect_route"] in ROUTES
    if "expect_year" in q:
        assert q["expect_year"] == "CURRENT" or isinstance(q["expect_year"], int)


@pytest.mark.parametrize("q", by_category("temporal_isolation"),
                         ids=lambda q: q["id"])
def test_temporal_isolation_questions_name_their_era(q):
    """Otherwise the router rightly defaults to the current season and the test
    measures the default path instead of era isolation."""
    assert RE_YEAR.search(q["question"]) or q.get("clarified_season"), (
        "question text must contain the era it is testing")


@pytest.mark.parametrize("q", by_category("temporal_isolation"),
                         ids=lambda q: q["id"])
def test_temporal_isolation_questions_declare_a_bleed_check(q):
    assert q.get("forbid_documents"), "an isolation test needs forbidden documents"
    assert not set(q.get("expect_documents", [])) & set(q["forbid_documents"]), (
        "a document cannot be both expected and forbidden")


@pytest.mark.parametrize("q", by_category("refusal"), ids=lambda q: q["id"])
def test_refusal_questions_assert_a_refusal(q):
    """Two valid shapes. An uncovered era returns nothing; a covered era must at
    least not surface text about a rule that did not exist yet."""
    empty = q.get("expect_empty") is True
    absent = bool(q.get("expect_terms_absent"))
    assert empty or absent, "a refusal case must assert emptiness or absent terms"
    assert not (empty and absent), "pick one; they test different things"
    if empty:
        assert "expect_documents" not in q, "a refusal case must not expect sources"


@pytest.mark.parametrize("q", QUESTIONS, ids=lambda q: q["id"])
def test_unqualified_questions_use_the_current_sentinel(q):
    """A hardcoded year on a question with no year in it rots at the next season
    rollover; CURRENT tracks it."""
    if q["expect_route"] == "default_modern" and "expect_year" in q:
        assert q["expect_year"] == "CURRENT", (
            "default_modern expectations must use CURRENT, not a fixed year")
