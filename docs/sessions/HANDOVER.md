# Session handover

Written 2026-09-21. Supersedes nothing; `docs/ai/HANDOVER.md` is the older
cold-start document for a contributor new to the project and is still accurate
about architecture.

## Repository state

| | |
| --- | --- |
| Branch | `master`, in sync with `origin/master` |
| HEAD | `90ef57a` Act on the pre-merge review: make the backend failure visible |
| Working tree | clean, 0 uncommitted |
| Tags | `v0.1.0`, `v0.9.0`. **Both local only, deliberately unpushed** |
| Remotes | `origin` = github.com/AlphaNerdFx/hoopcourt, **private** |
| CI | green on `master`, py3.10 and py3.12 |

`make check` equivalent, run at handover time:

* ruff: exit 0
* pytest: exit 0, **461 collected**, 1 skipped (opt-in network test), 3 xfail
  (deliberate, see `tests/test_timeline_sources.py`)
* `run_eval.py`: exit 0, **45/45**, temporal isolation 100% across 25 queries

Nothing is known-broken.

## Completed this session

* `291c541` Measured the install footprint on a virtualenv built **without**
  system site packages, the first this project has ever had: 5.8 GB with 15
  NVIDIA packages by default, 1.4 GB with none using the CPU torch build. Both
  pass the evaluation. README Quick start carries the command.
* `388d43b` **D21.** `DEFAULT_LOCAL_FILE` named a GGUF file that has never
  existed, so the llama-cpp backend raised on every machine and `/health`
  reported `generator: null`, identical to a machine with no backend installed.
  Replaced by a quantisation plus `resolve_gguf_files`.
* `8a708d0` Covered the download path; dropped a test that restated its own
  fixture and could not fail.
* `79bea2b` Re-measured every published figure across the docs.
* `bb49604` **Corrected one of those re-measurements.** The page count was
  changed to 3,320 on the grounds that D3 had it right; D3 cites
  `scripts/audit_corpus.py`, which prints **3,385**. Verified twice.
* `90ef57a` Acted on a two-axis review run before tagging. Both axes reached the
  same defect from opposite directions: the backend diagnostic never reached an
  operator. Added a weekly upstream-drift workflow.

Also this session, outside the repo: created
github.com/AlphaNerdFx/era-engine (private) for the commercial product brief and
the internal roadmap, and purged a pasted transcript containing verbatim corpus
text from git history with `git-filter-repo`, losing zero commits and leaving
both tags at their original SHAs.

## In progress

**Nothing is mid-edit.** The next step is a single gate.

### The one thing standing between here and v1.0.0

`requirements-local.txt`, the llama-cpp-python local GGUF backend, **is still
not proven by anything in the repository.**

* `tests/test_local_backend.py` fakes `llama_cpp` and `huggingface_hub` as
  modules, so it passes with neither installed.
* `.github/workflows/ci.yml` never installs `requirements-local.txt`.
* `venv/bin/python -c "import llama_cpp"` raises `ModuleNotFoundError`.

D21 made the *failure* visible. It did not make the *success* demonstrable.

Exact next step:

```bash
python3 -m venv /tmp/llamaverify            # NOT --system-site-packages
/tmp/llamaverify/bin/pip install --no-cache-dir torch \
    --index-url https://download.pytorch.org/whl/cpu
/tmp/llamaverify/bin/pip install --no-cache-dir -r requirements-local.txt
# then, with ollama unreachable, confirm the fallback actually loads:
NBA_OLLAMA_URL=http://127.0.0.1:1 NBA_GGUF_PATH=<a real .gguf> \
    /tmp/llamaverify/bin/python -c "..."
```

`llama-cpp-python` compiles from source and needs cmake and a C toolchain. **If
it cannot build on this machine, record that as a documented limitation rather
than leaving it unproven.** That honesty is the point: v1.0.0 was already tagged
once on a green suite and demoted.

Watch the memory. This host is WSL2 with ~7.4 GB usable, not the 16 GB the
hardware profile claims, and a pip install of multi-gigabyte wheels has already
been OOM-killed once. `--no-cache-dir` helps.

## Background jobs

**None running.** The background agent `4c6a077c` that produced `388d43b`
through `79bea2b` was stopped and removed (`claude rm 4c6a077c`); its worktree
is pruned and its branch `worktree-local-gguf-verify` is merged and deleted from
the remote.

## Open decisions needing input

1. **Tag v1.0.0 and push it.** Blocked on the llama-cpp gate above. Pushing a
   tag triggers `release.yml` against that tag's code; `v0.1.0` predates every
   fix here and its release run would fail, which is why neither existing tag is
   pushed.
2. **Flip the repository public.** `gh repo edit AlphaNerdFx/hoopcourt
   --visibility public`. The plan says at v1.0.0.
3. **Rename `era-engine`** if a better name arrives. It is a working title.
4. **Unresolved review findings**, all judgement calls rather than defects:
   commit bodies on `388d43b` and `79bea2b` run to 2,318 and 3,418 characters
   against the documented 256-character limit; `n_gpu_layers` is uncovered by
   any test; `fake_hub` / `fake_llama_cpp` are misleading names.

## Things that will bite the next session

Each cost real time here.

* `pgrep -f "X"` inside a loop whose own command contains `X` matches itself and
  never exits. Match a log marker instead.
* `pytest ... | tail` returns tail's exit code. This has already produced one
  commit containing a failing test.
* Generation is **not reproducible at temperature 0**. Report ranges over three
  runs minimum and always name the answer style.
* Measurement runs need the machine alone; concurrent load has both corrupted a
  measurement and triggered an OOM kill.
* Never `git add -A` without looking. That is how the copyrighted transcript
  reached history.
