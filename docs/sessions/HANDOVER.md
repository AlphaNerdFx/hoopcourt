# Session handover: v1.0.0 shipped and public

Written 2026-09-22, immediately after the repository went public. Overwrites the
previous handover. `docs/ai/HANDOVER.md` is the separate cold-start document for
someone new to the architecture and is still accurate.

## Repository state

| | |
| --- | --- |
| Branch | `master`, in sync with `origin/master` |
| HEAD | `965da11` Add post-1.0.0 handover |
| Working tree | clean, 0 uncommitted |
| Tags | `v0.1.0`, `v0.9.0`, **`v1.0.0` at `c3fa3f0`, pushed** |
| Visibility | **PUBLIC** |
| Repo | https://github.com/AlphaNerdFx/hoopcourt |
| Release | https://github.com/AlphaNerdFx/hoopcourt/releases/tag/v1.0.0, published, not a prerelease |
| Wiki | 7 pages live |
| Dataset | https://huggingface.co/datasets/AlphaNerdFx/hoopcourt-eval, public |
| Commercial repo | `AlphaNerdFx/era-engine`, **private and must stay so** |

## `make check` status

Run at handover time. Nothing is known-broken.

* `ruff check src scripts tests` — exit 0
* `pytest tests/ -q` — exit 0, **461 collected**, 1 skipped (opt-in network
  test), 3 xfail (deliberate, `tests/test_timeline_sources.py`)
* `run_eval.py --db nba_legal.db` — exit 0, **45/45**, temporal isolation 100%
  across 25 queries
* `audit_corpus.py` — clean, 3,385 PDF pages and 107 text blocks
* CI green on `master`; the `Release` workflow succeeded end to end

## Completed this session

* `031baad` **Proved the llama-cpp backend**, which D21 had only claimed in
  prose. `llama-cpp-python` compiles here with no system cmake, scikit-build-core
  fetches it into build isolation. With ollama pointed at a refused port,
  `build_generator("local")` returns a local backend rather than `None`, loads a
  real GGUF and answers from retrieved chunks. Also wrote the 1.0.0 changelog
  section. **Caveat recorded there and worth repeating: that answer carried zero
  citations.** A 0.5B smoke-test model is far weaker than the `mistral:7b` every
  published figure was measured against. The backend path is proven, the model is
  not endorsed.
* `66a28da` Marked the release checklist. The llama-cpp box had been ticked on
  09-21 on a prose claim that left no artifact.
* `4eb4069` **Fixed the release workflow, which had never once succeeded.**
  Pushing the tag ran it for the first time and it failed at exit 2: the job
  generated `--only "Haywood v. NBA (U.S. 1971)"` inside a shell command
  substitution, and a shell does not re-parse quotes it produced itself, so every
  document name word-split into unrecognised arguments. `build_index.py` now
  takes `--tier`, one token that cannot split.
* `965da11` This handover's predecessor.

Outside the repository: published the wiki (7 pages), created and published the
Hugging Face dataset, and flipped the repository public after a final audit
(124 tracked files, zero corpus, zero secret-shaped strings, transcript absent
from all history).

## In progress

**Nothing.** No edits are mid-flight, no background jobs are running, the tree is
clean and everything is pushed.

## Background jobs

**None.** Temporary artefacts from this session were cleaned except
`/tmp/llamaverify` (1.4 GB), which is the virtualenv that proved the local
backend. It is disposable; `docs/project/TESTING.md` carries the recipe to
rebuild it. `/tmp` does not survive a WSL restart, so do not rely on it.

## Open decisions needing input

1. **PyPI is unclaimed, deliberately, and I advise leaving it.** There is no
   reservation mechanism, so claiming `hoopcourt` means uploading a real
   distribution, and `pyproject.toml` states the project is not packaged for
   PyPI because the index must be built from documents the user fetches. A stub
   would make `pip install hoopcourt` appear to work and then fail, permanently,
   since PyPI never allows reuse of a deleted version. Package it properly if
   that ever makes sense; the name may be gone by then, which is the cheaper
   loss.
2. **A Hugging Face *model* repo was not created.** D15 and Phase C say the
   fine-tune is not justified (one invented citation per 26 questions is not a
   knowledge gap), so it would sit empty indefinitely.
3. **`era-engine` is a working name.** `gh repo rename` costs one command.
4. Unresolved review judgement calls, none of them defects: two commit bodies
   exceed the documented 256-character limit; `n_gpu_layers` is uncovered by any
   test; `fake_hub` and `fake_llama_cpp` are misleading fixture names.

## Now that the repository is public

* CI is unmetered, so the weekly upstream check costs nothing.
* Anything that leaks is harvested within minutes. The `.gitignore` entries for
  `data/`, `*.pdf`, `*.db` and `internal/` are now load-bearing rather than
  precautionary. **Never `git add -A` without looking**; that is exactly how a
  copyrighted transcript reached history and had to be purged.
* The GitHub wiki is independently editable, and the source of truth is `wiki/`
  in this repository. Edit it here and push, or the two will drift.

## Next work, in the plan's order

`v1.1.0` is the multi-conversation UI. The design is in
`/home/youssef/.claude/plans/read-all-files-in-swift-ember.md`; these are the
constraints, each of which exists to protect the isolation gate:

* History lives in a **separate** `hoopcourt_chat.db`, never in `nba_legal.db`,
  because `scripts/build_index.py` owns that file and a rebuild must not destroy
  user data.
* History is evicted **before** retrieved chunks, never the reverse.
* A bare follow-up **inherits** the conversation's era. That is correctness, not
  convenience: without it "what about the luxury tax?" inside a 1999 thread
  routes to the current season and answers from the 2023 CBA.
* Every turn retrieves fresh. Unioning earlier turns' chunks is rule bleeding
  assembled by the conversation layer.
* Temperature is exposed in Casual Fan mode only, capped, Legal Scholar pinned at
  0.0, carried as a schema CHECK constraint rather than a handler.

Then v1.2.0 corpus expansion, v1.3.0 statistics by SQL (D14).

## Known-weak spots, ranked

1. **`tests/test_local_backend.py` fakes `llama_cpp` and `huggingface_hub` as
   modules**, so it passes with neither installed. Deliberate, since CI cannot
   install them, but it means the backend's *success* is only ever proven by the
   manual gate in `docs/project/TESTING.md`. Re-run it before any release
   touching `src/model/generation.py`.
2. **`hf_hub_download` has no `revision=` pin.** A security review found no
   exploitable issue in the v1.0.0 diff but flagged this as real supply-chain
   exposure: a compromise of `Qwen/Qwen2.5-7B-Instruct-GGUF` yields a GGUF that
   `llama_cpp` loads. Predates this release.
3. **`release.yml:37`** interpolates `github.event.inputs.tag` into a shell
   command. Pre-existing, write-access gated. Move it to `env:`.
4. **Citation verification cannot see relevance.** It proves a citation came
   from the supplied context, never that the passage answers the question. A 1998
   query once verified 3/3 while answering for the 1997-98 season.

## Rules that each cost a real defect here

* **Verify the command production runs, not one shaped like it.** The release
  workflow failed because its command had been checked locally through `eval`,
  which re-parses quotes where CI does not.
* **A test that cannot fail is a defect.** Mutation-test anything claiming to
  verify a feature.
* **Assert the observation, not the verdict.** `assert report.ok` passed for a
  citation being silently discarded, because `ok` is true when nothing was
  extracted.
* **A generation figure is a range and carries its style.** Not reproducible at
  temperature 0 here; three runs minimum.
* **Measurement runs need the machine alone.** ~7.4 GB usable on this WSL2 guest,
  not the 16 GB the hardware profile claims.
* **Check exit codes directly.** `pytest ... | tail` returns tail's status.
* **`pgrep -f "X"`** inside a loop whose own command contains `X` matches itself
  and never exits.

## Suggested skills

`professor` fires on its own and the owner wants teaching during development,
expansively. `code-review` before any tag, two axes against the last release tag.
`security-review` before anything that changes public surface. `commit`,
`diagnosing-bugs`, `handover`.
