"""Direct PDF text extraction.

No OCR. Every one of the 18 corpus documents carries a usable text layer --
including ``CBA 1995.pdf``, whose scan was already run through Acrobat's Paper
Capture plugin -- and every one is single-column. The multi-column,
coordinate-sorted PaddleOCR pipeline of BUILD_SEQUENCE.md Step 3 therefore has
nothing in this corpus to do; ``scripts/audit_corpus.py`` re-checks that claim
so the decision can be revisited if the corpus ever grows a real scan.

Running headers are stripped because they otherwise land in the middle of
chunk text ("Article II 37 four (4) Salary Cap Years...") and pollute both the
embedding and the quoted answer. Where a header names its Article, that name is
captured -- it is the cheapest reliable source of citation metadata we have.
"""
from __future__ import annotations

import json
import pathlib
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

import pdfplumber

# "Article II 37" (odd pages) and "36 Article II" (even pages) -- the 2011/2017/
# 2023 CBA house style.
# The page number is what makes it a *running header*: requiring one keeps a
# standalone "ARTICLE IV" body heading out of this branch, so it reaches the
# structural-heading path and stays in the text where the chunker can see it.
RE_RUNNING_ARTICLE = re.compile(
    r"^(?:(?P<pg_before>\d{1,4})\s+Article\s+(?P<art_after>[IVXLC]+)"
    r"|Article\s+(?P<art_before>[IVXLC]+)\s+(?P<pg_after>\d{1,4}))$",
    re.IGNORECASE,
)
# A bare printed page number (Constitution, CBA 1995), plus the OCR debris that
# shares that slot on scanned pages ("--", "-1", "!_ __", "30 --~;1").
# Noise characters that share the header slot on scanned pages. The dash range is
# written with escapes so a future find-and-replace on dash characters cannot
# silently turn it into an invalid range.
# Characters that share the header slot on scanned pages. Assembled from
# separate literals, with the dashes given as code points, so that a
# find-and-replace over punctuation cannot corrupt the class. An earlier
# sweep rewrote the literal dashes here into an invalid range that only
# failed at import time.
_NOISE = "".join([
    r"\s", r"\-", "\u2013", "\u2014", "_", "!", "|", ".", ",",
    ";", ":", "~", "'", '"', "^", "*",
])
RE_BARE_PAGE = re.compile(rf"^[{_NOISE}]*\d{{0,4}}[{_NOISE}]*$")
# Structural headings inside the body text. Both are deliberately case-SENSITIVE
# and anchored end-to-end: a case-insensitive `^ARTICLE [IVXLC]+` also matches
# in-text cross-references such as "Article XXXI challenging the ..." that happen
# to begin a line, which silently mislabels every following chunk's citation.
RE_BODY_ARTICLE = re.compile(r"^ARTICLE\s+([IVXLC]+)\.?\s*$")
RE_SECTION = re.compile(r"^Section\s+(\d+)\.(?!\d)")

# pdfplumber inserts a space when the gap between two characters exceeds this
# many points. The default of 3 is too wide for CBA 2017's tight kerning: whole
# phrases came out as "foreachSeasonoftheContract", affecting 35% of that
# document's chunks and quietly poisoning their embeddings for an entire era.
#
# Measured across six documents at 1.5: CBA 2017's run-together count drops from
# 16 to 0 over a five-page sample, every other document is byte-identical, and
# the over-splitting proxy (short orphan tokens, the opposite failure) moves by
# +3 on CBA 2017 and 0 elsewhere. Lower is safe here; the default is not.
X_TOLERANCE = 1.5


@dataclass
class ExtractedPage:
    page_num: int                 # 1-based index into the PDF
    printed_page: str | None      # page number as printed, when detectable
    article: str | None           # roman numeral, e.g. "II"
    section: str | None           # arabic, e.g. "3"
    text: str


def _clean(text: str) -> str:
    """Normalise ligatures and smart punctuation; collapse soft hyphenation."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    # Words split across a line break by a trailing hyphen.
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    return text


def _strip_running_header(lines: list[str]) -> tuple[list[str], str | None, str | None]:
    """Remove a leading running header, returning (lines, article, printed_page)."""
    if not lines:
        return lines, None, None
    head = lines[0].strip()

    m = RE_RUNNING_ARTICLE.match(head)
    if m:
        page = m.group("pg_before") or m.group("pg_after")
        article = m.group("art_before") or m.group("art_after")
        return lines[1:], article.upper(), page

    if RE_BARE_PAGE.match(head) and len(head) <= 12:
        digits = re.match(r"^\D*(\d{1,4})", head)
        return lines[1:], None, (digits.group(1) if digits else None)

    # Short, wholly non-alphabetic leading lines are scanner debris in the
    # header slot ("30 --~;1" in CBA 1995). Drop them, but never a line with
    # letters in it -- that is body text.
    if len(head) <= 12 and not any(ch.isalpha() for ch in head):
        digits = re.match(r"^\D*(\d{1,4})", head)
        return lines[1:], None, (digits.group(1) if digits else None)

    return lines, None, None


# Court opinions arrive as plain text with no pages. They still need a locator,
# so the text is cut into fixed blocks and `page_num` counts blocks. That is not
# a reporter page and must never be cited as one -- see format_citation, which
# renders judicial sources as "part N" rather than "p. N".
TEXT_BLOCK_CHARS = 3000


def extract_text_document(path: str | Path) -> Iterator[ExtractedPage]:
    """Yield synthetic pages for a plain-text source (court opinions)."""
    raw = _clean(pathlib.Path(str(path)).read_text(encoding="utf-8", errors="replace"))
    paragraphs = [ln for ln in raw.split("\n") if ln.strip()]

    block: list[str] = []
    size = 0
    index = 0
    for para in paragraphs:
        block.append(para)
        size += len(para) + 1
        if size >= TEXT_BLOCK_CHARS:
            index += 1
            yield ExtractedPage(page_num=index, printed_page=None, article=None,
                                section=None, text="\n".join(block).strip())
            block, size = [], 0
    if block:
        index += 1
        yield ExtractedPage(page_num=index, printed_page=None, article=None,
                            section=None, text="\n".join(block).strip())


def extract_document(pdf_path: str | Path) -> Iterator[ExtractedPage]:
    """Yield one ``ExtractedPage`` per page, headers stripped, structure tracked.

    Dispatches on suffix: PDFs go through pdfplumber, plain text through
    ``extract_text_document``.
    """
    if str(pdf_path).lower().endswith((".txt", ".md")):
        yield from extract_text_document(pdf_path)
        return

    current_article: str | None = None
    current_section: str | None = None

    with pdfplumber.open(str(pdf_path)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            raw = page.extract_text(x_tolerance=X_TOLERANCE) or ""
            lines = [ln for ln in _clean(raw).split("\n") if ln.strip()]
            lines, header_article, printed = _strip_running_header(lines)

            if header_article:
                current_article = header_article

            for line in lines:
                stripped = line.strip()
                if m := RE_BODY_ARTICLE.match(stripped):
                    current_article = m.group(1).upper()
                    current_section = None
                elif m := RE_SECTION.match(stripped):
                    current_section = m.group(1)

            yield ExtractedPage(
                page_num=index,
                printed_page=printed,
                article=current_article,
                section=current_section,
                text="\n".join(lines).strip(),
            )


def extract_to_json(pdf_path: str | Path, out_dir: str | Path) -> Path:
    """Extract a document and cache it as JSON (extraction is the slow step)."""
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{pdf_path.stem}.json"

    pages = [asdict(p) for p in extract_document(pdf_path)]
    out_path.write_text(
        json.dumps({"source": pdf_path.name, "pages": pages}, indent=1),
        encoding="utf-8",
    )
    return out_path


if __name__ == "__main__":  # pragma: no cover
    import sys

    if len(sys.argv) < 2:
        sys.exit("usage: python -m src.parser.extract <file.pdf> [--json OUT_DIR]")
    target = sys.argv[1]
    if "--json" in sys.argv:
        dest = sys.argv[sys.argv.index("--json") + 1]
        print(f"wrote {extract_to_json(target, dest)}")
    else:
        for page in extract_document(target):
            print(f"\n{'='*70}\n[p{page.page_num} printed={page.printed_page} "
                  f"article={page.article} section={page.section}]\n{'='*70}")
            print(page.text[:1200])
