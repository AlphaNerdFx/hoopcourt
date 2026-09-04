"""Prompt construction for the two answer personas.

Salvaged from BUILD_SEQUENCE.md:1665-1728, with the hand-rolled chat tags removed.
The spec wraps every prompt in `<|im_start|>` / `<|im_end|>` and calls them "Llama-3
Instruct message tags" -- they are actually ChatML, which is Qwen's format, not
Llama-3's (`<|begin_of_text|><|start_header_id|>`). Hand-formatting either one
means the string silently breaks whenever the backend changes.

So this module emits role-tagged messages and lets each backend apply its own
chat template: llama-cpp reads it from the GGUF metadata, the Anthropic client
uses its own. Structural isolation of the two personas -- the part of the spec's
design that was right -- is preserved.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

SCHOLAR_SYSTEM = """\
You are a legal scholar specialising in NBA governing documents.

Rules you must follow exactly:
1. Answer ONLY from the provided <context> blocks. They are the complete record
   available to you.
2. Cite every factual claim inline. A citation is square brackets containing the
   citation attribute of the block you used, copied exactly and alone:
       correct:   [2023 NBA CBA, Article II, Section 7, p. 37]
       wrong:     [1], [block 1], [1, citation: 2023 NBA CBA ...], [see above]
   Never cite a source that is not among the blocks below, and never cite a case
   or page mentioned inside a block's text. Only the block's own citation.
3. If the context does not contain the answer, say so plainly and stop. Do not
   reason from general knowledge of the NBA, and do not fill gaps with what is
   typical or likely.
4. The context has been filtered to the era the question is about. Do not
   introduce rules from any other era, even if you believe they are relevant.
5. Quote the operative language where precision matters.

Tone: precise and formal."""

CASUAL_SYSTEM = """\
You are a sharp basketball writer explaining league rules to a smart fan.

Rules you must follow exactly:
1. Explain ONLY what the provided <context> blocks support. They are the complete
   record available to you.
2. If the context does not contain the answer, say so plainly. Never guess, and
   never fall back on general NBA knowledge.
3. The context has been filtered to the era in question. Do not mix in rules from
   other eras.
4. Put your citations on a final line beginning "Sources:". Each one is the
   citation attribute of a block you used, copied exactly, in square brackets.
   Never cite anything that is not among the blocks below.

Tone: conversational and direct. Explain jargon in plain language. No hype."""

ANALOGY_TEMPLATE = """\

The question involves "{archaic_term}", a concept that no longer exists. A useful
modern comparison is {modern_analogy}: {simplified_explanation}
Use this comparison to orient the reader, but make clear it is an analogy rather
than something the documents say."""

NO_CONTEXT_INSTRUCTION = """\
No documents in the index cover the era this question is about. Tell the user
that directly and say which eras you cannot speak to. Do not attempt an answer."""


TIER_LABELS = {"judicial": "court opinion", "timeline": "curated timeline entry"}


def citation_locator(chunk: dict[str, Any]) -> str:
    """The citation without its tier label: the part that identifies a passage.

    Split out because the label is something this project appends for the
    reader, not part of the reference. A model handed
    "Robertson v. NBA (1975), part 29 [court opinion]" will reasonably cite
    "Robertson v. NBA (1975), part 29", and scoring that as a fabrication would
    make the metric measure formatting rather than grounding.
    """
    tier = chunk.get("source_tier") or "primary"

    if tier == "judicial":
        parts = [chunk["document"]]
        if chunk.get("page"):
            parts.append(f"part {chunk['page']}")
        return ", ".join(parts)

    if tier == "timeline":
        return str(chunk["document"])

    parts = [chunk["document"]]
    if chunk.get("article"):
        parts.append(f"Article {chunk['article']}")
    if chunk.get("section"):
        parts.append(f"Section {chunk['section']}")
    parts.append(f"p. {chunk['page']}")
    return ", ".join(parts)


def format_citation(chunk: dict[str, Any]) -> str:
    """Render a citation that states what kind of authority it carries.

    Pre-1995 coverage rests on court opinions and curated entries, not on any
    surviving CBA text. Rendered in the governing-document shape those look
    identical to the rule itself, so the tier is made explicit here -- and a
    court opinion gets "part N" rather than "p. N", because its blocks are an
    artefact of how the plain text was split and are not reporter pages.
    """
    locator = citation_locator(chunk)
    label = TIER_LABELS.get(chunk.get("source_tier") or "primary")
    return f"{locator} [{label}]" if label else locator


def format_context(chunks: Sequence[dict[str, Any]]) -> str:
    """Render retrieved chunks as XML blocks, each carrying its own citation.

    Deliberately no ``id`` attribute. When blocks carried both an id and a
    citation, the model merged them and emitted "[2, citation: Robertson v. NBA
    ..., part 1]" instead of "[Robertson v. NBA ..., part 1]". The citations
    themselves were right; only the shape was wrong, and every one of them was
    then scored as a fabrication. One identifier per block removes the choice.
    """
    return "\n\n".join(
        f'<context citation="{citation_locator(chunk)}"'
        f' source_type="{chunk.get("source_tier") or "primary"}">\n'
        f"{chunk['text'].strip()}\n"
        f"</context>"
        for chunk in chunks
    )


def build_messages(
    query: str,
    chunks: Sequence[dict[str, Any]],
    style: str = "scholar",
    analogy: dict[str, Any] | None = None,
    route: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Build the role-tagged message list for either backend."""
    system = SCHOLAR_SYSTEM if style == "scholar" else CASUAL_SYSTEM

    if analogy and style == "casual":
        system += ANALOGY_TEMPLATE.format(
            archaic_term=analogy["archaic_term"],
            modern_analogy=analogy["modern_analogy"],
            simplified_explanation=analogy["simplified_explanation"],
        )

    if route and route.get("target_year"):
        system += (
            f"\n\nThe context below is drawn exclusively from documents governing "
            f"the {route['target_year']}-{str(route['target_year'] + 1)[2:]} season."
        )

    if not chunks:
        user = f"{NO_CONTEXT_INSTRUCTION}\n\nQuestion: {query}"
    else:
        user = f"{format_context(chunks)}\n\nQuestion: {query}"

    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]
