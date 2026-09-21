"""Colloquial rule names expanded into the language the corpus uses.

The corpus is contract English; users ask in the language of broadcasts. Where
the two share no words *and* no semantic bridge, retrieval fails outright:
measured on the shipped index, "What is the Stepien Rule?" returned five playing
rules about flopping and jump balls, because "Stepien" appears in 0 of 5,724
chunks and the remaining word "Rule" matches a document named "Official 2025-26
Rulebook".
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api.router import (  # noqa: E402
    ALIAS_FILE,
    expand_aliases,
    load_aliases,
    retrieval_text,
)

FILTERED = {"route_action": "strict_season_filter", "target_year": 2024}
MODERN = {"route_action": "default_modern", "target_year": 2025}


def test_the_shipped_alias_file_parses_and_is_complete():
    entries = yaml.safe_load(ALIAS_FILE.read_text(encoding="utf-8"))["aliases"]
    assert entries
    for alias in entries:
        assert alias["term"].strip()
        assert alias["expands_to"].strip()
        # Every entry must carry the measurement that justified it. An alias
        # added on a hunch is a guess about a user's vocabulary sitting in the
        # retrieval path, where it is invisible when wrong.
        assert alias["evidence"].strip(), f"{alias['term']} has no evidence"


def test_a_nickname_is_replaced_not_appended():
    """Leaving the nickname in keeps the noise that caused the failure: "Rule"
    pulling toward the Rulebook is the whole defect."""
    out = expand_aliases("What is the Stepien Rule?")
    assert "Stepien" not in out
    assert "first round" in out


def test_expansion_is_case_insensitive():
    assert "Stepien" not in expand_aliases("what is the stepien rule?")


def test_an_unknown_phrase_is_untouched():
    q = "What is the shot clock reset rule?"
    assert expand_aliases(q) == q


def test_the_longest_matching_term_wins():
    """"Larry Bird rights" must not be consumed by the shorter "Bird rights",
    which would leave a stray "Larry" in the embedded text."""
    out = expand_aliases("Explain Larry Bird rights")
    assert "Bird" not in out
    assert "Larry" not in out


def test_expansion_survives_year_stripping():
    """Both rewrites act on the same text, and a query can need both."""
    out = retrieval_text("What were Bird rights in 2015?", FILTERED)
    assert "2015" not in out
    assert "Qualifying Veteran Free Agent" in out


def test_expansion_applies_on_routes_that_skip_year_stripping():
    """A nickname question usually carries no year at all, so it routes to
    default_modern, which returns early from the year-stripping branch."""
    assert "Qualifying Veteran Free Agent" in retrieval_text("What are Bird rights?", MODERN)


def test_a_missing_alias_file_degrades_rather_than_crashes(tmp_path):
    """Retrieval without aliases is worse, not broken. The index is the thing
    this project cannot run without; a curated convenience file is not."""
    assert load_aliases(tmp_path / "absent.yaml") == []


@pytest.mark.parametrize("term", ["Stepien Rule", "Bird rights"])
def test_every_shipped_term_actually_expands(term):
    assert expand_aliases(term) != term
