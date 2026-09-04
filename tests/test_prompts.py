"""Prompt construction tests.

The grounding rules live in prose inside the system prompt, so these assert the
prompt actually carries them -- a silently dropped instruction is invisible until
the model invents a citation.
"""
from __future__ import annotations

import pytest

from src.model.prompt_templates import (
    build_messages,
    format_citation,
    format_context,
)


def flat(text: str) -> str:
    """Collapse the prompt's line wrapping so assertions match phrases, not layout."""
    return " ".join(text.lower().split())

CHUNK = {
    "document": "2023 NBA CBA", "article": "II", "section": "7", "page": 37,
    "text": "The Maximum Annual Salary shall not exceed thirty-five percent (35%).",
    "distance": 0.12,
}


def test_citation_includes_every_available_locator():
    assert format_citation(CHUNK) == "2023 NBA CBA, Article II, Section 7, p. 37"


def test_citation_degrades_when_structure_is_unknown():
    bare = {"document": "NBA Constitution 2024", "page": 14}
    assert format_citation(bare) == "NBA Constitution 2024, p. 14"


def test_context_blocks_carry_exactly_one_identifier():
    """A block used to carry both an id and a citation, and the model merged
    them into "[1, citation: ...]". Correct citations, wrong shape, all scored
    as fabrications. One identifier removes the choice."""
    rendered = format_context([CHUNK])
    assert 'citation="2023 NBA CBA, Article II, Section 7, p. 37"' in rendered
    assert "<context " in rendered and "</context>" in rendered
    assert "id=" not in rendered


@pytest.mark.parametrize("style", ["scholar", "casual"])
def test_both_personas_forbid_answering_beyond_the_context(style):
    system = flat(build_messages("q", [CHUNK], style)[0]["content"])
    assert "only" in system
    assert "era" in system
    assert ("guess" in system
            or "do not reason from general knowledge" in system)


def test_scholar_requires_inline_citations_and_casual_defers_them():
    scholar = flat(build_messages("q", [CHUNK], "scholar")[0]["content"])
    casual = flat(build_messages("q", [CHUNK], "casual")[0]["content"])
    assert "inline" in scholar
    assert "final line" in casual


def test_era_is_stated_in_the_system_prompt():
    system = build_messages("q", [CHUNK], "scholar",
                            route={"target_year": 2024})[0]["content"]
    assert "2024-25" in system


def test_empty_context_instructs_refusal_not_improvisation():
    user = build_messages("What happened in 1952?", [], "scholar")[1]["content"]
    assert "No documents in the index cover the era" in user
    assert "Do not attempt an answer" in user


def test_analogy_is_injected_only_for_casual_and_marked_as_analogy():
    analogy = {"archaic_term": "reserve clause",
               "modern_analogy": "a franchise tag that never expires",
               "simplified_explanation": "the team held rights indefinitely"}
    casual = flat(build_messages("q", [CHUNK], "casual", analogy=analogy)[0]["content"])
    assert "reserve clause" in casual
    assert "analogy rather" in casual
    scholar = build_messages("q", [CHUNK], "scholar", analogy=analogy)[0]["content"]
    assert "franchise tag" not in scholar, "analogies must not enter scholar mode"


def test_messages_are_role_tagged_not_pre_formatted_with_chat_tags():
    """The backend owns its chat template; hand-rolled tags break on swap."""
    messages = build_messages("q", [CHUNK], "scholar")
    assert [m["role"] for m in messages] == ["system", "user"]
    joined = "".join(m["content"] for m in messages)
    for tag in ("<|im_start|>", "<|im_end|>", "<|begin_of_text|>", "<|start_header_id|>"):
        assert tag not in joined
