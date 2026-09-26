"""Golden test: the exact chunk boundaries a known document produces.

The property tests next door assert that boundaries obey rules. This asserts
what they actually ARE, for one fixed document, so that a change to chunking
shows its consequences as a readable diff rather than as a pass or a fail.

That difference matters here because chunk boundaries are a one-way door: they
are baked into 5,724 chunk hashes and every stored embedding, so re-cutting the
corpus costs about eighty minutes of CPU. A change worth paying that for is a
change worth seeing itemised first.

Recorded per chunk: the page, Article and Section it cites, its length, and the
opening of its text. Not the whole text, which would make the file enormous and
the diff unreadable, and not only a hash, which would tell you that something
moved without telling you what.

    UPDATE_GOLDEN=1 pytest tests/test_golden_chunks.py   # re-record, deliberately
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingest.chunker import chunk_pages  # noqa: E402
from src.parser.extract import ExtractedPage  # noqa: E402

GOLDEN = Path(__file__).parent / "golden_chunks.json"

# Shaped like the real corpus: a running Article heading, numbered Sections,
# a long Section that forces the oversized splitter, an enumerated paragraph,
# and a short line that must be dropped as boilerplate.
_LONG = " ".join(
    f"The Team shall pay the Player an amount equal to {n} percent of the "
    f"Salary Cap in effect for the {1990 + n}-{str(1991 + n)[2:]} Salary Cap Year."
    for n in range(1, 40)
)

PAGES = [
    ExtractedPage(page_num=1, printed_page="1", article=None, section=None, text="\n".join([
        "ARTICLE II",
        "Section 1.",
        "Notwithstanding any other provision of this Agreement, the Maximum Annual "
        "Salary for a Player with fewer than seven (7) Years of Service shall not "
        "exceed twenty-five percent (25%) of the Salary Cap in effect at the time "
        "the Contract is executed.",
        "(a) The foregoing shall apply for each Season of the Contract; and",
        "(b) any excess shall be disregarded for all purposes of this Agreement.",
        "Section 2.",
        "A Team may not trade or exchange its right to select a player in the first "
        "round of consecutive NBA Drafts, and any such trade shall be void.",
        "37",
    ])),
    ExtractedPage(page_num=2, printed_page="2", article=None, section=None, text="\n".join([
        "Section 3.",
        _LONG,
    ])),
    ExtractedPage(page_num=3, printed_page="3", article=None, section=None, text="\n".join([
        "ARTICLE III",
        "Section 1.",
        "The Salary Cap for each Salary Cap Year shall be determined in accordance "
        "with the provisions of this Article, and shall be announced by the League "
        "no later than the first day of the Moratorium Period.",
    ])),
]


def _shape() -> list[dict]:
    out = []
    for chunk in chunk_pages("golden", PAGES):
        text = " ".join(chunk.text.split())
        out.append({
            "page": chunk.page_num,
            "article": chunk.article,
            "section": chunk.section,
            "chars": len(chunk.text),
            "opens": text[:70],
        })
    return out


def test_chunk_boundaries_match_the_recorded_shape():
    """A diff here is a chunking change. Read it before re-recording.

    Each moved line is a citation that now points somewhere else, and every
    stored embedding for the real corpus would need recomputing to match.
    """
    actual = _shape()
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.write_text(json.dumps(actual, indent=2) + "\n", encoding="utf-8")
        return
    assert GOLDEN.exists(), (
        f"{GOLDEN.name} is missing. Re-record it deliberately with "
        f"UPDATE_GOLDEN=1 pytest {Path(__file__).name}")
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert actual == expected, (
        "chunk boundaries moved. If that was the point of your change, re-record "
        "with UPDATE_GOLDEN=1 and put the diff in the pull request: every moved "
        "boundary is a citation that now points elsewhere, and the real index "
        "needs an ~80 minute re-embed to match.")


def test_the_golden_document_actually_exercises_the_interesting_paths():
    """A golden file only protects what its fixture reaches.

    Without this, someone could simplify the fixture until the golden passes
    trivially, and the test would keep reporting success while covering nothing.
    """
    shape = _shape()
    assert len(shape) >= 4, "fixture should produce several chunks"
    assert {c["article"] for c in shape} >= {"II", "III"}, "both Articles reached"
    assert len({c["section"] for c in shape}) >= 3, "several Sections reached"
    assert len({c["page"] for c in shape}) >= 3, "chunks from every page"
    # The oversized splitter must be exercised: Section 3 is long enough to be
    # cut into more than one piece, which is the path with the overlap in it.
    sec3 = [c for c in shape if c["section"] == "3"]
    assert len(sec3) >= 2, "the long Section should split into several chunks"
    # And the short trailing page number must not survive as a chunk.
    assert all(c["chars"] >= 120 for c in shape), "boilerplate floor holds"
