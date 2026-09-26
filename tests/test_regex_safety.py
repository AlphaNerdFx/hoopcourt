"""No regular expression in the request path may blow up on hostile input.

Catastrophic backtracking turns a pattern that is linear on ordinary text into
one that is exponential on a crafted string, and Python's `re` has no timeout:
a request that hits one does not fail, it hangs, holding a worker until
something kills the process.

Three groups of these patterns sit on genuinely reachable input. The router's
run on the user's query. The verifier's run on generated answer text, which is
shaped by both the question and the retrieved chunks. The extractor's run on
document text. None is behind an authenticated boundary.

Two design notes, because both were got wrong first:

* The patterns are DISCOVERED from the modules, not listed, so a regex added
  tomorrow is covered without anyone remembering. A hand-kept list would go
  stale exactly the way the ambiguous-year count did.
* The sweep runs in a SUBPROCESS with a timeout. An in-process version cannot
  fail on the case it exists for: `re` does not release the GIL and does not
  poll for signals, so a truly catastrophic pattern hangs the test runner
  instead of failing it. A guard whose failure mode is the symptom it guards
  against is not a guard.

    python tests/test_regex_safety.py --sweep    # what the subprocess runs
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.api import router as router_mod  # noqa: E402
from src.ingest import chunker as chunker_mod  # noqa: E402
from src.model import verify as verify_mod  # noqa: E402
from src.parser import extract as extract_mod  # noqa: E402

# Generous on purpose. Catastrophic backtracking is exponential, so a pattern
# that is going to fail takes minutes. A wide budget cannot flake on a loaded
# runner while still catching the real thing.
BUDGET_SECONDS = 2.0
SWEEP_TIMEOUT = 120
N = 2_000

HOSTILE = [
    "[" * N,
    "[" + "a" * N,
    "[" + "[a]" * N,
    "[" + "]" * N,
    "[" + "p. " * N,
    "[" + "," * N + "p. 1",
    " " * N + "*" * N + " " * N + "source",
    "*_#" * N + "sources",
    "Sources:" + " " * N,
    "9" * N,
    "1" * N + "-" * N,
    "Section " + "9" * N + ".",
    "ARTICLE " + "I" * N,
    "A" * N + "-\n" + "B" * N,
    ("p. 1, " * N) + "p.",
    "a" * N + "!",
    ("–" * N) + "p. 1",
]


def compiled_patterns() -> list[tuple[str, re.Pattern]]:
    """Every compiled pattern reachable as a module attribute, with its name."""
    found = []
    for mod in (router_mod, verify_mod, extract_mod, chunker_mod):
        for attr in dir(mod):
            value = getattr(mod, attr)
            if isinstance(value, re.Pattern):
                found.append((f"{mod.__name__}.{attr}", value))
    return sorted(found)


def _timed(fn) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def _check(label: str, fn, budget: float = BUDGET_SECONDS) -> str | None:
    """Run fn, return a failure string if it took longer than the budget."""
    elapsed = _timed(fn)
    if elapsed >= budget:
        return f"{label} took {elapsed:.3f}s, over a {budget}s budget"
    return None


def sweep() -> int:
    """Run every check, printing each name BEFORE it runs.

    Printing first is what makes a timeout diagnosable: if the subprocess is
    killed, the last line of its output names the pattern that hung.
    """
    failures = []

    # Calibration: prove the harness FLAGS something over budget, before
    # trusting it to say nothing is. A plain linear scan against a deliberately
    # tiny budget does that without depending on how fast this machine is, and
    # without any backtracking that could hang.
    print("calibration: over-budget detection", flush=True)
    scan = lambda: re.compile("b").search("a" * 2_000_000)   # noqa: E731
    if _check("calibration", scan, budget=1e-6) is None:
        failures.append("calibration did not flag an over-budget check, so a "
                        "real one would not be flagged either")
    elif _check("calibration", scan) is not None:
        failures.append("the calibration scan exceeds the real budget on this "
                        "machine, so the sweep's timings cannot be trusted")
    else:
        print("  ok: flags over budget, passes under it", flush=True)

    patterns = compiled_patterns()
    for name, pattern in patterns:
        for i, probe in enumerate(HOSTILE):
            print(f"{name} [probe {i}]", flush=True)
            bad = _check(f"{name} on a {len(probe)}-char input starting "
                         f"{probe[:40]!r}", lambda p=pattern, s=probe: p.search(s))
            if bad:
                failures.append(bad)

    # The end-to-end surfaces, not just patterns in isolation.
    print("verify_citations on a hostile answer", flush=True)
    hostile_answer = (
        "[" * 500
        + "[2023 NBA CBA, " + "p. 1, " * 500 + "p. 2]"
        + "Sources:" + " " * 500 + "\n"
        + "- [" * 500
        + "–" * 500
    )
    context = [{"document": "2023 NBA CBA", "article": "II", "section": "7",
                "page": 60, "source_tier": "primary", "text": "x"}]
    report = None

    def _verify():
        nonlocal report
        report = verify_mod.verify_citations(hostile_answer, context)

    bad = _check("verify_citations on a hostile answer", _verify)
    if bad:
        failures.append(bad)
    # Assert the observation: a crafted answer must not report itself clean by
    # making the extractor lose track of what it found.
    if report.total != len(report.supported) + len(report.fabricated):
        failures.append("verify_citations returned an inconsistent report")

    print("router on a hostile query", flush=True)
    for probe in ("9" * 20_000, "coin flip " * 2_000,
                  "ARTICLE " + "I" * 20_000, " " * 20_000 + "2011"):
        route: dict = {}

        # Both the probe and the result dict are bound as defaults rather than
        # captured: a closure over a loop variable reads its LAST value, which
        # would silently make this check test one probe four times.
        def _route(p=probe, out=route):
            out.update(router_mod.TemporalRouter.resolve_query_route(p, None, {2011}))

        bad = _check(f"router on {probe[:30]!r}", _route)
        if bad:
            failures.append(bad)
        if route.get("route_action") not in {
                "strict_season_filter", "require_season_clarification",
                "historical_keyword_override", "default_modern"}:
            failures.append(f"router returned {route.get('route_action')!r}")

    print(f"\nchecked {len(patterns)} patterns x {len(HOSTILE)} probes", flush=True)
    if failures:
        print("\nFAILURES:", flush=True)
        for f in failures:
            print(f"  {f}", flush=True)
        return 1
    print("all within budget", flush=True)
    return 0


# ---------------------------------------------------------------------------
# The pytest surface
# ---------------------------------------------------------------------------

def test_the_discovery_actually_found_the_patterns():
    """Guards the guard. If an import moved, the sweep would test nothing and
    keep reporting success, which is the failure mode this project has hit
    three times already."""
    names = {n for n, _ in compiled_patterns()}
    assert len(names) >= 10, f"only found {len(names)}: {sorted(names)}"
    # The two carrying nested quantifiers, which are the ones worth naming.
    assert "src.model.verify.RE_BRACKETED" in names
    assert "src.model.verify.RE_SOURCES_HEADING" in names


def test_no_pattern_backtracks_catastrophically():
    """Run the sweep out of process, so a hang becomes a failure.

    On timeout the last line of captured output names the pattern that did not
    return, which is the only thing that makes a hang debuggable.
    """
    try:
        proc = subprocess.run(
            [sys.executable, str(Path(__file__)), "--sweep"],
            capture_output=True, text=True, timeout=SWEEP_TIMEOUT, cwd=ROOT)
    except subprocess.TimeoutExpired as exc:
        tail = (exc.stdout or b"").decode(errors="replace").strip().splitlines()
        last = tail[-1] if tail else "<no output>"
        raise AssertionError(
            f"the regex sweep did not finish in {SWEEP_TIMEOUT}s. The last "
            f"check started was: {last}. A pattern that never returns is "
            f"catastrophic backtracking, and on the request path that is a hung "
            f"worker rather than an error.") from exc
    assert proc.returncode == 0, (
        f"regex sweep reported a problem:\n{proc.stdout[-2000:]}\n{proc.stderr[-500:]}")


if __name__ == "__main__":
    if "--sweep" in sys.argv:
        raise SystemExit(sweep())
    raise SystemExit("pass --sweep to run the checks")
