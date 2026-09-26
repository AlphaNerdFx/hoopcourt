#!/usr/bin/env python3
"""Dependency vulnerability audit, with a triage list that has to justify itself.

Wraps ``pip-audit``. The wrapper exists because a raw run is red today and would
stay red: 20 advisories across three packages, none of which this application's
code paths can reach. A scanner that is always red gets ignored, and then it is
ignored on the day it reports something real.

So each known advisory is listed below with the reason it does not apply,
checked against the source rather than assumed. Anything NOT on that list exits
non-zero. The list is also checked in the other direction: an entry that no
longer appears upstream is reported as stale, so the triage cannot quietly rot
into a permanent silence.

    python scripts/audit_deps.py                 # triaged run, for CI
    python scripts/audit_deps.py --show-triaged  # include the accepted ones
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ["requirements.txt", "requirements-dev.txt"]

# Advisory id -> why it cannot be reached from this code. Verified 2026-09-27 by
# reading src/, not by reasoning about the package in general. Re-verify before
# extending: the justification is about OUR call sites, so a new feature can
# invalidate one of these without the advisory changing at all.
TRIAGED: dict[str, str] = {
    # -- starlette -------------------------------------------------------
    "PYSEC-2026-161":
        "Host header can poison request.url. Nothing in src/ reads request.url; "
        "grep finds only urllib.request.urlopen in the Ollama client.",
    "PYSEC-2026-248":
        "A path not starting with / moves the URL authority boundary. Same reason: "
        "no security decision here reads request.url, .hostname or .netloc.",
    "PYSEC-2026-249":
        "max_fields/max_part_size ignored for urlencoded bodies. The API accepts "
        "JSON only and never calls request.form(); there is no Form() parameter.",
    "PYSEC-2026-2280":
        "HTTPEndpoint resolves handlers by getattr on the method name. No "
        "HTTPEndpoint subclass exists; every route is a function with @app.get/post.",
    "PYSEC-2026-2281":
        "StaticFiles UNC path SSRF on Windows. StaticFiles is never mounted; the "
        "single page is served with FileResponse, and the target platform is Linux.",
    # -- pytest ----------------------------------------------------------
    "PYSEC-2026-1845":
        "Test runner only. Not imported by src/ and not installed by "
        "requirements.txt, so it is absent from any user installation.",
    # -- transformers (transitive, via sentence-transformers) -------------
    "PYSEC-2025-217":
        "X-CLIP checkpoint conversion RCE. No checkpoint conversion here; the only "
        "transformers use is AutoTokenizer.from_pretrained, on an opt-in path.",
    "PYSEC-2026-2288":
        "Trainer._load_rng_state calls torch.load without weights_only. Trainer is "
        "never imported; grep for Trainer and torch.load over src/ finds neither.",
    "PYSEC-2026-2289": "transformers; same reasoning as PYSEC-2026-2288.",
    "PYSEC-2026-2290": "transformers; same reasoning as PYSEC-2026-2288.",
    "PYSEC-2026-3929": "transformers; same reasoning as PYSEC-2026-2288.",
}


def run_pip_audit() -> list[dict]:
    # Through the running interpreter, not a bare `pip-audit` on PATH: that way
    # the audit inspects the environment it was invoked from, and it works
    # inside a virtualenv whose bin directory is not on PATH.
    cmd = [sys.executable, "-m", "pip_audit",
           "--format", "json", "--progress-spinner", "off"]
    for req in REQUIREMENTS:
        cmd += ["-r", str(ROOT / req)]
    # pip-audit exits 1 when it finds anything, which is not an error for us.
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if not proc.stdout.strip():
        print(proc.stderr, file=sys.stderr)
        raise SystemExit("pip-audit produced no output")
    return json.loads(proc.stdout).get("dependencies", [])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--show-triaged", action="store_true")
    args = ap.parse_args()

    findings: list[tuple[str, str, str, str]] = []
    for dep in run_pip_audit():
        for vuln in dep.get("vulns", []):
            findings.append((dep["name"], dep["version"], vuln["id"],
                             ", ".join(vuln.get("fix_versions") or []) or "none"))

    # De-duplicate: the same advisory is reported once per requirements file.
    findings = sorted(set(findings))
    untriaged = [f for f in findings if f[2] not in TRIAGED]
    accepted = [f for f in findings if f[2] in TRIAGED]
    seen = {f[2] for f in findings}
    stale = sorted(set(TRIAGED) - seen)

    print(f"pip-audit: {len(findings)} advisory/advisories, "
          f"{len(accepted)} triaged, {len(untriaged)} new")

    if args.show_triaged and accepted:
        print("\nAccepted, with the reason each cannot be reached:")
        for name, version, vid, fix in accepted:
            print(f"  {name} {version}  {vid}  (fix: {fix})")
            print(f"      {TRIAGED[vid]}")

    if stale:
        print("\nSTALE triage entries: these no longer appear and should be removed,")
        print("because a triage list that outlives its advisories hides the next one:")
        for vid in stale:
            print(f"  {vid}")

    if untriaged:
        print("\nNEW, untriaged:")
        for name, version, vid, fix in untriaged:
            print(f"  {name} {version}  {vid}  (fix: {fix})")
        print("\nEither upgrade, or add the id to TRIAGED in this file with the "
              "reason it cannot be reached from src/. Do not add it without "
              "checking the call sites.")
        return 1

    print("\nNo untriaged advisories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
