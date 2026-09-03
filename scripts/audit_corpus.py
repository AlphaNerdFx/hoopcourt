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


def audit(manifest_path: Path, data_dir: Path, samples: int) -> int:
    import pdfplumber

    from src.parser.extract import X_TOLERANCE

    entries = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))["documents"]
    print(f"{'DOCUMENT':<38}{'PAGES':>6}{'CHARS/PG':>9}{'FUSED/PG':>9}  VERDICT")
    print("-" * 78)

    needs_ocr, mangled, missing, total_pages = [], [], [], 0
    for entry in entries:
        pdf = data_dir / entry["file"]
        name = entry["doc_name"]
        if not pdf.exists():
            missing.append(name)
            print(f"{name:<40}{'-':>7}{'-':>10}  MISSING")
            continue
        with pdfplumber.open(pdf) as doc:
            n = len(doc.pages)
            total_pages += n
            idx = sorted({int(n * f) for f in SAMPLE_FRACTIONS[:samples]} & set(range(n)))
            texts = [(doc.pages[i].extract_text(x_tolerance=X_TOLERANCE) or "").strip()
                     for i in idx]
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
        verdict = ("text layer OK" if ok_text and ok_fused
                   else "NEEDS OCR" if not ok_text
                   else "WORDS FUSED - tune X_TOLERANCE")
        print(f"{name:<38}{n:>6}{median:>9.0f}{median_fused:>9.0f}  {verdict}")

    print("-" * 78)
    print(f"{len(entries) - len(missing)} document(s) checked, {total_pages} pages")
    if missing:
        print(f"{len(missing)} missing -- run scripts/fetch_corpus.py: "
              f"{', '.join(missing)}")
    if needs_ocr:
        print(f"\n{len(needs_ocr)} document(s) have no usable text layer: "
              f"{', '.join(needs_ocr)}")
        print("An OCR ingestion path is now justified (BUILD_SEQUENCE.md Step 3).")
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
