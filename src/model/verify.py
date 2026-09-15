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
        if not inner or NON_CITATION.match(inner):
            continue
        if not (RE_HAS_WORD.search(inner) or RE_LOCATOR.search(inner)):
            continue
        out.extend(_expand(inner))
    return out


RE_SOURCES_HEADING = re.compile(r"^\s*sources?\s*:?\s*$", re.I)


def sources_block_citations(answer: str, allowed: set[str]) -> list[str]:
    """Citations listed under a trailing "Sources:" heading, one per line.

    Only lines that match a supplied citation exactly are returned. A line that
    is not one of the citations the model was handed is left alone rather than
    guessed at: this exists to find references the model really did give, not to
    manufacture them out of prose.
    """
    lines = (answer or "").splitlines()
    start = next((i for i, ln in enumerate(lines) if RE_SOURCES_HEADING.match(ln)), None)
    if start is None:
        return []
    out: list[str] = []
    for line in lines[start + 1:]:
        candidate = line.strip().lstrip("-*\u2022 ").strip()
        if not candidate:
            continue
        if normalise(candidate) in allowed:
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
    if not citations:
        # Casual Fan mode puts its references on a trailing "Sources:" line
        # rather than inline, which CLAUDE.md sec.6 asks for explicitly, and in
        # practice the model writes them as a plain list without brackets. Read
        # bracketed-only and every casual answer scores as ungrounded: observed
        # on 5 of 5. Accepting the block is safe because a line is only counted
        # when it matches a supplied citation exactly, so anything that is not a
        # citation cannot become one.
        citations = sources_block_citations(answer, allowed_full | allowed_docs)
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
