"""Tests for the corpus audit.

Written after the script was found crashing on every court opinion in the
manifest. It had been correct when written, when the corpus was 18 PDFs; Phase 7
added 7 plain-text opinions and `pdfplumber.open` raises on those. The audit is
named as the standing guard in CLAUDE.md, TODO.md and the architecture doc, so it
had been silently unrunnable for the whole of Phase 7.

Nothing tested it, which is the actual defect. These fixtures are synthetic
because `data/` is gitignored: the suite must pass on a clean checkout with no
corpus present.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.audit_corpus import audit, sample_pages  # noqa: E402

PROSE = ("The National Basketball Association and the Players Association "
         "agree as follows, and this sentence exists only to give the audit "
         "something of realistic length to measure. ")


def _corpus(tmp_path: Path, name: str, filename: str, body: str) -> tuple[Path, Path]:
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / filename).write_text(body, encoding="utf-8")
    manifest = tmp_path / f"{filename}.manifest.yaml"
    manifest.write_text(
        yaml.safe_dump({"documents": [{"doc_name": name, "file": filename}]}),
        encoding="utf-8",
    )
    return manifest, data


def test_plain_text_source_audits_instead_of_crashing(tmp_path):
    """The regression. A .txt opinion used to raise PdfminerException."""
    manifest, data = _corpus(tmp_path, "Haywood v. NBA", "haywood.txt", PROSE * 200)
    assert audit(manifest, data, samples=6) == 0


def test_truncated_text_source_fails_the_audit(tmp_path):
    """A half-downloaded opinion is as fatal as a missing text layer and looks
    identical once indexed, so it has to fail rather than pass quietly."""
    manifest, data = _corpus(tmp_path, "Truncated v. NBA", "stub.txt", "Syllabus.")
    assert audit(manifest, data, samples=6) == 1


def test_fused_words_fail_the_audit(tmp_path):
    """The CBA 2017 failure mode: text present, words run together, embeds as
    noise. Detection must not be PDF-only."""
    manifest, data = _corpus(tmp_path, "Fused v. NBA", "fused.txt",
                             "foreachSeasonoftheContractthePlayerShallBePaid " * 200)
    assert audit(manifest, data, samples=6) == 1


def test_missing_source_is_reported_not_raised(tmp_path):
    """A partial corpus should say what to fetch, not stop the run."""
    manifest, data = _corpus(tmp_path, "Gone v. NBA", "gone.txt", PROSE)
    (data / "gone.txt").unlink()
    assert audit(manifest, data, samples=6) == 0


def test_text_is_sliced_into_notional_pages(tmp_path):
    """Page counts for a text file are a unit of measurement, not a real page
    count, but they must still be proportional to length."""
    src = tmp_path / "op.txt"
    src.write_text("x" * 9000, encoding="utf-8")
    n, texts = sample_pages(src, samples=6)
    assert n == 3
    assert texts and all(t for t in texts)


def test_empty_file_does_not_divide_by_zero(tmp_path):
    src = tmp_path / "empty.txt"
    src.write_text("", encoding="utf-8")
    n, texts = sample_pages(src, samples=6)
    assert n == 1
    assert texts == [""]


@pytest.mark.parametrize("suffix", [".txt", ".TXT"])
def test_suffix_check_is_case_insensitive(tmp_path, suffix):
    """`NBA Constitution 2012.PDF` ships with an uppercase extension, so the
    branch cannot be a case-sensitive compare in either direction."""
    src = tmp_path / f"op{suffix}"
    src.write_text(PROSE * 50, encoding="utf-8")
    n, _ = sample_pages(src, samples=6)
    assert n >= 1
