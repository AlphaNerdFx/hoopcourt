"""Check that an answer only cites what it was actually given.

Retrieval correctness and answer correctness are different failures with
different fixes, and the evaluation so far only measures the first. A model can
be handed five correct chunks and still invent a pinpoint: cite Article IX when
the context said Article II, or attribute a real provision to the wrong page.
That failure looks exactly like a good answer, which is what makes it dangerous.

The rule enforced here is stricter than "the citation names a real document".
A citation is valid only if it matches one the model was handed in context.
Citing a genuine provision that was not in the context is still fabrication:
the model produced a pinpoint it could not have read.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from src.model.prompt_templates import citation_locator, format_citation

# Citations are emitted inside square brackets. The tier suffixes this project
# adds are themselves bracketed, so the pattern takes the outermost span and the
# nesting is stripped afterwards.
RE_BRACKETED = re.compile(r"\[([^\[\]]*(?:\[[^\]]*\][^\[\]]*)*)\]")

# Text that is bracketed but is plainly not a citation.
NON_CITATION = re.compile(r"^\s*(?:\d+|sic|\.\.\.|…|see|ibid\.?|id\.?)\s*$", re.I)

# A citation names something. Legal documents are full of bracketed enumeration
# ("5a, i", "b, ii") that an answer quotes verbatim, and counting those as
# fabricated citations put the measured rate at half its real value. Requiring a
# word of four or more letters keeps enumeration out without excusing an
# invented document, which always names one.
RE_HAS_WORD = re.compile(r"[A-Za-z]{4,}")

# ...but that rule alone silently discarded citations to 8 of the 46 indexed
# documents, including the 2023 NBA CBA and every historical CBA. "CBA 1995,
# p. 31" has no word of four letters: "CBA" is three. Such a citation was
# dropped, so an answer citing nothing but page-level CBA references was scored
# as having cited nothing at all. Observed live: an answer carrying three
# bracketed citations reported "1/1 citations verified", and the two it dropped
# were "2024-25 CBA 101, p. 12".
#
# A locator is the other thing that makes a bracket a citation. Enumeration
# quoted out of the text ("5a, i", "(iii)") never carries one.
RE_LOCATOR = re.compile(r"\b(?:pp?\.|part)\s*\d", re.I)

# A bare document name is weaker than a pinpoint but is not invented, and
# verify_citations accepts one. "2023 NBA CBA" has no four-letter word and no
# locator, so it needed its own shape: a word of three or more letters next to a
# four-digit year. Enumeration ("5a, i", "(iii)") carries no year and is still
# excluded.
RE_SHORT_WORD = re.compile(r"[A-Za-z]{3,}")
RE_YEAR = re.compile(r"\b\d{4}\b")


def looks_like_citation(text: str) -> bool:
    """Whether a fragment is a citation *attempt*, regardless of validity.

    Shape only. Deciding whether the attempt is supported or fabricated belongs
    to verify_citations, which is the only place that knows what was supplied.
    Conflating the two is how a fabrication becomes invisible.
    """
    if not text or NON_CITATION.match(text):
        return False
    if RE_HAS_WORD.search(text) or RE_LOCATOR.search(text):
        return True
    return bool(RE_SHORT_WORD.search(text) and RE_YEAR.search(text))

# "p. 1, p. 2, p. 4" and "p. 28-29" are several citations written once. Splitting
# them measures grounding; leaving them fused measures punctuation.
RE_REPEATED_PAGE = re.compile(r",\s*(?=p\.\s*\d)", re.I)
RE_PAGE_RANGE = re.compile(r"\bp\.\s*(\d+)\s*[-\u2013\u2014]\s*(\d+)", re.I)


def normalise(citation: str) -> str:
    """Fold whitespace, spacing around punctuation, and case.

    A real model reformats slightly, and every such difference read as
    fabrication would make the metric useless: false positives would swamp the
    real ones and the number would stop being worth looking at.
    """
    text = re.sub(r"\s+", " ", citation).strip()
    text = re.sub(r"\s+([,;.])", r"\1", text)   # "CBA , Article" -> "CBA, Article"
    text = re.sub(r"([,;.])(?=\S)", r"\1 ", text)  # "p.37" -> "p. 37"
    return text.strip().rstrip(".,;").casefold()


@dataclass
class CitationReport:
    supported: list[str] = field(default_factory=list)
    fabricated: list[str] = field(default_factory=list)
    uncited_claim: bool = False

    @property
    def total(self) -> int:
        return len(self.supported) + len(self.fabricated)

    @property
    def ok(self) -> bool:
        return not self.fabricated and not self.uncited_claim

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "supported": len(self.supported),
            "fabricated": self.fabricated,
            "uncited_claim": self.uncited_claim,
        }


def _expand(citation: str) -> list[str]:
    """Split one bracket that holds several citations into its parts."""
    if m := RE_PAGE_RANGE.search(citation):
        lo, hi = int(m.group(1)), int(m.group(2))
        if 0 < hi - lo <= 20:
            head = citation[:m.start()].rstrip(", ")
            return [f"{head}, p. {n}".lstrip(", ") for n in range(lo, hi + 1)]

    parts = RE_REPEATED_PAGE.split(citation)
    if len(parts) > 1:
        # The split happens before each "p. N", so parts[0] is the document
        # prefix and carries no pinpoint. It is not a citation on its own, and
        # emitting it would count one reference as several.
        prefix = parts[0].rstrip(", ").strip()
        return [f"{prefix}, {tail.strip()}" for tail in parts[1:]]
    return [citation]


def extract_citations(answer: str) -> list[str]:
    """Pull bracketed citations out of an answer, in order of appearance."""
    out: list[str] = []
    for match in RE_BRACKETED.finditer(answer or ""):
        inner = match.group(1).strip()
        if not looks_like_citation(inner):
            continue
        out.extend(_expand(inner))
    return out


# "Sources:" alone on its line, "Sources: CBA 1995, p. 31" with the first
# reference alongside it, and "**Sources:**" in markdown. The prompt asks for a
# final line beginning "Sources:" and the model writes all three.
RE_SOURCES_HEADING = re.compile(r"^\s*[*_#]*\s*sources?\s*[*_]*\s*:\s*(.*)$", re.I)
# A bullet, or an ordinal like "1." / "2)". Not bare digits: a citation
# commonly opens with its year, and a greedy class ate the "2023" off
# "2023 NBA CBA", reporting a fabrication under a name it never used.
RE_LIST_MARKER = re.compile(r"^(?:[-*\u2022]+|\d+[.)])\s*")


def extract_sources_block(answer: str) -> list[str]:
    """Citation attempts listed under a trailing "Sources:" heading.

    Casual Fan mode puts its references here rather than inline, which
    CLAUDE.md sec.6 asks for, and writes them unbracketed.

    Every line of citation shape is returned, **including ones that were never
    supplied**. Filtering to supplied citations here would mean a model listing
    one real source and two invented ones reported as fully grounded, which is
    the sec.2.2 failure this module exists to catch, reached from the opposite
    direction.
    """
    lines = (answer or "").splitlines()
    out: list[str] = []
    start = None
    for i, line in enumerate(lines):
        if match := RE_SOURCES_HEADING.match(line):
            start = i
            first = match.group(1).strip().strip("*_").strip()
            if looks_like_citation(first):
                out.append(first)
            break
    if start is None:
        return []
    for line in lines[start + 1:]:
        candidate = RE_LIST_MARKER.sub("", line.strip()).strip().strip("*_").strip()
        if looks_like_citation(candidate):
            out.append(candidate)
    return out


def verify_citations(
    answer: str,
    context_chunks: Sequence[dict[str, Any]],
    require_citation: bool = True,
) -> CitationReport:
    """Compare every citation in ``answer`` against the chunks supplied as context.

    ``require_citation`` flags a substantive answer that cites nothing at all,
    which is the other half of the grounding rule: a claim with no citation is
    as ungrounded as a claim with a false one.
    """
    # Two tiers of acceptance, and the distinction matters. A full citation must
    # match one that was handed to the model. A bare document name is weaker but
    # not invented, so it is allowed on its own.
    #
    # Matching is exact against these sets, never by substring. A substring test
    # accepts "2023 NBA CBA, Article IX, p. 401" because the document name is
    # inside it, which lets through precisely the failure this exists to catch:
    # a real document carrying a pinpoint the model made up.
    # Both the bare locator and the labelled form are accepted: the tier label
    # is added for the reader, and a model that omits it has still cited
    # correctly.
    allowed_full = {normalise(format_citation(c)) for c in context_chunks}
    allowed_full |= {normalise(citation_locator(c)) for c in context_chunks}
    allowed_docs = {normalise(str(c.get("document", "")))
                    for c in context_chunks if c.get("document")}

    report = CitationReport()
    citations = extract_citations(answer)
    # A trailing "Sources:" list is the other place a citation can appear, and
    # the only place Casual Fan mode puts one. A reference repeated there after
    # being cited inline is one reference written twice, so it is counted once;
    # a reference that appears only in the list is counted.
    seen = {normalise(c) for c in citations}
    for candidate in extract_sources_block(answer):
        if normalise(candidate) not in seen:
            seen.add(normalise(candidate))
            citations.append(candidate)
    for citation in citations:
        key = normalise(citation)
        if key in allowed_full or key in allowed_docs:
            report.supported.append(citation)
        else:
            report.fabricated.append(citation)

    if require_citation and context_chunks:
        substantive = len((answer or "").split()) >= 25
        if substantive and report.total == 0:
            report.uncited_claim = True
    return report
