# Versioning

This project follows [Semantic Versioning](https://semver.org/). That standard
says what the digits mean in general. This document says what they mean *here*,
so a change can be classified without argument.

## The public contract

A version number only means something if there is a stated contract for it to
break. Ours is:

* The `POST /query` request and response shapes.
* The `GET /health` response shape.
* Documented CLI flags and their behaviour (`scripts/*.py`, `tests/eval/run_eval.py`).
* The database schema in `src/db/schema.py`.
* What a `source_tier` means (`primary`, `judicial`, `timeline`).
* What a citation means: a reference to a passage that was supplied as context.

Anything not on that list is internal and may change in a patch release.

## MAJOR, x+1.0.0

The contract breaks. A caller that worked before stops working, or keeps working
and now means something different.

* A response field removed, renamed, or changed type.
* A request field becoming required, or narrowing what it accepts.
* A schema change that requires rebuilding an existing index.
* A documented CLI flag removed or given different behaviour.
* The meaning of a source tier or a citation changing.
* Era coverage narrowing, so a question answerable before is refused now.

The second kind is the dangerous one. Silently changing what a citation asserts
is a breaking change even though every field keeps its name, because every
answer the system has ever given now means something else.

## MINOR, x.y+1.0

New capability, contract intact. Existing callers are unaffected.

* A new route, or a new optional request field.
* A new response field (the response model is `extra="forbid"` on construction,
  but adding a field does not break a reader).
* New corpus documents, or a new source tier.
* A new answer style.
* A new UI surface.
* Evaluation questions added or tightened such that reported numbers move.

That last case deserves its own note. Tightening the evaluation is a minor
release, not a patch, because the numbers in the README change even though no
code did. A reader comparing two releases must be able to see that the
measurement moved rather than the behaviour.

## PATCH, x.y.z+1

No contract change, and no reported number changes.

* Bug fixes that restore documented behaviour.
* Documentation, tests, refactors.
* Data corrections that do not alter the schema, such as fixing a timeline
  entry's source URL.
* Dependency bumps with no behavioural change.

## Pre-release, `-rc.N`

Any release whose gate includes a step CI cannot run. Today that means anything
touching generation, because CI has no GPU and no model. See
[TESTING.md](TESTING.md) for the manual gate.

`release.yml` marks a tag as a GitHub prerelease when it starts with `v0.` or
contains a hyphen.

## Release gates

These apply at every level. There is no version small enough to skip them.

1. **Temporal isolation at 100%.** `run_eval.py` exits non-zero below it. Rule
   bleeding is a correctness failure, not a quality metric, so a drop blocks a
   patch release exactly as hard as a major one.
2. **Suite green and ruff clean**, with the exit code checked directly.
   `pytest ... | tail` returns tail's status and has already produced one commit
   containing a failing test.
3. **A CHANGELOG section matching the version**, enforced by `release.yml`.
4. **Every changed measurement ships with its measurement.** A citation figure
   must state which answer style produced it and over how many runs, because
   generation is not reproducible on this stack and a single run is a sample.

## Why the project sat below 1.0.0 for so long

`CHANGELOG.md` recorded that versions stay below 1.0.0 until a generation
backend ships and the answer layer is measured rather than only the retrieval
layer. Both happened, and 1.0.0 was briefly tagged and then demoted, because
launching the application for the first time found three defects in ten minutes
and proved the documented install had never been performed by anyone.

1.0.0 asserts stability to other people. The lesson kept here: a green test
suite is not evidence that software runs.
