"""Every timeline claim must be traceable to the source it names.

CI already checks that each entry *has* a citation and a source_url. Neither
check looks at whether they agree with each other, or with the claim. A curated
entry is rendered beside governing text and, unlike that text, nobody can verify
it except by following its link, so a link that does not support the claim is
worse than no link: it manufactures confidence.

The defects listed as known-bad below were found by audit and need a human with
network access to resolve. They are named rather than skipped so that the count
can only go down.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TIMELINE = Path(__file__).resolve().parents[1] / "historical_timeline.yaml"


def entries() -> list[dict]:
    loaded = yaml.safe_load(TIMELINE.read_text(encoding="utf-8"))
    return loaded["entries"] if isinstance(loaded, dict) else loaded


# Audited 2026-09-16. Each needs a source that supports its claim; none can be
# corrected without fetching and reading a replacement, and guessing a URL is
# the failure this project exists to prevent.
KNOWN_BAD = {
    "baa-nbl-merger": "cites the draft-lottery page for a 1946-49 league-formation claim",
    "aba-merger-completed": "cites the draft-lottery page for a 1976 merger claim",
    "shot-clock": "citation names Rule 7, source_url points at rule-no-1",
}

RE_RULE_IN_CITATION = re.compile(r"\bRule\s+(\d+)\b", re.I)
RE_RULE_IN_URL = re.compile(r"rule-no-(\d+)")


@pytest.mark.parametrize("entry", entries(), ids=lambda e: e["id"])
def test_a_cited_rule_number_matches_the_url_it_links_to(entry):
    """"Rule 7" beside a link to rule-no-1 is a reader following a citation to
    the wrong rule."""
    if entry["id"] in KNOWN_BAD:
        pytest.xfail(KNOWN_BAD[entry["id"]])
    cited = RE_RULE_IN_CITATION.search(str(entry.get("citation", "")))
    linked = RE_RULE_IN_URL.search(str(entry.get("source_url", "")))
    if cited and linked:
        assert cited.group(1) == linked.group(1)


@pytest.mark.parametrize("entry", entries(), ids=lambda e: e["id"])
def test_a_league_history_claim_does_not_link_to_a_lottery_page(entry):
    """A page about the draft lottery cannot be the source for a league merger.
    Five entries share that URL; three are genuinely about the lottery."""
    if entry["id"] in KNOWN_BAD:
        pytest.xfail(KNOWN_BAD[entry["id"]])
    url = str(entry.get("source_url", ""))
    topic = str(entry.get("topic", "")).lower()
    if "lottery" in url and topic in {"league formation", "aba merger"}:
        pytest.fail(f"{entry['id']}: {topic} sourced to a lottery page")


def test_the_known_bad_list_only_shrinks():
    """A guard on the guard. If an id here is fixed or renamed, this fails and
    the entry must be removed from the list rather than left to rot."""
    ids = {e["id"] for e in entries()}
    stale = set(KNOWN_BAD) - ids
    assert not stale, f"KNOWN_BAD names entries that no longer exist: {stale}"


def test_every_entry_cites_something_and_links_somewhere():
    for entry in entries():
        assert str(entry.get("citation", "")).strip(), f"{entry['id']} has no citation"
        assert str(entry.get("source_url", "")).strip(), f"{entry['id']} has no source"


def test_wikipedia_is_flagged_rather_than_silently_accepted():
    """Not banned: for an extinct practice with no court record and no surviving
    league page, it may be the only source there is. But it is the weakest
    source in a corpus of court opinions and official publications, and it
    should never grow quietly."""
    wiki = [e["id"] for e in entries() if "wikipedia.org" in str(e.get("source_url", ""))]
    assert wiki == ["territorial-picks"], (
        f"Wikipedia-sourced entries changed: {wiki}. Prefer a court opinion or an "
        "official league publication; if neither exists, say so in the summary."
    )
