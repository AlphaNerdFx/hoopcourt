"""Citation verification tests.

Written after the checker was working, against cases proved by hand first. The
two failure directions matter equally: missing a fabricated pinpoint makes the
metric worthless, and flagging harmless reformatting makes it noise nobody reads.
"""
from __future__ import annotations

import pytest

from src.model.verify import extract_citations, normalise, verify_citations

CHUNKS = [
    {"document": "2023 NBA CBA", "article": "II", "section": "7", "page": 37,
     "source_tier": "primary"},
    {"document": "Robertson v. NBA (S.D.N.Y. 1975)", "article": None,
     "section": None, "page": 18, "source_tier": "judicial"},
    {"document": "Reserve clause (1946-1976)", "article": None, "section": None,
     "page": 1, "source_tier": "timeline"},
]


@pytest.mark.parametrize("answer", [
    "The maximum is 35% [2023 NBA CBA, Article II, Section 7, p. 37].",
    "The maximum is 35% [ 2023  NBA CBA , Article II, Section 7, p. 37 ].",
    "The maximum is 35% [2023 NBA CBA, Article II, Section 7, p.37].",
    "The maximum is 35% [2023 nba cba, article ii, section 7, p. 37]",
])
def test_reformatting_is_not_fabrication(answer):
    assert verify_citations(answer, CHUNKS).ok


@pytest.mark.parametrize("answer,invented", [
    ("See [2023 NBA CBA, Article IX, Section 2, p. 401].",
     "2023 NBA CBA, Article IX, Section 2, p. 401"),
    ("See [2023 NBA CBA, Article II, Section 7, p. 999].",
     "2023 NBA CBA, Article II, Section 7, p. 999"),
    ("See [1988 NBA CBA, Article X, p. 12].", "1988 NBA CBA, Article X, p. 12"),
    ("See [Robertson v. NBA (S.D.N.Y. 1975), part 99 [court opinion]].",
     "Robertson v. NBA (S.D.N.Y. 1975), part 99 [court opinion]"),
])
def test_invented_pinpoints_are_caught(answer, invented):
    """A real document carrying a made-up pinpoint is the dangerous case: it
    looks exactly like a good answer."""
    report = verify_citations(answer, CHUNKS)
    assert not report.ok
    assert invented in report.fabricated


def test_bare_document_name_is_weak_but_not_invented():
    assert verify_citations("Defined in the [2023 NBA CBA].", CHUNKS).ok


def test_citing_a_real_document_absent_from_context_is_fabrication():
    """The model can only have read what it was handed. A correct citation to
    something outside the context is still a pinpoint it could not have seen."""
    only_robertson = [CHUNKS[1]]
    report = verify_citations(
        "See [2023 NBA CBA, Article II, Section 7, p. 37].", only_robertson)
    assert not report.ok


def test_substantive_answer_with_no_citation_is_flagged():
    answer = ("The maximum annual salary a player may receive is thirty five "
              "percent of the salary cap, and it applies to every contract "
              "signed after the effective date of the agreement in question.")
    report = verify_citations(answer, CHUNKS)
    assert report.uncited_claim and not report.ok


def test_short_refusal_is_not_required_to_cite():
    assert verify_citations("No document covers that season.", CHUNKS).ok


def test_no_context_means_nothing_to_verify():
    assert verify_citations("I cannot answer that.", []).ok


def test_timeline_and_judicial_tiers_round_trip():
    answer = ("Players were bound indefinitely "
              "[Robertson v. NBA (S.D.N.Y. 1975), part 18 [court opinion]], "
              "see also [Reserve clause (1946-1976) [curated timeline entry]].")
    report = verify_citations(answer, CHUNKS)
    assert report.ok and report.total == 2


def test_brackets_that_are_not_citations_are_ignored():
    answer = "The rule applied [1] and was later amended [see] to add a proviso."
    assert extract_citations(answer) == []


def test_normalise_is_idempotent():
    text = "2023 NBA CBA , Article II, Section 7, p.37"
    assert normalise(normalise(text)) == normalise(text)


# --- extractor behaviour, derived from what a real model actually emitted ---


def test_bracketed_enumeration_is_not_a_citation():
    """Legal text is full of "[5a, i]" style enumeration which an answer quotes
    verbatim. Counting those as fabrications halved the measured citation rate."""
    answer = "Return criteria [5a, i] and [5b, ii] and [b, iv] apply in order."
    assert extract_citations(answer) == []


def test_repeated_pages_in_one_bracket_are_split():
    cites = extract_citations("See [Draft Probabilities 2003, p. 1, p. 2, p. 4].")
    assert cites == ["Draft Probabilities 2003, p. 1",
                     "Draft Probabilities 2003, p. 2",
                     "Draft Probabilities 2003, p. 4"]


def test_page_range_is_expanded():
    cites = extract_citations("See [NBPA Agents Governing Regulations, p. 9-11].")
    assert cites == [f"NBPA Agents Governing Regulations, p. {n}" for n in (9, 10, 11)]


def test_splitting_does_not_excuse_a_fabricated_page():
    chunks = [{"document": "Draft Probabilities 2003", "article": None,
               "section": None, "page": n, "source_tier": "primary"}
              for n in (1, 2, 4)]
    good = verify_citations("See [Draft Probabilities 2003, p. 1, p. 2, p. 4].", chunks)
    assert good.ok and good.total == 3

    bad = verify_citations("See [Draft Probabilities 2003, p. 1, p. 77].", chunks)
    assert not bad.ok
    assert bad.fabricated == ["Draft Probabilities 2003, p. 77"]


def test_absurd_page_range_is_not_expanded():
    """A range of hundreds is not a citation the model read; leaving it intact
    means it fails the check rather than generating a hundred lookups."""
    cites = extract_citations("See [Some Doc, p. 1-500].")
    assert cites == ["Some Doc, p. 1-500"]


# --- Found by reading real answers out of the running UI, not by testing. ---

PAGE_ONLY = [
    {"document": "2024-25 CBA 101", "article": None, "section": None, "page": 12,
     "source_tier": "primary"},
    {"document": "CBA 1995", "article": None, "section": None, "page": 31,
     "source_tier": "primary"},
]


@pytest.mark.parametrize("citation", [
    "2024-25 CBA 101, p. 12",
    "CBA 1995, p. 31",
])
def test_a_citation_whose_document_is_an_acronym_is_not_discarded(citation):
    """The regression. Requiring a word of four or more letters to treat a
    bracket as a citation dropped 8 of the 46 indexed documents, including the
    2023 NBA CBA and every historical CBA: "CBA" is three letters.

    Observed live: an answer carrying three bracketed citations displayed
    "1/1 citations verified", having silently discarded two of them.
    """
    assert extract_citations(f"As stated [{citation}].") == [citation]


@pytest.mark.parametrize("noise", ["5a, i", "b, ii", "(iii)", "4"])
def test_quoted_enumeration_is_still_not_a_citation(noise):
    """Why the four-letter rule existed. Legal text is full of bracketed
    enumeration that an answer quotes verbatim, and counting it as fabrication
    once halved the measured rate. It must stay excluded."""
    assert extract_citations(f"the clause [{noise}] applies") == []


def test_a_trailing_sources_list_counts_as_citing():
    """Casual Fan mode puts references on a final line rather than inline, which
    CLAUDE.md sec.6 asks for, and the model writes them unbracketed. Read
    bracketed-only, every casual answer scored as ungrounded: 5 of 5 observed."""
    answer = (
        "Teams over the second apron lose the ability to trade that first round "
        "pick, and it only unfreezes if they drop back under the level in three "
        "of the next four years, which is a long way back for a contender.\n\n"
        "Sources:\n"
        "- 2024-25 CBA 101, p. 12\n"
        "- CBA 1995, p. 31"
    )
    report = verify_citations(answer, PAGE_ONLY)
    assert report.supported == ["2024-25 CBA 101, p. 12", "CBA 1995, p. 31"]
    assert not report.uncited_claim
    assert report.ok


def test_a_sources_list_cannot_manufacture_a_citation():
    """Only a line matching a supplied citation exactly is counted. Anything
    else is left alone rather than guessed at, so prose under the heading cannot
    become a reference."""
    answer = (
        "The Stepien Rule is named after the owner of a team that traded away "
        "its first round picks for years on end, and the league wrote a rule to "
        "stop anyone repeating it. None of that is in the documents here.\n\n"
        "Sources:\n"
        "- A Document Never Supplied, p. 4\n"
        "- general knowledge"
    )
    report = verify_citations(answer, PAGE_ONLY)
    assert report.supported == []
    assert report.uncited_claim, "an answer resting on nothing must still be flagged"


def test_inline_citations_are_not_double_counted_with_the_list():
    """Legal Scholar mode cites inline and may also summarise at the end.
    Counting both would report more citations than the answer contains."""
    answer = (
        "The minimum is set by the scale [CBA 1995, p. 31] for that year, and "
        "nothing else in the agreement displaces it for a standard contract.\n\n"
        "Sources:\n"
        "- CBA 1995, p. 31"
    )
    report = verify_citations(answer, PAGE_ONLY)
    assert report.total == 1
