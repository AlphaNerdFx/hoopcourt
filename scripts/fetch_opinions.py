#!/usr/bin/env python3
"""Fetch the court opinions that cover the pre-1995 era.

No public copy of any NBA collective bargaining agreement before 1995 appears to
exist. What does exist, in full and in the public domain, is the litigation that
construed those agreements: the reserve clause, the draft, the four-year rule and
the first salary cap were all litigated, and the opinions state what the rules
were with an authority no secondary summary can match.

Source is the **Caselaw Access Project** (static.case.law) rather than
CourtListener. CourtListener's full-text endpoint requires an API key and its
HTML pages sit behind an AWS WAF challenge (HTTP 202, empty body); CAP is static
JSON, open, unauthenticated, and public domain -- which keeps the project's
"no signup, no paid service" constraint intact. CourtListener remains the better
tool for *finding* a case; CAP is how the text is retrieved.

Opinions are named explicitly in corpus_manifest.yaml. They are never bulk
fetched: a docket search for "Wood v. National Basketball Association" returns
six hundred unrelated opinions.

    python scripts/fetch_opinions.py            # fetch what is missing
    python scripts/fetch_opinions.py --force    # re-fetch everything
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
UA = {"User-Agent": "Mozilla/5.0 (compatible; courtroom-to-court/1.0)"}
JUDICIAL_TIER = "judicial"


def fetch_json(url: str, timeout: int) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def render_opinion(case: dict) -> str:
    """Flatten a CAP case record into plain text with a citable header.

    The header is kept because the chunker sees only text: without the citation
    and court on the page, a retrieved passage could not say where it came from.
    """
    cites = ", ".join(c.get("cite", "") for c in case.get("citations") or [])
    court = (case.get("court") or {}).get("name_abbreviation", "")
    body = case.get("casebody") or {}

    parts = [
        case.get("name", case.get("name_abbreviation", "")),
        f"{cites} ({court} {str(case.get('decision_date'))[:4]})",
        "",
    ]
    if head := (body.get("head_matter") or "").strip():
        parts += [head, ""]
    for op in body.get("opinions") or []:
        if author := (op.get("author") or "").strip():
            parts.append(author)
        parts += [(op.get("text") or "").strip(), ""]
    return "\n".join(parts).strip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", type=Path, default=ROOT / "corpus_manifest.yaml")
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    ap.add_argument("--force", action="store_true", help="re-fetch existing files")
    ap.add_argument("--timeout", type=int, default=120)
    args = ap.parse_args()

    entries = [e for e in yaml.safe_load(
        args.manifest.read_text(encoding="utf-8"))["documents"]
        if e.get("source_tier") == JUDICIAL_TIER]

    if not entries:
        print(f"no entries with source_tier: {JUDICIAL_TIER} in the manifest")
        return 0

    failures = 0
    for e in entries:
        dest = args.data_dir / e["file"]
        if dest.exists() and not args.force:
            print(f"  {e['doc_name']:<44} present ({dest.stat().st_size:,} bytes)")
            continue
        try:
            case = fetch_json(e["source_url"], args.timeout)
            text = render_opinion(case)
        except Exception as exc:
            failures += 1
            print(f"  {e['doc_name']:<44} FAILED {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        print(f"  {e['doc_name']:<44} {len(text):>9,} chars -> {e['file']}")

    if failures:
        print(f"\n{failures} opinion(s) could not be fetched.")
        return 1
    print(f"\n{len(entries)} opinion(s) available under {args.data_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
