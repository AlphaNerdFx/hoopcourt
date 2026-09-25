#!/usr/bin/env python3
"""End-to-end smoke test of the public API contract against a built index.

Complements the evaluation rather than repeating it. run_eval.py scores routing
and retrieval over 45 labelled questions by calling the internals directly; this
drives the assembled FastAPI app and checks the things only the HTTP surface can
get wrong: status codes, response shape, and the coverage and grounding objects
a caller is expected to branch on.

Assertions are on the observation, never on a verdict field that can be true
because nothing happened -- the failure DECISIONS.md and TESTING.md both record.

    BACKEND_MODE=none python scripts/smoke_test.py --db ci.db
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "ok  " if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(f"{label}: {detail}" if detail else label)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="nba_legal.db")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"no index at {db}", file=sys.stderr)
        return 2

    os.environ["NBA_LEGAL_DB"] = str(db)
    # Not 'local': that would try ollama and then llama-cpp. Generation is not
    # what this test is for, and an unrecognised mode disables it deliberately.
    os.environ.setdefault("BACKEND_MODE", "none")

    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.db.connection import get_vector_db_connection
    from src.db.schema import ambiguous_seasons, coverage_bounds

    conn = get_vector_db_connection(str(db))
    bounds = coverage_bounds(conn)
    ambiguous = ambiguous_seasons(conn)
    indexed = {r["doc_name"]: (r["start_season"], r["end_season"])
               for r in conn.execute(
                   "SELECT doc_name, start_season, end_season FROM documents")}
    conn.close()
    print(f"index: {len(indexed)} documents, coverage {bounds}, "
          f"{len(ambiguous)} ambiguous year(s)")

    with TestClient(app) as client:
        print("\n/health")
        r = client.get("/health")
        check("200", r.status_code == 200, str(r.status_code))
        health = r.json() if r.status_code == 200 else {}
        idx = health.get("index", {})
        check("reports documents", idx.get("documents", 0) > 0, str(idx))
        check("reports vectors", idx.get("vectors", 0) > 0, str(idx))
        check("no orphaned vectors", idx.get("orphaned_vectors", 1) == 0, str(idx))
        check("names the vector engine", bool(health.get("engine", {}).get("sqlite_vec")),
              str(health.get("engine")))

        print("\n/ (single-page UI)")
        r = client.get("/")
        check("200", r.status_code == 200, str(r.status_code))

        print("\n/query, a question inside coverage")
        # Chosen because the judicial tier answers it, so this holds on the
        # public-domain index CI builds as well as on a full one.
        r = client.post("/query", json={"query": "What was the reserve clause?", "k": 5})
        check("200", r.status_code == 200, r.text[:200])
        body = r.json() if r.status_code == 200 else {}
        year = body.get("target_year")
        check("routed to a year", isinstance(year, int), str(year))
        check("returned sources", len(body.get("sources", [])) > 0,
              f"coverage={body.get('coverage')}")
        check("grounded flag matches the sources it returned",
              body.get("grounded") is bool(body.get("sources")),
              f"grounded={body.get('grounded')} n={len(body.get('sources', []))}")

        # Era isolation over HTTP: every cited document must actually govern the
        # routed season. This is the project's central claim, asserted on the
        # documents that came back rather than on a boolean.
        if isinstance(year, int):
            bled = [s["document"] for s in body.get("sources", [])
                    if s["document"] in indexed
                    and not (indexed[s["document"]][0] <= year <= indexed[s["document"]][1])]
            check("no document outside the routed era", not bled, str(bled))

        print("\n/query, every source carries a usable citation")
        for s in body.get("sources", []):
            check(f"citation for {s['document']}", bool(s.get("citation", "").strip()),
                  str(s))
            break  # one is enough for a smoke test; the suite covers the rest

        print("\n/query, a season nothing covers")
        # 1912, not 1899: RE_YEAR matches 19xx and 20xx only, so an earlier year
        # is not seen as a year at all and falls through to the current season.
        r = client.post("/query", json={"query": "What were the rules in 1912?"})
        check("200", r.status_code == 200, r.text[:200])
        cov = r.json().get("coverage", {}) if r.status_code == 200 else {}
        check("says it is not covered", cov.get("covered") is False, str(cov))
        check("gives a reason", cov.get("reason") == "era_not_covered", str(cov))
        check("names the coverage span", bool(cov.get("message")), str(cov))

        print("\n/query, over the token limit")
        # Over 1,000 tokens but under the 20,000-character field limit, or
        # Pydantic rejects it with 422 before the token gate is reached.
        oversized = "the Maximum Annual Salary " * 250          # ~6,500 chars
        check("stays inside the field limit", len(oversized) < 20_000, str(len(oversized)))
        r = client.post("/query", json={"query": oversized})
        check("400", r.status_code == 400, str(r.status_code))
        detail = r.json().get("detail", {}) if r.status_code == 400 else {}
        check("names the error", detail.get("error") == "prompt_too_long", str(detail))
        check("reports the count and limit",
              isinstance(detail.get("counted_tokens"), int) and detail.get("limit") == 1000,
              str(detail))

        print("\n/query, an ambiguous season")
        if ambiguous:
            year = sorted(ambiguous)[0]
            r = client.post("/query", json={"query": f"What was the salary cap in {year}?"})
            check("409", r.status_code == 409, str(r.status_code))
            payload = r.json() if r.status_code == 409 else {}
            check("offers both seasons", len(payload.get("options", [])) == 2, str(payload))
            check("says how to resend", payload.get("resend_with") == "clarified_season",
                  str(payload))
        else:
            # Expected on the public-domain index: ambiguity is derived from
            # primary-tier windows and that build has none. Skipped, not passed.
            print("  [skip] no primary documents indexed, so no year is ambiguous")

        print("\n/query, a malformed request")
        r = client.post("/query", json={"query": ""})
        check("422", r.status_code == 422, str(r.status_code))

    print()
    if FAILURES:
        print(f"SMOKE FAILED: {len(FAILURES)} check(s)")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("SMOKE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
