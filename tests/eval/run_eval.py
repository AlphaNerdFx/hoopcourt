#!/usr/bin/env python3
"""Retrieval and routing evaluation.

Answers the two questions the PRD asserts but never measures: does the router
send each query to the right ruleset, and does retrieval ever leak text from the
wrong era? Both are checkable without an LLM, so this runs offline and on CPU.

The temporal-isolation rate is the gate. CLAUDE.md sec.2.2 calls rule bleeding a
fatal system error, so anything below 100% exits non-zero.

    python tests/eval/run_eval.py --db nba_legal.db
    python tests/eval/run_eval.py --db nba_legal.db --category refusal --verbose
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.api.router import TemporalRouter, current_season  # noqa: E402
from src.db.connection import get_vector_db_connection  # noqa: E402
from src.db.schema import ambiguous_seasons  # noqa: E402
from src.db.search import retrieve_segmented_context  # noqa: E402
from src.ingest.embedder import Embedder  # noqa: E402
from src.model.generation import build_generator  # noqa: E402
from src.model.verify import verify_citations  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


class Result:
    def __init__(self, qid: str, category: str):
        self.qid, self.category = qid, category
        self.checks: dict[str, bool | None] = {}
        self.notes: list[str] = []

    def check(self, name: str, passed: bool, note: str = "") -> None:
        self.checks[name] = passed
        if not passed and note:
            self.notes.append(note)

    @property
    def passed(self) -> bool:
        return all(v for v in self.checks.values() if v is not None)


def evaluate(db_path: str, questions: list[dict], verbose: bool,
             generator=None) -> list[Result]:
    conn = get_vector_db_connection(db_path)
    indexed = {r["doc_name"] for r in conn.execute("SELECT doc_name FROM documents")}
    # The same set the API injects, so the eval exercises the real routing path.
    ambiguous = ambiguous_seasons(conn)
    embedder = Embedder()
    results: list[Result] = []

    for q in questions:
        r = Result(q["id"], q["category"])
        route = TemporalRouter.resolve_query_route(
            q["question"], q.get("clarified_season"), ambiguous
        )

        # ---- routing ----
        if "expect_route" in q:
            got, want = route["route_action"], q["expect_route"]
            r.check("route", got == want, f"route={got} want={want}")
        if "expect_year" in q:
            want = q["expect_year"]
            # "CURRENT" tracks the season in progress, so an unqualified question
            # keeps asserting the right thing after a season rollover instead of
            # silently rotting into a hardcoded year.
            if want == "CURRENT":
                want = current_season()
            got = route["target_year"]
            r.check("year", got == want, f"year={got} want={want}")
        if "expect_trigger" in q:
            got, want = route["trigger_keyword"], q["expect_trigger"]
            r.check("trigger", got == want, f"trigger={got} want={want}")

        # ---- retrieval ----
        needs_retrieval = any(
            k in q for k in ("expect_documents", "forbid_documents",
                             "expect_terms_any", "expect_empty",
                             "expect_terms_absent")
        )
        if needs_retrieval:
            emb = embedder.embed_query(q["question"])
            chunks = retrieve_segmented_context(conn, emb, route, k=5)
            got_docs = {c["document"] for c in chunks}

            if q.get("expect_empty"):
                r.check("refusal", not chunks,
                        f"expected no results, got {len(chunks)} from {sorted(got_docs)}")

            if "forbid_documents" in q:
                leaked = got_docs & set(q["forbid_documents"])
                r.check("no_bleed", not leaked, f"BLED FROM {sorted(leaked)}")

            if "expect_documents" in q:
                expected = set(q["expect_documents"])
                # Only judge documents that are actually in this index; a partial
                # build should report coverage, not fake failures.
                if not (expected & indexed):
                    r.checks["in_expected_docs"] = None
                    r.notes.append("expected docs not indexed - skipped")
                else:
                    stray = got_docs - expected
                    r.check("in_expected_docs", not stray and bool(chunks),
                            f"unexpected {sorted(stray)}" if stray else "no results")

            if "expect_terms_absent" in q:
                # Once an era has any coverage, retrieval always returns its
                # nearest rows, so "returns nothing" stops being a usable test
                # for an anachronism. What still holds is that the corpus has no
                # text about a rule that did not exist yet: asking about the
                # luxury tax in 1975 may surface 1970s chunks, but none of them
                # may actually be about a luxury tax.
                blob = " ".join(c["text"].lower() for c in chunks)
                present = [t for t in q["expect_terms_absent"] if t.lower() in blob]
                r.check("no_anachronism", not present,
                        f"anachronistic term(s) surfaced: {present}")

            if "expect_terms_any" in q and not q.get("expect_empty"):
                terms = [t.lower() for t in q["expect_terms_any"]]
                blob = " ".join(c["text"].lower() for c in chunks)
                if not chunks and "expect_documents" in q and \
                        not (set(q["expect_documents"]) & indexed):
                    r.checks["recall"] = None
                else:
                    r.check("recall", any(t in blob for t in terms),
                            f"none of {q['expect_terms_any']} in top-5")

            # Generation is measured separately from retrieval, because they
            # fail differently and have different fixes. Retrieval can hand over
            # five correct chunks and the model still invent a pinpoint.
            if generator is not None and chunks:
                # A backend failure is recorded against the question, not raised.
                # One request timing out during a cold model load used to abort
                # the whole run and discard every result already gathered.
                try:
                    answer = generator.generate(q["question"], chunks, route,
                                                style="scholar")
                except Exception as exc:
                    r.check("citations", False,
                            f"generation failed: {type(exc).__name__}")
                else:
                    cite = verify_citations(answer, chunks)
                    r.check("citations", cite.ok,
                            f"fabricated {cite.fabricated}" if cite.fabricated
                            else "answer cited nothing")
                    if verbose:
                        r.notes.append(f"answer: {answer[:200]}")

            if verbose:
                r.notes.append("retrieved: " + (", ".join(
                    f"{c['document']}(p{c['page']},d={c['distance']:.3f})"
                    for c in chunks) or "<nothing>"))
        results.append(r)
    return results


def report(results: list[Result]) -> int:
    by_cat: dict[str, list[Result]] = collections.defaultdict(list)
    for r in results:
        by_cat[r.category].append(r)

    print(f"\n{'CATEGORY':<22}{'PASS':>7}{'TOTAL':>7}   RATE")
    print("-" * 52)
    for cat in sorted(by_cat):
        rs = by_cat[cat]
        p = sum(1 for r in rs if r.passed)
        print(f"{cat:<22}{p:>7}{len(rs):>7}   {100*p/len(rs):5.1f}%")
    total_pass = sum(1 for r in results if r.passed)
    print("-" * 52)
    print(f"{'OVERALL':<22}{total_pass:>7}{len(results):>7}   "
          f"{100*total_pass/len(results):5.1f}%")

    def rate(name: str) -> tuple[int, int]:
        vals = [r.checks[name] for r in results if r.checks.get(name) is not None]
        return sum(vals), len(vals)

    print("\nper-check:")
    for name in ("route", "year", "trigger", "no_bleed", "in_expected_docs",
                 "recall", "refusal", "no_anachronism", "citations"):
        ok, n = rate(name)
        if n:
            print(f"  {name:<18} {ok:>3}/{n:<3}  {100*ok/n:5.1f}%")

    failures = [r for r in results if not r.passed]
    if failures:
        print(f"\n{len(failures)} failing:")
        for r in failures:
            bad = [k for k, v in r.checks.items() if v is False]
            print(f"  [{r.category}] {r.qid}: {', '.join(bad)}")
            for note in r.notes:
                print(f"      {note}")

    bleed_ok, bleed_n = rate("no_bleed")
    print()
    if bleed_n and bleed_ok < bleed_n:
        print(f"GATE FAILED: temporal isolation {100*bleed_ok/bleed_n:.1f}% "
              f"({bleed_n - bleed_ok} query/queries leaked across eras).")
        return 1
    if bleed_n:
        print(f"GATE PASSED: temporal isolation 100% across {bleed_n} queries.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="nba_legal.db")
    ap.add_argument("--questions", type=Path,
                    default=ROOT / "tests" / "eval" / "questions.yaml")
    ap.add_argument("--category")
    ap.add_argument("--id", action="append", dest="ids", metavar="QUESTION_ID",
                    help="run only these question ids; repeatable. Generation "
                         "is deterministic, so re-running the handful of "
                         "questions a backend restart cost is exact rather "
                         "than an approximation of the full run.")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--with-generation", action="store_true",
                    help="also generate answers and verify their citations")
    args = ap.parse_args()

    if not Path(args.db).exists():
        print(f"index not found: {args.db}\nrun: python scripts/build_index.py "
              f"--db {args.db}", file=sys.stderr)
        return 2

    questions = yaml.safe_load(args.questions.read_text(encoding="utf-8"))["questions"]
    if args.category:
        questions = [q for q in questions if q["category"] == args.category]
    if args.ids:
        wanted = set(args.ids)
        questions = [q for q in questions if q["id"] in wanted]
        missing = wanted - {q["id"] for q in questions}
        if missing:
            print(f"no such question id: {', '.join(sorted(missing))}",
                  file=sys.stderr)
            return 2
    generator = None
    if args.with_generation:
        generator = build_generator()
        if generator is None:
            print("no generation backend installed; "
                  "pip install -r requirements-local.txt", file=sys.stderr)
            return 2
        print(f"generation backend: {generator.name}")

    if not questions:
        print("no questions selected", file=sys.stderr)
        return 2
    print(f"evaluating {len(questions)} questions against {args.db}")
    return report(evaluate(args.db, questions, args.verbose, generator))


if __name__ == "__main__":
    raise SystemExit(main())
