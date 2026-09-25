# Branches, pull requests and the merge gates

`master` is protected. Nothing is pushed to it directly; every change arrives as
a pull request that has passed the checks below. This file says what each gate
measures, why it exists, and how to move a threshold deliberately when a change
earns it.

## The loop

```
git switch -c <topic>          # branch from master
# work, commit
git push -u origin <topic>
gh pr create --fill            # or open it in the browser
# checks run; merge when they are green
```

Branch names are not enforced. Commit messages stay under 256 characters and
brief, per [CODE_REVIEW.md](CODE_REVIEW.md).

## What runs on every pull request

| Check | Workflow | Blocks a merge | What it measures |
| --- | --- | --- | --- |
| Lint and test (py3.10, py3.12) | `ci.yml` | yes | `ruff`, then the full offline suite on both supported interpreters |
| Corpus and timeline integrity | `ci.yml` | yes | The manifest and timeline parse, and every timeline claim is attributable |
| Integration, eval and smoke | `pr.yml` | yes | Builds a public-domain index, runs the 45-question evaluation, then drives the assembled API |
| Benchmark (base vs head) | `pr.yml` | yes | Seven hot paths, measured on both commits on the same runner |
| Mutation (changed files) | `pr.yml` | **no, advisory** | How many mutants of the files this branch changed survive the suite |

### Integration, eval and smoke

Three things in one job because they share an index build.

* `scripts/fetch_opinions.py` then `build_index.py --db ci.db --tier judicial`.
  Court opinions and the curated timeline are the only sources CI may lawfully
  fetch, and they are exactly what covers pre-1995.
* `tests/eval/run_eval.py` runs the whole suite. **Temporal isolation is the
  gate and exits non-zero below 100%.** Questions whose documents are absent
  from a public-domain index are skipped rather than failed, because a log full
  of expected failures teaches people to ignore failures.
* `scripts/smoke_test.py` drives the assembled FastAPI app and asserts the
  things only the HTTP surface can get wrong: status codes, the `coverage`
  object, the 409 for an ambiguous season, the 400 from the token gate, and that
  no returned document falls outside the routed era.

### Benchmark

`scripts/benchmark.py` times seven paths this project owns: routing, query
shaping, alias expansion, chunking, the pre-filtered vector search, citation
verification and boundary derivation. It deliberately does **not** time the
embedding model. That is the dominant cost of a real request, and it is a
third-party tensor op whose runtime on a shared runner moves by more than any
regression this gate is meant to catch, so including it would measure the runner
rather than the change. Nothing in the benchmark imports torch, which is also
why the job installs three packages and finishes in seconds.

Two properties make a percentage gate defensible here:

* **Base and head are measured in the same job, on the same runner, minutes
  apart.** Absolute nanoseconds from different jobs are not comparable; a
  ratio measured back to back cancels almost all machine variance.
* **The gate reads the fastest round, not the mean.** Benchmark noise is
  one-sided: nothing makes a loop finish faster than the machine can run it, so
  the minimum is the least contaminated estimate. Iteration counts are sized so
  each round lands near 90ms, because a percentage over a microsecond operation
  measures the scheduler.

Measured run-to-run drift on the minimum is under about 11%, so the default
**30%** threshold has roughly three times the headroom it needs.

#### Moving the threshold

The 30% default is not sacred, and the right number depends on the size of the
change. A refactor touching one function should not slow anything; a feature
that adds a genuine stage to the pipeline may cost real time and still be worth
merging.

Raise it for a single pull request by adding a label:

```
perf-allow:50
```

The label is read through the environment and validated as a number, never
interpolated into a shell command. It is deliberately visible on the pull
request rather than hidden in a commit, so the decision is reviewable: **say in
the description what got slower and why it is worth it.** To change the default
for every pull request, edit `DEFAULT_THRESHOLD_PCT` in `.github/workflows/pr.yml`.

A regression that is real and not worth paying for is a blocked merge. Optimise
it, or split the slow part out of the branch.

### Mutation, and why it does not block

A passing test is evidence only if some realistic change would make it fail.
Three checks in this project could not fail: four recall terms that appeared in
up to 95% of the expected document, a routing guard phrased to avoid the cue
that actually misroutes, and an `assert report.ok` that was true because nothing
had been extracted. So the suite gets mutated.

The job mutates only the files the branch changed, uses the coverage map to skip
mutants on lines no test executes, and is time-boxed. It **reports** and does
not block, for one honest reason: the absolute score is low. On
`src/api/tokens.py`, 48 mutants, 10 killed and 31 survived. Any budget strict
enough to be useful would block every pull request today, and a gate that is
always red gets switched off.

Read it as a prompt, not a verdict: a surviving mutant on a line you just wrote
is a test worth adding.

Tooling note: `mutmut` is pinned to **2.5.1**. Version 3.x asserts internally
that module names do not begin with `src.`, which every import in this
repository does.

## Branch protection

`master` requires a pull request, and the four blocking checks above must pass.
Force pushes and deletion are refused. Re-apply or inspect the rules with:

```
gh api repos/:owner/:repo/rulesets
```

## When a gate is wrong

Gates are code and can be defective. If a check fails and you believe the change
is sound, the order is: reproduce it locally, then fix the gate in its own pull
request rather than working around it. `scripts/benchmark.py` and
`scripts/smoke_test.py` both run locally with no arguments beyond `--db`.
