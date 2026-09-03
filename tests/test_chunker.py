"""Chunking tests.

The property that matters is that a chunk's citation describes the text the chunk
actually contains. A chunk citing Section 6 while quoting "this Section 4" is
worse than an uncited chunk: it is confidently wrong, and the whole design
depends on citations being trustworthy.
"""
from __future__ import annotations

from src.ingest.chunker import (
    MAX_CHARS,
    MIN_CHARS,
    Chunk,
    chunk_pages,
    dedupe,
)
from src.parser.extract import ExtractedPage


def page(num, text, article=None, section=None):
    return ExtractedPage(page_num=num, printed_page=str(num), article=article,
                         section=section, text=text)


def test_section_heading_forces_a_new_chunk():
    body = "Filler sentence for length. " * 8
    pages = [page(1, f"Section 4. Compensation.\n{body}\n"
                     f"Section 5. Conformity.\n{body}", article="II")]
    chunks = chunk_pages("DOC", pages)
    sections = [c.section for c in chunks]
    assert "4" in sections and "5" in sections
    for c in chunks:
        if c.section == "5":
            assert "Section 4." not in c.text


def test_continuation_text_keeps_the_section_it_belongs_to():
    """Regression for the page-level section bug.

    Text at the top of page 11 still belongs to Section 4; Section 5 only starts
    further down that page. Taking the section from `page.section` -- the last
    section seen anywhere on the page -- labelled that continuation Section 5,
    producing a chunk that cited Section 5 while quoting Section 4's text.
    """
    marker = "CARRYOVER-SENTENCE-BELONGING-TO-SECTION-FOUR. "
    tail = marker * 6
    pages = [
        page(10, "Section 4. Compensation.\n" + "Body of section four. " * 6,
             article="II"),
        page(11, f"{tail}\nSection 5. Conformity.\n" + "Body of section five. " * 6,
             article="II"),
    ]
    chunks = chunk_pages("DOC", pages)

    carrying = [c for c in chunks if marker in c.text]
    assert carrying, "the carryover text should survive chunking"
    assert all(c.section == "4" for c in carrying), (
        f"carryover cited as section {[c.section for c in carrying]}, expected 4")

    five = [c for c in chunks if "Body of section five" in c.text]
    assert five and all(c.section == "5" for c in five)
    assert all(marker not in c.text for c in five), "sections must not share a chunk"


def test_article_heading_resets_the_section():
    body = "Provision text of sufficient length to survive. " * 5
    pages = [page(1, f"Section 9. Late Provision.\n{body}\nARTICLE V\nBENEFITS\n{body}")]
    chunks = chunk_pages("DOC", pages)
    after = [c for c in chunks if c.article == "V"]
    assert after, "ARTICLE heading should set the article"
    assert all(c.section != "9" for c in after), "section must reset at a new article"


def test_running_header_article_applies_to_the_whole_page():
    body = "Some provision text that is long enough to be kept. " * 5
    chunks = chunk_pages("DOC", [page(37, body, article="II")])
    assert chunks and all(c.article == "II" for c in chunks)


def test_chunks_respect_the_hard_size_cap():
    pages = [page(1, "A single very long run-on clause without punctuation " * 400)]
    for c in chunk_pages("DOC", pages):
        assert len(c.text) <= MAX_CHARS


def test_short_boilerplate_is_dropped():
    assert chunk_pages("DOC", [page(1, "iii")]) == []
    assert chunk_pages("DOC", [page(1, "x" * (MIN_CHARS - 10))]) == []


def test_blank_pages_are_skipped_without_error():
    assert chunk_pages("DOC", [page(1, ""), page(2, "   \n  ")]) == []


def test_citation_renders_every_available_locator():
    c = Chunk("2023 NBA CBA", "text", "II", "7", 37, "hash")
    assert c.citation() == "2023 NBA CBA, Article II, Section 7, p. 37"
    assert Chunk("D", "t", None, None, 3, "h").citation() == "D, p. 3"


def test_chunk_hash_is_stable_and_content_addressed():
    body = "Identical provision text repeated across two documents. " * 4
    a = chunk_pages("DOC", [page(1, body)])
    b = chunk_pages("DOC", [page(1, body)])
    assert [c.chunk_hash for c in a] == [c.chunk_hash for c in b]
    other = chunk_pages("OTHER DOC", [page(1, body)])
    assert a[0].chunk_hash != other[0].chunk_hash, "hash must include the document"


def test_dedupe_removes_repeated_boilerplate():
    body = "Repeated footer boilerplate of adequate length for a chunk. " * 4
    chunks = chunk_pages("DOC", [page(1, body)]) * 3
    assert len(dedupe(chunks)) == len(chunks) // 3
