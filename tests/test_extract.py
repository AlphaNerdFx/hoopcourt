"""Extraction unit tests. Pure-function tests over line lists: fast, offline,
and they do not depend on the (gitignored) corpus being present."""
from __future__ import annotations

import pytest

from src.parser.extract import _clean, _strip_running_header


@pytest.mark.parametrize(
    "head,article,printed",
    [
        ("Article II 37", "II", "37"),          # odd-page CBA running header
        ("36 Article II", "II", "36"),          # even-page CBA running header
        ("29", None, "29"),                     # bare printed page number
        ("30 --~;1", None, "30"),               # OCR debris around a page number
        ("--", None, None),
        ("!_ __", None, None),
    ],
)
def test_running_headers_are_stripped(head, article, printed):
    lines, art, pg = _strip_running_header([head, "real body text follows"])
    assert lines == ["real body text follows"]
    assert art == article
    assert pg == printed


@pytest.mark.parametrize("head", [
    "(b) To the extent reasonably practicable, the terms",
    "Section 7. Maximum Annual Salary.",
    "ARTICLE IV",              # a structural heading, not a running header
    "Article XXXI",            # bare, no page number -> likely a cross-reference
    "four (4) Salary Cap Years in which he was under a Player",
])
def test_body_text_is_never_mistaken_for_a_header(head):
    lines, art, pg = _strip_running_header([head, "next"])
    assert lines == [head, "next"], "stripped real body text"


def test_cross_reference_does_not_hijack_the_article_number():
    """Regression: a case-insensitive ^ARTICLE match relabelled every chunk after
    a line beginning with an in-text cross-reference."""
    from src.parser.extract import RE_BODY_ARTICLE
    assert RE_BODY_ARTICLE.match("ARTICLE VI")
    assert RE_BODY_ARTICLE.match("ARTICLE VI.")
    assert not RE_BODY_ARTICLE.match("Article XXXI challenging the suspension")
    assert not RE_BODY_ARTICLE.match("under Article XXXI, the player may")


def test_section_heading_ignores_decimal_cross_references():
    from src.parser.extract import RE_SECTION
    assert RE_SECTION.match("Section 7. Maximum Annual Salary.").group(1) == "7"
    assert not RE_SECTION.match("section 3.10 of the Plan shall be eliminated")
    assert not RE_SECTION.match("Section 3.10 of the Plan")


def test_running_header_requires_a_page_number():
    """What distinguishes a running header from a body heading is the page
    number beside it. Without this, "ARTICLE IV" was stripped out of the text
    it was supposed to be introducing."""
    stripped, art, pg = _strip_running_header(["Article II 37", "body"])
    assert stripped == ["body"] and art == "II" and pg == "37"

    kept, art, pg = _strip_running_header(["ARTICLE IV", "BENEFITS"])
    assert kept == ["ARTICLE IV", "BENEFITS"] and art is None and pg is None


def test_clean_normalises_quotes_and_soft_hyphenation():
    assert _clean("the player’s “Contract”") == "the player's \"Contract\""
    assert _clean("Compen-\nsation") == "Compensation"
