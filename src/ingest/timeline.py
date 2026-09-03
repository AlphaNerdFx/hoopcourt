"""Load the curated historical timeline and render it for indexing.

CLAUDE.md sec.2.2 allows "verified historical JSON timelines" as a grounding
source alongside retrieved chunks. This is that mechanism. It carries the
pre-1995 era, where no public CBA text survives and the court opinions reach only
as far back as the litigation does.

Each entry becomes its own ``documents`` row rather than sharing one. That is not
a modelling accident: the era filter operates on ``documents.start_season`` /
``end_season``, so a per-entry row gives every claim its own validity window and
reuses the pre-filter in ``src/db/search.py`` **unchanged** -- the one piece of
SQL the anti-bleed guarantee rests on. A single shared row would make every entry
retrievable for every pre-1995 season, which is exactly the bleeding this project
exists to prevent.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONFIDENCE_LEVELS = ("high", "medium")
REQUIRED_FIELDS = ("id", "topic", "start_season", "end_season", "summary",
                   "citation", "source_url", "confidence")


@dataclass
class TimelineEntry:
    id: str
    topic: str
    start_season: int
    end_season: int
    summary: str
    citation: str
    source_url: str
    confidence: str

    @property
    def doc_name(self) -> str:
        """How this entry is cited. The window is part of the name because a
        timeline claim is only true for the seasons it names."""
        span = (str(self.start_season) if self.start_season == self.end_season
                else f"{self.start_season}-{self.end_season}")
        label = self.id.replace("-", " ").capitalize()
        return f"{label} ({span})"

    def render(self) -> str:
        """The indexed text. The citation travels *inside* the chunk so a
        retrieved passage carries its own authority even if a caller drops the
        surrounding metadata."""
        lines = [
            f"{self.topic} ({self.start_season}-{self.end_season})",
            "",
            " ".join(self.summary.split()),
            "",
            f"Source: {self.citation}",
        ]
        if self.confidence != "high":
            lines.append(
                "Confidence: medium -- drawn from the league's published history "
                "rather than from a document in this index. Treat as background, "
                "not as the text of a rule."
            )
        return "\n".join(lines)

    def chunk_hash(self) -> str:
        return hashlib.sha256(
            f"timeline|{self.id}|{self.render()}".encode()
        ).hexdigest()


def load_timeline(path: str | Path) -> list[TimelineEntry]:
    """Parse and validate the timeline file."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    entries = raw.get("entries") or []
    seen: set[str] = set()
    out: list[TimelineEntry] = []

    for i, e in enumerate(entries):
        missing = [f for f in REQUIRED_FIELDS if f not in e]
        if missing:
            raise ValueError(f"timeline entry {i} ({e.get('id','?')}) missing {missing}")
        if e["id"] in seen:
            raise ValueError(f"duplicate timeline id: {e['id']}")
        seen.add(e["id"])
        if e["confidence"] not in CONFIDENCE_LEVELS:
            raise ValueError(f"{e['id']}: confidence must be one of {CONFIDENCE_LEVELS}")
        if int(e["start_season"]) > int(e["end_season"]):
            raise ValueError(f"{e['id']}: start_season after end_season")
        if not str(e["citation"]).strip():
            # An uncited entry is an assertion this project cannot stand behind.
            raise ValueError(f"{e['id']}: citation is required")
        out.append(TimelineEntry(
            id=e["id"], topic=e["topic"],
            start_season=int(e["start_season"]), end_season=int(e["end_season"]),
            summary=e["summary"], citation=e["citation"],
            source_url=e["source_url"], confidence=e["confidence"],
        ))
    return out


def entry_stats(entries: list[TimelineEntry]) -> dict[str, Any]:
    covered: set[int] = set()
    for e in entries:
        covered.update(range(e.start_season, e.end_season + 1))
    return {
        "entries": len(entries),
        "high_confidence": sum(1 for e in entries if e.confidence == "high"),
        "medium_confidence": sum(1 for e in entries if e.confidence == "medium"),
        "seasons_covered": len(covered),
        "span": (min(covered), max(covered)) if covered else None,
    }
