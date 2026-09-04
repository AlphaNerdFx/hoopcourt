#!/usr/bin/env python3
"""Help a user assemble their own local copy of the corpus.

This replaces BUILD_SEQUENCE.md Step 8, which proposed shipping a pre-compiled
`nba_legal.db` over IPFS with a BitTorrent magnet-link fallback. Three problems
with that plan, in increasing order of seriousness:

1. Nothing in the 9-step sequence ever *built* the database it downloads, and its
   SHA-256 was hardcoded from a file that did not exist.
2. It adds an IPFS gateway pool and a magnet fallback to maintain.
3. The compiled database contains the full text of copyrighted documents.
   Distributing that text is the same act as distributing the PDFs, so the
   "no raw PDFs in the repo" rule does not cure it -- it relocates it.

What this project distributes instead is *checksums and instructions*. Each user
fetches documents from official or public-record sources themselves and compiles
their own index locally. Nothing copyrighted is ever redistributed, and the
result is still reproducible and verifiable.

    python scripts/fetch_corpus.py               # what is present, what is not
    python scripts/fetch_corpus.py --record      # write checksums for your copy
    python scripts/fetch_corpus.py --verify      # check your copy against them
    python scripts/fetch_corpus.py --check-urls  # do the sources still serve the file?
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHECKSUM_FILE = ROOT / "corpus_checksums.json"


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def load_manifest(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["documents"]


def cmd_status(entries: list[dict], data_dir: Path) -> int:
    present, missing = [], []
    for e in entries:
        (present if (data_dir / e["file"]).exists() else missing).append(e)

    print(f"corpus root: {data_dir}")
    print(f"present: {len(present)}/{len(entries)}\n")
    if missing:
        print("Missing documents -- download each from its official source and save\n"
              "it at the path shown. Do not use mirrors on personal cloud storage.\n")
        for e in missing:
            print(f"  {e['doc_name']}")
            print(f"    save as : data/{e['file']}")
            print(f"    source  : {e['source_url']}\n")
        print("See DATA_SOURCES.md for what each source is and how to navigate it.")
    else:
        print("All manifest documents are present. Next:\n"
              "  python scripts/audit_corpus.py     # confirm text layers\n"
              "  python scripts/build_index.py      # compile the local index")
    return 0 if not missing else 1


def cmd_record(entries: list[dict], data_dir: Path) -> int:
    """Record checksums of the local corpus so others can verify their own copy."""
    out: dict[str, dict[str, object]] = {}
    for e in entries:
        p = data_dir / e["file"]
        if not p.exists():
            continue
        out[e["doc_name"]] = {"file": e["file"], "sha256": sha256(p),
                              "bytes": p.stat().st_size}
        print(f"  {e['doc_name']:<40} {out[e['doc_name']]['sha256'][:16]}...")
    CHECKSUM_FILE.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
    print(f"\nwrote {CHECKSUM_FILE.name} ({len(out)} entries)")
    print("This file contains no document content and is safe to commit.")
    return 0


def cmd_verify(entries: list[dict], data_dir: Path) -> int:
    if not CHECKSUM_FILE.exists():
        print(f"no {CHECKSUM_FILE.name}; run --record first", file=sys.stderr)
        return 2
    recorded = json.loads(CHECKSUM_FILE.read_text(encoding="utf-8"))
    mismatch, absent, ok = [], [], 0
    for name, info in recorded.items():
        p = data_dir / info["file"]
        if not p.exists():
            absent.append(name)
            continue
        if sha256(p) == info["sha256"]:
            ok += 1
        else:
            mismatch.append(name)

    print(f"verified {ok}/{len(recorded)}")
    for name in absent:
        print(f"  MISSING   {name}")
    for name in mismatch:
        print(f"  MISMATCH  {name}  (different edition, or a corrupted download)")
    return 1 if (mismatch or absent) else 0


def cmd_check_urls(entries: list[dict], data_dir: Path, timeout: int) -> int:
    """Confirm each source_url still serves the document it claims to.

    DATA_SOURCES.md promises a user can fetch every document from its source_url,
    which makes a stale or mis-pasted URL a real defect rather than a typo. Two
    failures this catches that reading the YAML does not:

      * a URL that serves a *different* document -- the 2012 Constitution entry
        was pasted from the 2019 entry, and only the byte count revealed it;
      * a URL that returns HTML rather than a PDF, e.g. a Scribd viewer page.

    Content-Length is compared against the local file. A mismatch is not proof of
    error (the host may have reissued the document), but an exact match is strong
    evidence the URL is right.
    """
    import urllib.error
    import urllib.request

    print(f"{'DOCUMENT':<44}{'HTTP':>6}{'REMOTE':>11}{'LOCAL':>11}  VERDICT")
    print("-" * 96)
    problems = 0
    for e in entries:
        name, url = e["doc_name"], e["source_url"]
        local = data_dir / e["file"]
        local_size = local.stat().st_size if local.exists() else None

        # Some CDNs refuse HEAD but answer a ranged GET, so try both before
        # calling a URL unreachable -- a false "UNREACHABLE" would send someone
        # hunting for a replacement source that was never broken.
        headers = {"User-Agent": "Mozilla/5.0 (compatible; courtroom-to-court/1.0)"}
        code, remote_size, ctype = "ERR", None, ""
        for method, extra in (("HEAD", {}), ("GET", {"Range": "bytes=0-0"})):
            req = urllib.request.Request(url, method=method,
                                         headers={**headers, **extra})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    code = str(r.status)
                    ctype = r.headers.get("Content-Type", "") or ""
                    if cr := r.headers.get("Content-Range"):
                        remote_size = int(cr.split("/")[-1])
                    elif cl := r.headers.get("Content-Length"):
                        remote_size = int(cl)
                break
            except urllib.error.HTTPError as exc:
                code = str(exc.code)
                if exc.code not in (403, 405, 501):
                    break
            except Exception:
                code = "ERR"

        # Expected format depends on the tier. Governing documents are PDFs;
        # court opinions come from the Caselaw Access Project as JSON. Demanding
        # PDF everywhere flagged all seven opinions as viewer pages, which is the
        # kind of standing false alarm that trains people to ignore the check.
        tier = e.get("source_tier", "primary")
        expected = "json" if tier == "judicial" else "pdf"
        if code == "200" and expected not in ctype.lower():
            verdict, bad = f"NOT {expected.upper()} (viewer page?)", True
        elif code == "200" and expected == "json":
            # The rendered .txt will not match the JSON payload's size, so a
            # reachable, correctly-typed response is all this can assert.
            verdict, bad = "reachable (CAP JSON)", False
        elif code == "200" and remote_size and local_size and remote_size == local_size:
            verdict, bad = "matches local file", False
        elif code == "200" and remote_size and local_size:
            # A different printing of the same document is legitimate; the
            # manifest records when a human has confirmed the edition matches.
            if e.get("source_verified"):
                verdict, bad = "different printing, edition verified", False
            else:
                verdict, bad = "SIZE MISMATCH - wrong document?", True
        elif code == "200":
            verdict, bad = "reachable", False
        elif code in ("403", "429"):
            verdict, bad = "blocked to scripts - check in a browser", False
        else:
            verdict, bad = "UNREACHABLE", True
        problems += bad
        print(f"{name[:43]:<44}{code:>6}{str(remote_size or '-'):>11}"
              f"{str(local_size or '-'):>11}  {verdict}")

    print("-" * 96)
    if problems:
        print(f"{problems} source URL(s) need attention.")
        return 1
    print("All source URLs look sound.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", type=Path, default=ROOT / "corpus_manifest.yaml")
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--record", action="store_true", help="write corpus_checksums.json")
    g.add_argument("--verify", action="store_true", help="check against recorded hashes")
    g.add_argument("--check-urls", action="store_true",
                   help="confirm each source_url still serves its document")
    ap.add_argument("--timeout", type=int, default=40)
    args = ap.parse_args()

    entries = load_manifest(args.manifest)
    if args.record:
        return cmd_record(entries, args.data_dir)
    if args.verify:
        return cmd_verify(entries, args.data_dir)
    if args.check_urls:
        return cmd_check_urls(entries, args.data_dir, args.timeout)
    return cmd_status(entries, args.data_dir)


if __name__ == "__main__":
    raise SystemExit(main())
