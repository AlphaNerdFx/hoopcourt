#!/usr/bin/env python3
"""Compare two benchmark runs and fail when one regressed past the threshold.

Both runs must come from the SAME machine in the same job. Absolute nanoseconds
from a shared CI runner are not comparable across jobs: runner classes, noisy
neighbours and CPU model all move them by more than the threshold. Comparing a
base checkout against the head checkout back to back cancels almost all of that,
which is what makes a percentage gate defensible here.

    python scripts/compare_benchmarks.py base.json head.json --threshold-pct 30
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

DEFAULT_THRESHOLD_PCT = 30.0
# Below this, a percentage is scheduler noise rather than a measurement. The
# benchmark script sizes its iteration counts to stay well above it; a case that
# falls under it is reported and not gated.
MIN_MEANINGFUL_NS = 1_000.0


def load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("benchmarks", {})


def compare(base: dict, head: dict, threshold_pct: float) -> tuple[list, list, list, list]:
    regressions, improvements, steady, unmatched = [], [], [], []
    for name in sorted(set(base) | set(head)):
        if name not in base:
            unmatched.append((name, "new in this branch, not gated"))
            continue
        if name not in head:
            unmatched.append((name, "removed in this branch, not gated"))
            continue
        b, h = base[name]["min_ns"], head[name]["min_ns"]
        if b < MIN_MEANINGFUL_NS or h < MIN_MEANINGFUL_NS:
            unmatched.append((name, f"under {MIN_MEANINGFUL_NS:,.0f} ns, too small to gate"))
            continue
        pct = 100.0 * (h - b) / b
        row = (name, b, h, pct)
        if pct > threshold_pct:
            regressions.append(row)
        elif pct < -threshold_pct:
            improvements.append(row)
        else:
            steady.append(row)
    return regressions, improvements, steady, unmatched


def markdown(regressions, improvements, steady, unmatched, threshold_pct) -> str:
    out = [f"### Benchmark: base vs head (threshold {threshold_pct:g}% slower)", ""]
    rows = regressions + improvements + steady
    if rows:
        out += ["| Benchmark | Base | Head | Change | |",
                "| --- | ---: | ---: | ---: | :-- |"]
        for name, b, h, pct in sorted(rows, key=lambda r: -r[3]):
            mark = "**REGRESSION**" if pct > threshold_pct else ("faster" if pct < -threshold_pct else "ok")
            out.append(f"| `{name}` | {b:,.0f} ns | {h:,.0f} ns | {pct:+.1f}% | {mark} |")
        out.append("")
    for name, why in unmatched:
        out.append(f"- `{name}`: {why}")
    if unmatched:
        out.append("")
    if regressions:
        out.append(f"**{len(regressions)} benchmark(s) regressed past {threshold_pct:g}%.** "
                   "Optimise, or raise the threshold deliberately for this PR with a "
                   "`perf-allow:<pct>` label and say why in the description.")
    else:
        out.append(f"No benchmark regressed past {threshold_pct:g}%.")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("base", type=Path)
    ap.add_argument("head", type=Path)
    ap.add_argument("--threshold-pct", type=float,
                    default=float(os.environ.get("BENCH_THRESHOLD_PCT",
                                                 DEFAULT_THRESHOLD_PCT)))
    ap.add_argument("--summary", type=Path, help="append the markdown table here")
    args = ap.parse_args()

    regressions, improvements, steady, unmatched = compare(
        load(args.base), load(args.head), args.threshold_pct)
    report = markdown(regressions, improvements, steady, unmatched, args.threshold_pct)
    print(report)
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write(report + "\n")
    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
