"""Web UI tests.

Written after the page was verified serving and handling all three response
shapes by hand. These lock in the contract between the API and the page, which
is the thing most likely to drift: a field renamed in `main.py` breaks the UI
silently, because a browser reading `undefined` renders nothing rather than
raising.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[1] / "src" / "api" / "static" / "index.html"
HTML = PAGE.read_text(encoding="utf-8")


def test_page_exists_and_is_self_contained():
    """No build step, no CDN, no package manager. A tool people install should
    not need npm to display its own output, and the CDN case also means it would
    break with no network, which is the mode this project is designed for."""
    assert PAGE.exists()
    assert "<script src=" not in HTML, "no external scripts"
    assert "<link" not in HTML or "stylesheet" not in HTML, "no external stylesheets"
    assert "cdn" not in HTML.lower()


@pytest.mark.parametrize("field", [
    "target_year", "route_action", "trigger_keyword",
    "sources", "timeline", "coverage", "answer", "grounding",
])
def test_page_reads_every_top_level_response_field(field):
    assert field in HTML, f"UI never reads {field}"


@pytest.mark.parametrize("field", ["citation", "excerpt", "source_tier", "distance"])
def test_page_renders_each_source_field(field):
    assert field in HTML


def test_page_handles_all_three_failure_shapes():
    """409 ambiguous season, 400 over the token limit, and coverage=false. Each
    is a normal outcome of this design rather than an error, and a UI that only
    handled 200 would present them as breakage."""
    assert "409" in HTML and "options" in HTML
    assert "400" in HTML and "prompt_too_long" in HTML
    assert "covered" in HTML


def test_page_distinguishes_fabricated_from_uncited():
    """Two different failures. An answer citing nothing is not the same as one
    citing something it was never given, and showing the first as '0/0 verified'
    would read like success."""
    assert "uncited_claim" in HTML
    assert "fabricated" in HTML


def test_api_field_names_match_the_page():
    """The real drift guard: if a Pydantic field is renamed, this fails here
    rather than silently blanking part of the page in a browser."""
    from src.api.main import Coverage, Grounding, QueryResponse, Source

    # Fields the page deliberately does not surface, with the reason.
    exempt = {
        "grounded",            # implied by whether sources rendered
        "query",               # the user typed it
        "article", "page",     # already inside `citation`
        "document",            # already inside `citation`
        "season",              # shown via target_year
        "reason",              # conveyed by `message`
        "earliest_season", "latest_season", "nearest_covered_season",  # in `message`
        "checked",             # gates the badge, not displayed
        "supported", "citations",  # rendered via the badge text
    }
    for model in (QueryResponse, Coverage, Grounding, Source):
        for name in model.model_fields:
            if name in exempt:
                continue
            assert name in HTML, f"{model.__name__}.{name} is not read by the UI"


def test_theme_aware():
    """The page is rendered in whatever the viewer's OS is set to."""
    assert "prefers-color-scheme: dark" in HTML


def test_no_horizontal_overflow_at_phone_width():
    assert re.search(r"max-width:\s*\d+px", HTML), "content is width-capped"
    assert "viewport" in HTML
