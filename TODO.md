# TODO

Working checklist. Scope and reasoning live in
[docs/project/ROADMAP.md](docs/project/ROADMAP.md); decisions and the evidence
behind them live in [docs/architecture/DECISIONS.md](docs/architecture/DECISIONS.md).
This file is the list, not the argument.

---

## MVP: v1.0

**The claim: an era-aware question answering system over NBA governing documents,
with verifiable citations, that a person can install and use.**

Nothing below this line is required to make that true.

- [x] **Re-measure citation validity over all 43 questions.** Done, and the
      old 8/10 did not generalise: that was the 10-question `grounded_citation`
      category, not the full sample. Over all 26 answerable questions mistral
      scores 14-18/26 strict across three runs. Retrieval is 100% on every
      check in every run.
      The measurement also showed generation is **not reproducible at
      temperature 0** on this stack, so the figure is a range, not a number.
      See [docs/evaluation/GENERATION_MEASUREMENT.md](docs/evaluation/GENERATION_MEASUREMENT.md).
- [x] **Try other off-the-shelf models before assuming a fine-tune is needed.**
      `mistral:7b` vs `qwen2.5:7b-instruct` over all 43 questions, paired.
      McNemar exact p = 0.34: **no detectable difference**, which is what the
      rule fixed before the run says to conclude rather than picking the higher
      score. They fail in opposite directions: mistral fabricated 5 citations
      and left 1 uncited, qwen fabricated 2 and left 8 uncited, declining on
      questions the corpus demonstrably covers.
      Classifying every fabrication against the exact context each model was
      handed: **one genuinely invented citation each across 26 questions**. The
      rest are a supplied citation narrowed to a subdivision. That is a
      formatting habit, not hallucinated law, and it does not justify Phase C.
- [x] **Thin web UI**, single page served by the existing FastAPI app at `/`.
      Renders answer, sources with tier badges, timeline channel, coverage block
      and grounding result. No build step, no CDN, no package manager: a tool
      people install should not need npm to show its own output, and a CDN would
      break the offline mode this project is designed around.
      Building it exposed two concurrency bugs that only appear under load, see
      Known issues below.
- [x] **State the citation number honestly in the README.** 14-18 of 26 across
      three runs, with the range, what it measures, and why it fell when
      retrieval improved.
- [x] Write the release CHANGELOG section. Tagged **v0.9.0**, not v1.0.0.
- [ ] **What 1.0.0 actually requires: a clean-checkout install.** v1.0.0 was
      briefly tagged on a green test suite and a green eval, without the
      application ever being launched. Launching it found three defects in ten
      minutes (`make serve` broken, `/query` 500 on a backend hiccup, and a
      virtualenv that resolves most dependencies from `~/.local`). Before 1.0.0:
      - [x] Create a virtualenv **without** system site packages, `pip install
            -r requirements.txt`, and confirm every entry point runs from it.
      - [x] Follow README Quick start start to finish on a machine that has
            never built this, as a person who is not its author.
      - [x] Launch the server and exercise every response shape by hand: a
            normal answer, a 409 ambiguous year, an uncovered era, a refusal,
            and a backend that is switched off mid-session.
      - [x] **`requirements-local.txt`, the llama-cpp backend.** Verified
            2026-09-21 on its own clean virtualenv: installs at exit 0, builds
            from sdist in ~7 minutes with no cmake on the host, 1.4 GB total
            with CPU torch and no CUDA packages. With Ollama pointed at a
            refused port, `build_generator` falls through to it, `/health`
            reports the loaded model and `/query` answers in 110-175s on CPU.
            It also found the defect in DECISIONS D21: the default model
            constant named a file that does not exist upstream, so this backend
            had never loaded for anyone who did not set `NBA_GGUF_PATH`.
      - [ ] Only then tag 1.0.0.

### Housekeeping before v1.0

- [ ] Push to GitHub; claim `hoopcourt` on Hugging Face and PyPI (both free).
- [ ] Push `wiki/` to the separate `.wiki.git` repo, see `wiki/README.md`.
- [x] `OWNER/REPO` placeholders replaced with `AlphaNerdFx/hoopcourt`.
      Change them if the repo lands elsewhere.
- [x] Resolved the `security@` contact: dropped in favour of the GitHub private
      advisory flow. The old address was at an unregistered domain with a
      placeholder GPG key, so a researcher using it would have believed they had
      notified someone.

---

## Where the roadmap went

Phases A through E moved to the commercial repository. They were candidate work,
not commitments, and this file now carries only what is true: known issues with
the evidence for each, and the concrete next steps.

The reason is a specific failure. This file carried the estimate "8 of 21
timeline entries qualify for a judicial upgrade" for weeks. Measurement
disproved it: only one entry has any judicial coverage, and that opinion predates
the claim it would have to support. Nothing marked it as an estimate. A file that
mixes intent with measurement teaches readers to distrust the measurements too.

See [docs/project/VERSIONING.md](docs/project/VERSIONING.md) for what ships when.

---

## Known issues

- [x] **The evaluation can now run Casual Fan mode**, via
      `run_eval.py --style casual`. First measurement: 10/12 on
      `grounded_citation`, against 9/12 for scholar on the same questions.
      Indistinguishable at n=12 on a non-reproducible stack; what it establishes
      is that casual is not worse, after a 100% failure rate that was invisible
      for the life of the project because nothing ran it.
- [ ] Run both styles over all 45 questions, repeated, before quoting a headline
      figure for either. A citation number without its style is incomplete.
- [x] "What is the Stepien Rule?" retrieved the Official Rulebook rather than
      the governing passage. Fixed by D19: colloquial names are expanded into
      the corpus's own language for retrieval only. The rule is in **NBA
      Constitution 2024 p85**, not the CBA. Two eval questions now cover it and
      fail 0/2 with the alias file removed.

- [~] `CBA 1995.pdf` carries OCR debris. **Standalone debris lines are now
      removed** anywhere on the page, not only in the header slot: 89 of its 432
      chunks carried one, now 0, and the document was rebuilt.
      **Inline debris remains** and is not being chased. Marks like `t_ iJ` and
      `.-- ~` sit inside lines that also carry real words, and every rule tight
      enough to catch them also drops `(a).`, which is the enumeration citations
      resolve against. Cosmetic residue is the better trade than a broken
      citation. Reopen only with a rule measured against the whole index.
- [ ] The evaluation does not measure ranking quality *within* a document. A
      defect once fused 35% of CBA 2017 into noise and the suite still reported
      full marks. Run `audit_corpus.py` after touching any document.
- [ ] Generation eval is slow: a cold model load is 140-190s. Warm first.
- [ ] Generation is not reproducible run to run, so a single eval pass is a
      sample. Repeat before trusting any generation figure. Retrieval is exact.
- [ ] On WSL2 the guest gets ~7.4GB, not the 16GB in the hardware profile.
      Ollama then loads weights without mmap and the OOM killer takes
      llama-server mid-run. Do not run the test suite during an eval.

## Decided, do not reopen without new evidence

- Torch stays on the current build. Ollama already runs on GPU through its own
  `cuda_v12` runtime; the driver mismatch affects PyTorch alone and the swap
  only speeds rare full rebuilds. See HANDOVER section 8.
- No OCR. All corpus documents have usable text layers (D3).
- Era filtering uses the vec0 metadata column, never the primary key (D2).
- Distribution is fetch-and-build. Nothing copyrighted is redistributed (D4).
