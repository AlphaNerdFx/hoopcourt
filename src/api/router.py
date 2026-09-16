"""Token gating and contextual temporal routing.

Salvaged from BUILD_SEQUENCE.md:1187-1284 (the *contextual-proximity* Step 5, not
the naive keyword variant at line 837, which routes any mention of "coin flip" to
1984 including a modern playoff-seeding tiebreak).

Three corrections to the salvaged version:

* Multi-word context keys ("oscar robertson", "first pick") never matched: the
  original compared each key against single tokens only, so those entries were
  dead weight and their triggers under-fired.
* Substring matching (``if key in word``) let "pick" match "picket" and "aba"
  match "abandon". Matching is now on token boundaries, with an explicit prefix
  list for genuine morphology ("draft" -> "drafted", "drafting").
* Token counting no longer uses tiktoken. ``cl100k_base`` is OpenAI's BPE and
  matches neither backend; the limit is enforced with the tokenizer of whichever
  model will actually receive the prompt.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

MAX_PROMPT_TOKENS = 1000


def current_season(today: _dt.date | None = None) -> int:
    """The season year now in progress; NBA seasons start in October.

    A question with no year in it means "the rules as they stand today", and that
    must resolve to the CURRENT season rather than to the year the standing CBA
    was signed. Pinning the default at 2023 quietly made every annually-reissued
    document unreachable without an explicit year: the 2025-26 Rulebook, Officials
    Guide and Concussion Policy each govern 2025 only, and 2023 is not in that
    window, so "what are the shot clock rules?" could only ever return CBA text.
    Caught by tests/eval/questions.yaml.
    """
    if override := os.environ.get("NBA_CURRENT_SEASON"):
        return int(override)
    today = today or _dt.date.today()
    return today.year if today.month >= 10 else today.year - 1


DEFAULT_MODERN_SEASON = current_season()
PROXIMITY_WINDOW = 6  # words between trigger and context cue

# Fallback when no corpus-derived set is supplied (pure/offline use). The live
# API computes the real set from the index via db.schema.ambiguous_seasons() --
# 2023 is merely the most famous boundary, not the only one.
AMBIGUOUS_YEARS = {2023}

RE_WORD = re.compile(r"[a-z0-9'\-]+")
RE_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")

# Punctuation left stranded once a year is removed, and the preposition that
# introduced it: "... receive in 2024?" should become "... receive?", not
# "... receive in ?", which embeds the dangling "in" as content.
RE_DANGLING_PREP = re.compile(r"\b(?:in|during|for|of|from|since|by)\s*(?=[?.,;:]|$)",
                              re.IGNORECASE)
RE_SPACE_BEFORE_PUNCT = re.compile(r"\s+([?.,;:])")


ALIAS_FILE = Path(__file__).resolve().parents[2] / "concept_aliases.yaml"
_ALIASES: list[tuple[str, str]] | None = None


def load_aliases(path: Path | None = None) -> list[tuple[str, str]]:
    """Colloquial rule names paired with the language the documents use.

    Cached at module level: the file is small and constant, and re-reading it per
    request would put a disk read on the hot path of every query.

    Longest term first, so "Larry Bird rights" is matched before "Bird rights"
    and the shorter form cannot consume the longer one's prefix.
    """
    global _ALIASES
    if _ALIASES is not None and path is None:
        return _ALIASES
    target = path or ALIAS_FILE
    if not target.exists():
        # An absent file means no expansions, not a crash. Retrieval without
        # aliases is degraded, not broken, and the index is the thing this
        # project cannot run without.
        return [] if path else (_ALIASES := [])
    import yaml

    entries = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    pairs: list[tuple[str, str]] = []
    for alias in entries.get("aliases", []):
        expansion = " ".join(str(alias["expands_to"]).split())
        for term in [alias["term"], *alias.get("also", [])]:
            pairs.append((term, expansion))
    pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
    if path is None:
        _ALIASES = pairs
    return pairs


def expand_aliases(text: str, aliases: list[tuple[str, str]] | None = None) -> str:
    """Replace a colloquial rule name with the wording the corpus uses.

    Substitution rather than addition. Leaving the nickname in keeps the noise
    that caused the failure: "Stepien Rule" retrieved the Official Rulebook
    because "Rule" matches a document of that name, and appending the expansion
    would have left "Rule" pulling in the same direction.

    Embedding only. `build_messages` receives the user's own question, because
    rewriting someone's words and then answering the rewrite is a different
    answer from the one they asked for.
    """
    for term, expansion in (load_aliases() if aliases is None else aliases):
        pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        text = pattern.sub(expansion, text)
    return text


def retrieval_text(query: str, route: dict) -> str:
    """The text to embed, which is not always the text the user typed.

    An explicit year is consumed twice by the naive path: once by the era
    filter, which is what it is for, and again by the embedding, where it
    matches any passage that happens to mention that year. The second use is
    actively harmful, because a governing document states a rule once and then
    works through dated examples of it.

    Measured on "What was the maximum annual salary a player could receive in
    2024?": with the year, the top 5 are apron and trade worked examples that
    mention the 2024-25 Salary Cap Year, and Article II Section 7, the provision
    that actually states the rule, does not appear at all. With the year
    removed, that provision ranks 2nd. The era filter has already restricted the
    candidates to documents governing 2024, so nothing about the temporal scope
    is lost.

    Only applied when the route actually filtered on a season. If the year was
    never used for routing, it may carry meaning that belongs in the query.
    """
    if route.get("route_action") != "strict_season_filter":
        return expand_aliases(query)
    stripped = RE_YEAR.sub(" ", query)
    if stripped == query:
        return expand_aliases(query)
    stripped = RE_SPACE_BEFORE_PUNCT.sub(r"\1", RE_DANGLING_PREP.sub("", stripped))
    stripped = RE_SPACE_BEFORE_PUNCT.sub(r"\1", " ".join(stripped.split()))
    # A question that was nothing but a year still has to retrieve something.
    return expand_aliases(stripped if len(stripped.split()) >= 3 else query)

# Terms whose historical meaning must override the modern default.
#
# Most carry a modern sense too, so they only fire near a context cue -- "coin
# flip" appears in a playoff-seeding tiebreak, and "territorial" appears in the
# antitrust phrase "territorial division of markets" inside Robertson itself.
#
# A few are extinct: the term has no current meaning, so requiring a cue only
# suppresses correct routing. Measured against the index, "reserve clause" occurs
# 0 times in documents governing 1995 or later and 24 times before, so
# `requires_context: False`. Re-run that count before adding another.
TRIGGER_CONTEXTS: dict[str, dict[str, Any]] = {
    "coin flip": {
        "era": "pre_1985_lottery",
        "context_keys": ["draft", "lottery", "1985", "worst", "selection",
                         "first pick", "territorial", "tiebreak"],
        "base_year": 1984,
    },
    "aba": {
        "era": "1976_merger",
        "context_keys": ["merger", "merged", "dispersal", "spirits", "1976",
                         "nets", "spurs", "nuggets", "pacers", "absorbed"],
        "base_year": 1976,
    },
    "reserve clause": {
        "era": "pre_1976_free_agency",
        "context_keys": ["contract", "option", "oscar robertson", "freedom",
                         "sherman", "court", "lawsuit", "antitrust", "bound"],
        "base_year": 1975,
        "requires_context": False,   # extinct term: 0 hits in 1995+ documents
    },
    "territorial pick": {
        "era": "pre_1966_draft",
        "context_keys": ["draft", "college", "radius", "local", "chamberlain"],
        "base_year": 1965,
        "requires_context": False,   # the full phrase has no modern sense
    },
    "territorial": {
        "era": "pre_1966_draft",
        "context_keys": ["pick", "draft", "1965", "college", "radius",
                         "50-mile", "chamberlain", "local"],
        "base_year": 1965,
    },
}

DECADE_MAP = {
    r"\b(forties|40s|1940s)\b": 1948,
    r"\b(fifties|50s|1950s)\b": 1955,
    r"\b(sixties|60s|1960s)\b": 1965,
    r"\b(seventies|70s|1970s)\b": 1975,
    r"\b(eighties|80s|1980s)\b": 1985,
    r"\b(nineties|90s|1990s)\b": 1995,
}

# Morphological variants worth accepting; anything else matches whole-token only.
_PREFIX_OK = {"draft", "merge", "select", "absorb", "bound", "option"}


class TokenLimitExceeded(ValueError):
    def __init__(self, counted: int, limit: int = MAX_PROMPT_TOKENS):
        self.counted, self.limit = counted, limit
        super().__init__(
            f"Prompts are strictly capped at {limit:,} tokens to ensure retrieval "
            f"accuracy. Your input was {counted:,} tokens."
        )


def _tokens(text: str) -> list[str]:
    return RE_WORD.findall(text.lower())


def _key_positions(words: Sequence[str], key: str) -> list[int]:
    """Indices where ``key`` occurs, supporting multi-word keys.

    The final token of a multi-word key matches its plural, so "territorial
    pick" also fires on "territorial picks" -- which is how anyone actually
    phrases the question. Only the last token is relaxed; matching every token
    loosely would start catching unrelated phrases.
    """
    parts = key.split()
    if len(parts) > 1:
        out = []
        for i in range(len(words) - len(parts) + 1):
            window = words[i:i + len(parts)]
            if window[:-1] != parts[:-1]:
                continue
            last, want = window[-1], parts[-1]
            if last == want or last == want + "s" or last == want + "es":
                out.append(i)
        return out
    positions = []
    for i, word in enumerate(words):
        if word == key or (key in _PREFIX_OK and word.startswith(key)):
            positions.append(i)
    return positions


def verify_proximity(query: str, trigger: str, context_keys: Sequence[str],
                     window: int = PROXIMITY_WINDOW) -> bool:
    """True when ``trigger`` occurs within ``window`` words of a context cue."""
    words = _tokens(query)
    trigger_positions = _key_positions(words, trigger)
    if not trigger_positions:
        return False
    for key in context_keys:
        for kpos in _key_positions(words, key):
            if any(abs(tpos - kpos) <= window for tpos in trigger_positions):
                return True
    return False


class TemporalRouter:
    """Map a question to the season whose ruleset should answer it."""

    @classmethod
    def resolve_query_route(
        cls,
        query: str,
        clarified_season: str | None = None,
        ambiguous_years: set[int] | None = None,
    ) -> dict[str, Any]:
        # A. The user already disambiguated ("2023-24" -> 2023).
        if clarified_season:
            return {"route_action": "strict_season_filter",
                    "target_year": int(str(clarified_season).split("-")[0]),
                    "trigger_keyword": None, "era": None}

        # B. An explicit four-digit year wins over every heuristic below.
        years = RE_YEAR.findall(query)
        if years:
            year = int(years[0])
            ambiguous = AMBIGUOUS_YEARS if ambiguous_years is None else ambiguous_years
            if year in ambiguous:
                return {"route_action": "require_season_clarification",
                        "target_year": year, "trigger_keyword": None, "era": None,
                        "options": [f"{year - 1}-{str(year)[2:]}",
                                    f"{year}-{str(year + 1)[2:]}"]}
            return {"route_action": "strict_season_filter", "target_year": year,
                    "trigger_keyword": None, "era": None}

        # C. Historical trigger terms. Extinct ones fire on presence; the rest
        # need a context cue nearby to avoid hijacking a modern question.
        lowered_tokens = _tokens(query)
        for trigger, cfg in TRIGGER_CONTEXTS.items():
            if not cfg.get("requires_context", True):
                fires = bool(_key_positions(lowered_tokens, trigger))
            else:
                fires = verify_proximity(query, trigger, cfg["context_keys"])
            if fires:
                return {"route_action": "historical_keyword_override",
                        "target_year": cfg["base_year"],
                        "trigger_keyword": trigger, "era": cfg["era"]}

        # D. Decade slang ("the seventies") maps to that decade's midpoint.
        lowered = query.lower()
        for pattern, midpoint in DECADE_MAP.items():
            if re.search(pattern, lowered):
                return {"route_action": "strict_season_filter",
                        "target_year": midpoint, "trigger_keyword": None, "era": None}

        # E. Default to the rules in force this season.
        return {"route_action": "default_modern",
                "target_year": current_season(),
                "trigger_keyword": None, "era": None}
