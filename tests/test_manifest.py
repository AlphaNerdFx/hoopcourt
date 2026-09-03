"""Validate corpus_manifest.yaml.

The manifest is hand-edited whenever a document is added or a source changes, and
its season windows *are* the routing logic, so an error here is a rule-bleeding
bug that produces confident wrong answers with real-looking citations, not a
crash. Every check below corresponds to a mistake that actually reached the file.
"""
from __future__ import annotations

import collections
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MANIFEST = yaml.safe_load(
    (ROOT / "corpus_manifest.yaml").read_text(encoding="utf-8"))["documents"]

CATEGORIES = {"Historical", "Current Operational", "Current Governing"}
ALLOWED_KEYS = {"file", "doc_name", "category", "start_season", "end_season",
                "source_url", "source_verified", "source_tier"}
TIERS = {"primary", "judicial", "timeline"}

# Documents that supersede one another form a lineage; two editions must never
# govern the same season.
LINEAGES = {
    "Constitution": lambda n: "Constitution" in n,
    "CBA": lambda n: re.search(r"\bCBA\b", n) and "101" not in n and "Exhibit" not in n,
}


def ids(q):
    return q["doc_name"]


@pytest.mark.parametrize("entry", MANIFEST, ids=ids)
def test_entry_is_well_formed(entry):
    assert entry["category"] in CATEGORIES
    assert isinstance(entry["start_season"], int)
    assert isinstance(entry["end_season"], int)
    assert entry["start_season"] <= entry["end_season"]
    assert entry["source_url"].startswith("http")
    unknown = set(entry) - ALLOWED_KEYS
    assert not unknown, f"unknown key(s) in manifest entry: {sorted(unknown)}"
    assert entry.get("source_tier", "primary") in TIERS


def test_document_names_are_unique():
    dupes = [n for n, c in collections.Counter(
        e["doc_name"] for e in MANIFEST).items() if c > 1]
    assert not dupes, f"duplicate doc_name: {dupes}"


def test_file_paths_are_unique():
    dupes = [f for f, c in collections.Counter(
        e["file"] for e in MANIFEST).items() if c > 1]
    assert not dupes, f"duplicate file: {dupes}"


def test_source_urls_are_not_accidentally_shared():
    """A pasted-in URL is how the 2012 Constitution ended up pointing at the 2019
    document. Distinct documents that share a URL are almost always a copy/paste."""
    shared = {u: [e["doc_name"] for e in MANIFEST if e["source_url"] == u]
              for u, c in collections.Counter(
                  e["source_url"] for e in MANIFEST).items() if c > 1}
    assert not shared, f"documents sharing a source_url: {shared}"


def test_judicial_entries_are_pre_1995():
    """Court opinions exist in this corpus to carry the era with no surviving CBA
    text. One scoped into the modern range would compete with the governing
    document it merely describes."""
    for e in MANIFEST:
        if e.get("source_tier") == "judicial":
            assert e["start_season"] < 1995, (
                f"{e['doc_name']} starts at {e['start_season']}; judicial sources "
                f"are for the pre-1995 gap")


def test_pre_1995_has_no_primary_sources():
    """If a real pre-1995 CBA ever surfaces, this fails -- and it should, because
    the whole judicial/timeline apparatus would then need revisiting."""
    early = [e for e in MANIFEST
             if e.get("source_tier", "primary") == "primary" and e["start_season"] < 1995]
    assert not early, f"primary source before 1995: {[e['doc_name'] for e in early]}"


@pytest.mark.parametrize("label,pred", list(LINEAGES.items()))
def test_lineage_windows_do_not_overlap(label, pred):
    """Two editions of the same document must not both govern a season."""
    rows = sorted((e["start_season"], e["end_season"], e["doc_name"])
                  for e in MANIFEST if pred(e["doc_name"]))
    for (s1, e1, n1), (s2, e2, n2) in zip(rows, rows[1:], strict=False):
        assert s2 > e1, (
            f"{label} overlap: {n1} ({s1}-{e1}) and {n2} ({s2}-{e2}) "
            f"both govern {s2}")


def test_cba_lineage_has_no_gaps():
    rows = sorted((e["start_season"], e["end_season"], e["doc_name"])
                  for e in MANIFEST if LINEAGES["CBA"](e["doc_name"]))
    for (_, e1, n1), (s2, _, n2) in zip(rows, rows[1:], strict=False):
        assert s2 == e1 + 1, f"gap or overlap between {n1} and {n2}"


@pytest.mark.skipif(not DATA.exists(), reason="corpus not present (it is gitignored)")
@pytest.mark.parametrize("entry", MANIFEST, ids=ids)
def test_file_exists_with_exactly_this_name(entry):
    """Case-sensitively. The 2012 Constitution was listed as .pdf while the file
    on disk was .PDF, so the build silently skipped it on Linux."""
    path = DATA / entry["file"]
    if path.exists():
        return
    parent = path.parent
    near = [p.name for p in parent.iterdir()
            if p.name.lower() == path.name.lower()] if parent.exists() else []
    pytest.fail(f"{entry['file']} not found"
                + (f" -- but {near} exists (case mismatch)" if near else ""))
