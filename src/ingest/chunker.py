"""Structure-aware chunking for legal text.

Fixed-size windows are wrong for this corpus: they cut mid-sentence and leave a
chunk that cites one section while quoting another, which is exactly the failure
the grounding rule (CLAUDE.md sec.2.2) treats as fatal. So chunks are cut on the
documents' own boundaries -- Section first, then paragraph -- and only fall back
to a hard character cap when a single section runs long.

Sizing is driven by the generation budget rather than chosen by feel. With
n_ctx=8192 and k=5 retrieved chunks, the context must hold 5 chunks plus the
system prompt plus a 1,000-token question and still leave room to answer:
~2,000 characters (~500 tokens) per chunk keeps 5 chunks near 2,500 tokens and
leaves roughly half the window free.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from src.parser.extract import RE_BODY_ARTICLE, ExtractedPage

TARGET_CHARS = 1400   # preferred chunk size
MAX_CHARS = 2000      # hard cap; see the context-budget note above
MIN_CHARS = 120       # below this a chunk is boilerplate, not content
OVERLAP_CHARS = 150   # carried across a size-forced split, never across sections

RE_SECTION_HEADING = re.compile(r"^Section\s+(\d+)\.(?!\d)")


@dataclass
class Chunk:
    doc_name: str
    text: str
    article: str | None
    section: str | None
    page_num: int
    chunk_hash: str

    def citation(self) -> str:
        """Same format the API and prompts emit -- one definition, one format."""
        from src.model.prompt_templates import format_citation

        return format_citation({
            "document": self.doc_name, "article": self.article,
            "section": self.section, "page": self.page_num,
        })


def _hash(doc_name: str, page: int, text: str) -> str:
    return hashlib.sha256(
        f"{doc_name}|{page}|{text}".encode()
    ).hexdigest()


def _split_oversized(text: str) -> list[str]:
    """Split a too-long block on paragraph, then sentence, then hard boundaries."""
    if len(text) <= MAX_CHARS:
        return [text]

    pieces: list[str] = []
    buffer = ""
    # Sentence-ish boundaries keep legal enumerations "(a) ... (b) ..." intact
    # more often than a blind character cut does.
    units = re.split(r"(?<=[.;:])\s+(?=[A-Z(])", text)
    for unit in units:
        if buffer and len(buffer) + len(unit) + 1 > TARGET_CHARS:
            pieces.append(buffer.strip())
            buffer = buffer[-OVERLAP_CHARS:].strip() + " " + unit
        else:
            buffer = f"{buffer} {unit}".strip()
    if buffer.strip():
        pieces.append(buffer.strip())

    # Anything still over the hard cap (a single enormous sentence) is cut.
    out: list[str] = []
    for piece in pieces:
        while len(piece) > MAX_CHARS:
            out.append(piece[:MAX_CHARS])
            piece = piece[MAX_CHARS - OVERLAP_CHARS:]
        if piece.strip():
            out.append(piece.strip())
    return out


def chunk_pages(doc_name: str, pages: Iterable[ExtractedPage]) -> list[Chunk]:
    """Group page text into citable chunks, flushing on section boundaries.

    Section state is tracked per *line* here rather than taken from
    ``page.section``. The page-level value is whatever section was last seen
    anywhere on that page, so text at the top of a page that still belongs to
    the previous section would inherit a later section number -- producing a
    chunk that cites Section 6 while quoting "this Section 4". Citations that
    confidently point at the wrong provision are worse than no citation.
    """
    chunks: list[Chunk] = []
    buffer: list[str] = []
    buf_len = 0
    cur_article: str | None = None
    cur_section: str | None = None
    ctx: dict[str, object] = {"article": None, "section": None, "page": 1}

    def flush() -> None:
        nonlocal buffer, buf_len
        body = "\n".join(buffer).strip()
        buffer, buf_len = [], 0
        if len(body) < MIN_CHARS:
            return
        for piece in _split_oversized(body):
            if len(piece) < MIN_CHARS:
                continue
            chunks.append(
                Chunk(
                    doc_name=doc_name,
                    text=piece,
                    article=ctx["article"],           # type: ignore[arg-type]
                    section=ctx["section"],           # type: ignore[arg-type]
                    page_num=int(ctx["page"]),        # type: ignore[arg-type]
                    chunk_hash=_hash(doc_name, int(ctx["page"]), piece),  # type: ignore[arg-type]
                )
            )

    for page in pages:
        if not page.text.strip():
            continue
        # The running header names the article for the whole page and is the
        # most reliable article signal we have.
        if page.article:
            cur_article = page.article
        for line in page.text.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            if m := RE_BODY_ARTICLE.match(stripped):
                if buffer:
                    flush()
                cur_article, cur_section = m.group(1).upper(), None
            elif m := RE_SECTION_HEADING.match(stripped):
                # A new Section starts a new chunk: never let two share one.
                if buffer:
                    flush()
                cur_section = m.group(1)
            if not buffer:
                # Chunk metadata is that of its first line, so a chunk always
                # cites the page and section its text actually begins on.
                ctx = {"article": cur_article, "section": cur_section,
                       "page": page.page_num}
            buffer.append(stripped)
            buf_len += len(stripped) + 1
            if buf_len >= TARGET_CHARS:
                flush()
    flush()
    return chunks


def dedupe(chunks: Sequence[Chunk]) -> list[Chunk]:
    """Drop repeated boilerplate; chunk_hash is UNIQUE in the schema."""
    seen: set[str] = set()
    out: list[Chunk] = []
    for c in chunks:
        if c.chunk_hash in seen:
            continue
        seen.add(c.chunk_hash)
        out.append(c)
    return out
