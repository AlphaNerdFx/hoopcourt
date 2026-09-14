#!/usr/bin/env python3
"""Re-check the assumption that this corpus needs no OCR.

src/parser/extract.py deliberately has no OCR path. That decision rests on a
measurement, not a preference, so this script re-runs the measurement: it samples
pages from every manifest document and reports how much text comes out.

If a future document lands with no text layer, this prints NEEDS OCR and exits
non-zero -- the signal to revisit BUILD_SEQUENCE.md Step 3 rather than assume it
stays unnecessary forever.

    python scripts/audit_corpus.py
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
import warnings
from pathlib import Path

import yaml

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
TEXT_OK_MEDIAN = 200      # chars/page below which a text layer is not usable
SAMPLE_FRACTIONS = (0.15, 0.30, 0.45, 0.60, 0.75, 0.90)

# "foreachSeasonoftheContract" -- words fused because the PDF's kerning is
# tighter than the extractor's space threshold. A page can be full of text and
# still be useless: fused tokens embed as noise. CBA 2017 shipped with 35% of its
# chunks affected before X_TOLERANCE was tuned, so this is checked, not assumed.
RE_RUN_TOGETHER = re.compile(r"[a-z][A-Z][a-z]")
RUN_TOGETHER_LIMIT = 3    # per sampled page, averaged
MIN_TRUSTWORTHY_SAMPLES = 3   # below this the median is one sparse page

# Court opinions arrive as plain text from the Caselaw Access Project, not as
# PDFs, so they have no pages and no text layer to sample. They are still worth
# auditing: a truncated download is exactly as fatal as a missing text layer and
# looks identical in the index. Slicing them into notional pages lets the same
# two measurements run over both kinds without a second set of thresholds.
TEXT_PAGE_CHARS = 3000


def sample_pages(path: Path, samples: int) -> tuple[int, list[str]]:
    """Return (page count, sampled page texts) for a PDF or a plain-text source.

    Sampling by index matters: extracting all 600 pages of a CBA to look at six
    of them costs about a minute per document.
    """
    def pick(n: int) -> list[int]:
        return sorted({int(n * f) for f in SAMPLE_FRACTIONS[:samples]} & set(range(n)))

    if path.suffix.lower() == ".pdf":
        import pdfplumber

        from src.parser.extract import X_TOLERANCE
        with pdfplumber.open(path) as doc:
            n = len(doc.pages)
            return n, [
                (doc.pages[i].extract_text(x_tolerance=X_TOLERANCE) or "").strip()
                for i in pick(n)
            ]

    body = path.read_text(encoding="utf-8", errors="replace")
    pages = [body[i:i + TEXT_PAGE_CHARS]
             for i in range(0, max(len(body), 1), TEXT_PAGE_CHARS)]
    return len(pages), [pages[i].strip() for i in pick(len(pages))]


def audit(manifest_path: Path, data_dir: Path, samples: int) -> int:
    entries = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))["documents"]
    print(f"{'DOCUMENT':<38}{'PAGES':>6}{'CHARS/PG':>9}{'FUSED/PG':>9}  VERDICT")
    print("-" * 78)

    needs_ocr, mangled, missing = [], [], []
    pdf_pages = text_blocks = 0
    for entry in entries:
        source = data_dir / entry["file"]
        name = entry["doc_name"]
        if not source.exists():
            missing.append(name)
            print(f"{name:<40}{'-':>7}{'-':>10}  MISSING")
            continue
        is_pdf = source.suffix.lower() == ".pdf"
        n, texts = sample_pages(source, samples)
        # Counted apart: a PDF page is a real page, a text block is this
        # script's own slicing unit. Adding them yields a number that means
        # nothing and invites being quoted as a page count.
        if is_pdf:
            pdf_pages += n
        else:
            text_blocks += n
        counts = [len(t) for t in texts]
        fused = [len(RE_RUN_TOGETHER.findall(t)) for t in texts]
        median = statistics.median(counts) if counts else 0
        median_fused = statistics.median(fused) if fused else 0

        ok_text = median >= TEXT_OK_MEDIAN
        ok_fused = median_fused <= RUN_TOGETHER_LIMIT
        if not ok_text:
            needs_ocr.append(name)
        elif not ok_fused:
            mangled.append(name)
        # "NEEDS OCR" is only meaningful for a PDF. A short text file is not a
        # scanning problem, it is a truncated or failed download.
        thin = "NEEDS OCR" if is_pdf else "TEXT TRUNCATED - refetch"
        verdict = ("text layer OK" if ok_text and ok_fused
                   else thin if not ok_text
                   else "WORDS FUSED - tune X_TOLERANCE")
        print(f"{name:<38}{n:>6}{median:>9.0f}{median_fused:>9.0f}  {verdict}")

    print("-" * 78)
    print(f"{len(entries) - len(missing)} document(s) checked, "
          f"{pdf_pages:,} PDF pages and {text_blocks:,} text blocks")
    if missing:
        print(f"{len(missing)} missing -- run scripts/fetch_corpus.py: "
              f"{', '.join(missing)}")
    if needs_ocr:
        print(f"\n{len(needs_ocr)} document(s) carry no usable text: "
              f"{', '.join(needs_ocr)}")
        if samples < MIN_TRUSTWORTHY_SAMPLES:
            # With one or two sampled pages the median is one or two pages, and
            # a title page or a plate carries almost no text. Measured: at
            # --samples 1 this condemns the Officials Guide and NBA
            # Constitution 2012, both of which pass comfortably at 3.
            print(f"CAUTION: only {samples} page(s) sampled per document. That "
                  f"is too few to conclude anything; re-run with "
                  f"--samples {MIN_TRUSTWORTHY_SAMPLES} or more before "
                  f"believing this.")
        else:
            print("An OCR ingestion path is now justified "
                  "(BUILD_SEQUENCE.md Step 3).")
        return 1
    if mangled:
        print(f"\n{len(mangled)} document(s) extract with fused words: "
              f"{', '.join(mangled)}")
        print("Text is present but words run together, which embeds as noise.")
        print("Lower X_TOLERANCE in src/parser/extract.py and re-run, then rebuild "
              "those documents.")
        return 1
    print("\nNo document requires OCR, and none extracts with fused words. "
          "The direct-extraction decision still holds.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, default=ROOT / "corpus_manifest.yaml")
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    ap.add_argument("--samples", type=int, default=6, choices=range(1, 7))
    args = ap.parse_args()
    return audit(args.manifest, args.data_dir, args.samples)


if __name__ == "__main__":
    raise SystemExit(main())
