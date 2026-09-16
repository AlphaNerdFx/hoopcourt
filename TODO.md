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
      - [ ] Create a virtualenv **without** system site packages, `pip install
            -r requirements.txt`, and confirm every entry point runs from it.
      - [ ] Follow README Quick start start to finish on a machine that has
            never built this, as a person who is not its author.
      - [ ] Launch the server and exercise every response shape by hand: a
            normal answer, a 409 ambiguous year, an uncovered era, a refusal,
            and a backend that is switched off mid-session.
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

## Phase A: Corpus expansion

Same manifest, same era windows, same tiers, same fetch-and-build posture. No new
architecture. Cheapest value per unit of work in the roadmap.

- [ ] Officiating: case book, points of emphasis, historical rulebook editions.
- [ ] League history: draft, expansion, franchise moves, labour disputes.
- [ ] Add a fourth `source_tier` (`historical_record`) rather than overloading
      `timeline`. Narrative record is not a curated claim.
- [~] Upgrade medium-confidence timeline entries where a court opinion can
      replace the league's published history. **The "8 of 21 qualify" estimate
      was wrong and is corrected here**: audited against the indexed opinions,
      only `aba-merger-completed` has any judicial coverage at all, and it does
      not support that entry's claims. Robertson v. NBA (1975) establishes that
      a merger was proposed and enjoined; the entry claims the 1976 completion,
      four named franchises and a dispersal draft, none of which a 1975 opinion
      can source. The other seven have zero judicial coverage: "territorial" in
      Robertson is antitrust market division, and "three point" is "the NBA
      argues three points".
- [ ] **Three timeline entries cite sources that do not support them.** Found by
      audit, pinned by `tests/test_timeline_sources.py` as xfail so the count can
      only go down. Each needs a human with network access; guessing a
      replacement URL is the failure this project exists to prevent.
      - `baa-nbl-merger` (1946-49, league formation) cites the draft-lottery page
      - `aba-merger-completed` (1976, ABA merger) cites the same lottery page
      - `shot-clock` says "Rule 7" and links to `rule-no-1-court-dimensions`
- [ ] `territorial-picks` is sourced to Wikipedia, the only non-primary source
      among 21. Acceptable only if no court record or official page exists for
      an extinct practice; say so in the summary if that is the finding.

After each document: temporal isolation must hold at 100%, and
`scripts/audit_corpus.py` must report no fused text.

---

## Phase B: Statistics, via SQL not RAG

Statistics are not a retrieval problem. See ROADMAP and DECISIONS D14.

- [ ] `scripts/fetch_stats.py` using `nba_api` (MIT), run by the user on their
      own machine. The client is MIT; the upstream data is not, and
      stats.nba.com publishes no bulk-data licence. Fetch-and-build, unchanged.
- [ ] `stats` table and a text-to-SQL engine over it.
- [ ] A classifier deciding documentary vs statistical, reusing `TemporalRouter`
      for season resolution.
- [ ] The response must say which engine answered. A number from a table and a
      quotation from the CBA carry different authority.

---

## Phase C: The fine-tune

**Not the next step.** MVP step 2 measured one invented citation per 26
questions for both candidate models; the rest of the strict failure count is
over-precision. Prompting is already exhausted for it: the scholar prompt
forbids appending sub-paragraph detail and gives `p. 57` vs `p. 57 (a)` as the
example, and mistral emitted `p. 57 (a)` anyway.

Cheaper things to try first, in order:

- [ ] Report a narrowed permitted citation as its own grounding state instead of
      calling it fabrication. The closed list is already in hand, so the system
      can distinguish "invented a document" from "added a subsection to a real
      citation" and say which. Do not rewrite the citation to make it pass, that
      launders the failure rather than reporting it.
- [ ] Measure a larger instruction-following model the same way.

Everything below stands if those fail. See
[docs/evaluation/GENERATION_MEASUREMENT.md](docs/evaluation/GENERATION_MEASUREMENT.md).

- [ ] Generate training pairs from **public-domain sources only**: the 7 court
      opinions, your own timeline entries, and synthetic Q&A derived from them.
      No CBA text. See DECISIONS D15 for why this boundary is not negotiable.
- [ ] QLoRA an Apache-2.0 base (Qwen2.5-7B-Instruct or Mistral-7B-Instruct).
- [ ] Evaluate against base plus closed-list prompt on the same 43 questions.
- [ ] **Ship only if it wins.** If it does not, publish the negative result;
      that is a useful finding and costs nothing to state.
- [ ] Publish the adapter (tens of MB, not tens of GB) under a permissive licence.

---

## Phase D: Dropped, tool not service

Decided: Hoopcourt is a tool people install, not a service anyone hosts.

That removes vLLM and llm-d from the roadmap entirely rather than deferring them,
since both exist to serve concurrent users and there are none. It also removes
the largest legal risk in the project: serving answers derived from copyrighted
text to the public would have inverted the fetch-and-build posture that every
other copyright decision rests on. A tool reading documents the user fetched
themselves does not.

See DECISIONS.md D17.

---

## Phase E: Contracts and cap, blocked

The *mechanics* already work from the indexed CBA: exceptions, aprons, cap holds.
What is missing is current per-team numbers, and the maintained sources are
commercial products whose data `DATA_SOURCES.md` rules out taking.

- [ ] Blocked pending a licensable feed. Do not scrape. Revisit only if the
      feature is redefined as "explain the mechanism", which already ships.

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
