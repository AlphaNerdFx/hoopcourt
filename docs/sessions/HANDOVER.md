# Session handover: post-1.0.0

Written 2026-09-22, immediately after v1.0.0 shipped. Supersedes the previous
handover. `docs/ai/HANDOVER.md` remains the cold-start document for someone new
to the architecture and is still accurate.

## Repository state

| | |
| --- | --- |
| Branch | `master`, in sync with `origin/master` |
| HEAD | `4eb4069` Build the release index by tier, not by generated --only flags |
| Working tree | clean |
| Tags | `v0.1.0`, `v0.9.0`, **`v1.0.0` at `c3fa3f0`, pushed** |
| Release | https://github.com/AlphaNerdFx/hoopcourt/releases/tag/v1.0.0, published, not a draft, not a prerelease |
| Visibility | **PRIVATE.** Flipping it public was deliberately left to the owner |
| CI | green. `Release` workflow succeeded end to end for the first time |

Gate at release, all four green:

* ruff exit 0
* pytest exit 0, **461 collected**, 1 skipped (opt-in network test), 3 xfail
* `run_eval.py` exit 0, **45/45**, temporal isolation 100% across 25 queries
* `audit_corpus.py` clean, 3,385 PDF pages and 107 text blocks

Nothing is known-broken. Nothing is mid-edit. No background jobs are running.

## What shipped in 1.0.0

Read `CHANGELOG.md` for the full record; it is not duplicated here. The short
version is that 1.0.0 asserts the public contract is stable **and that the
documented install has been performed rather than assumed**. It was tagged once
during development and demoted, because launching the application for the first
time found three defects in ten minutes.

The last blocker, the optional llama-cpp backend, was verified on 2026-09-22
with a reproducible procedure rather than a prose claim. `DECISIONS.md` D21
carries the steps and `docs/project/TESTING.md` carries them as a standing
manual gate, because CI installs only `requirements.txt` and never can install
that one.

## Open decisions needing the owner

1. **Flip the repository public.**
   `gh repo edit AlphaNerdFx/hoopcourt --visibility public`. The approved plan
   says at 1.0.0. It was not done automatically: publishing is effectively
   permanent, and the goal that produced this release stopped at tag and push.
2. **Claim `hoopcourt` on Hugging Face and PyPI**, both free. `TODO.md`.
3. **Push `wiki/` to the separate `.wiki.git` repo**, see `wiki/README.md`.
4. **`era-engine`** (github.com/AlphaNerdFx/era-engine, private) holds the
   commercial brief and the internal roadmap. Rename it if a better name
   arrives; nothing depends on the current one.

## Next work, in the plan's order

The approved plan is `/home/youssef/.claude/plans/read-all-files-in-swift-ember.md`
if it still exists; the durable copy of its reasoning is in
`docs/architecture/DECISIONS.md` and `docs/project/VERSIONING.md`.

**v1.1.0 is the multi-conversation UI.** The full design is in the plan file and
is summarised by these constraints, each of which exists to protect the
isolation gate:

* Conversation history lives in a **separate** `hoopcourt_chat.db`, never in
  `nba_legal.db`, because `scripts/build_index.py` owns that file and a rebuild
  must not destroy user data.
* History is evicted **before** retrieved chunks, never the reverse. `n_ctx` is
  8192 and the citations depend on the passages.
* A bare follow-up **inherits** the conversation's era. This is a correctness
  feature, not a convenience: without it "what about the luxury tax?" inside a
  1999 thread routes to the current season and answers from the 2023 CBA.
* Every turn retrieves fresh. Unioning earlier turns' chunks is rule bleeding
  assembled by the conversation layer.
* Temperature is exposed in Casual Fan mode only, capped, with Legal Scholar
  pinned at 0.0. The schema carries that as a CHECK constraint, not a handler.

Then v1.2.0 corpus expansion, v1.3.0 statistics by SQL (D14). The fine-tune
(D15) remains unjustified: one invented citation per 26 questions is not a
knowledge gap.

## Known-weak spots, ranked

1. **`tests/test_local_backend.py` fakes `llama_cpp` and `huggingface_hub` as
   modules**, so it passes with neither installed. That is deliberate, since CI
   cannot install them, but it means the backend's *success* is only ever proven
   by the manual gate. Re-run it before any release that touches
   `src/model/generation.py`.
2. **`hf_hub_download` is called with no `revision=` pin.** A security review
   found no exploitable issue in the v1.0.0 diff, but flagged this as real
   supply-chain exposure: a compromise of `Qwen/Qwen2.5-7B-Instruct-GGUF` yields
   a GGUF that `llama_cpp` loads. It predates this release. Worth pinning.
3. **`release.yml:37`** interpolates `github.event.inputs.tag` into a shell
   command. Pre-existing and write-access gated. Move it to `env:`.
4. **The evaluation cannot see relevance.** `verify_citations` proves a citation
   came from the supplied context, never that the passage answers the question.
   A 1998 query once verified 3/3 while answering for the 1997-98 season.

## Rules that each cost a real defect

Every one of these was learned the expensive way in this project.

* **Verify the command production runs, not one shaped like it.** The release
  workflow failed on its first execution because its `--only "Doc Name (1971)"`
  flags were generated inside a command substitution, and a shell does not
  re-parse quotes it produced itself. It had been checked locally with `eval`,
  which does. Fixed by `--tier`, a token that cannot split.
* **A test that cannot fail is a defect.** Mutation-test anything claiming to
  verify a feature: remove the feature, confirm red.
* **Assert the observation, not the verdict.** `assert report.ok` passed for a
  citation that was being silently discarded, because `ok` is true when nothing
  was extracted.
* **A generation figure is a range and carries its style.** Not reproducible at
  temperature 0 here. Three runs minimum.
* **Measurement runs need the machine alone.** ~7.4 GB usable on this WSL2
  guest, not the 16 GB the hardware profile claims.
* **Check exit codes directly.** `pytest ... | tail` returns tail's status.
* **Never `git add -A` unchecked.** That is how a copyrighted transcript reached
  git history and had to be purged with `git-filter-repo`.
* **`pgrep -f "X"`** inside a loop whose own command contains `X` matches itself
  and never exits. Match a log marker.

## Suggested skills for the next agent

* `professor` fires on its own; the owner wants teaching during development,
  expansively, as a beginner in software and ML.
* `code-review` before any tag. Two axes, against the last release tag.
* `commit`, `diagnosing-bugs`, `security-review` before anything public.
* `handover` when the session ends.
