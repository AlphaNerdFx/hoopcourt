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

- [ ] **Re-measure citation validity over all 43 questions.**
      The current prompt is the 8/10 closed-list version plus an untested
      anti-sub-paragraph rule; that exact combination has never been run.
      Warm the model first or the first request pays a 190s cold load.
      `python tests/eval/run_eval.py --db nba_legal.db --with-generation`
- [~] **Try other off-the-shelf models before assuming a fine-tune is needed.**
      `qwen2.5:7b-instruct` (Apache-2.0) pulled and compared against
      `mistral:7b`. On the 10-question subset both scored 7/10 with **zero
      overlap in which questions they failed**, which is what independent random
      failure looks like rather than a real difference. That subset cannot
      distinguish them. Re-running over all 43 questions for a larger sample
      before drawing any conclusion.
- [x] **Thin web UI**, single page served by the existing FastAPI app at `/`.
      Renders answer, sources with tier badges, timeline channel, coverage block
      and grounding result. No build step, no CDN, no package manager: a tool
      people install should not need npm to show its own output, and a CDN would
      break the offline mode this project is designed around.
      Building it exposed two concurrency bugs that only appear under load, see
      Known issues below.
- [ ] **State the citation number honestly in the README**, whatever it is.
- [ ] **Tag v1.0.0** and write the CHANGELOG section.

### Housekeeping before v1.0

- [ ] Push to GitHub; claim `hoopcourt` on Hugging Face and PyPI (both free).
- [ ] Push `wiki/` to the separate `.wiki.git` repo, see `wiki/README.md`.
- [ ] Replace `OWNER/REPO` placeholders if the repo path differs from
      `AlphaNerdFx/hoopcourt`.
- [ ] Resolve the `security@` contact in SECURITY.md, or drop it in favour of a
      GitHub private advisory. A disclosure channel that goes nowhere is worse
      than none.

---

## Phase A: Corpus expansion

Same manifest, same era windows, same tiers, same fetch-and-build posture. No new
architecture. Cheapest value per unit of work in the roadmap.

- [ ] Officiating: case book, points of emphasis, historical rulebook editions.
- [ ] League history: draft, expansion, franchise moves, labour disputes.
- [ ] Add a fourth `source_tier` (`historical_record`) rather than overloading
      `timeline`. Narrative record is not a curated claim.
- [ ] Upgrade medium-confidence timeline entries where a court opinion can
      replace the league's published history. 8 of 21 currently qualify.

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

Only if MVP step 2 shows off-the-shelf models cannot close the gap.

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

- [ ] `CBA 1995.pdf` carries OCR debris on a handful of pages (`30 --~;1`).
      Only the leading header line is stripped, so a second junk line can survive
      into chunk text. One document; stripping harder risks eating real text.
- [ ] The evaluation does not measure ranking quality *within* a document. A
      defect once fused 35% of CBA 2017 into noise and the suite still reported
      full marks. Run `audit_corpus.py` after touching any document.
- [ ] Generation eval is slow: a cold model load is 140-190s. Warm first.

## Decided, do not reopen without new evidence

- Torch stays on the current build. Ollama already runs on GPU through its own
  `cuda_v12` runtime; the driver mismatch affects PyTorch alone and the swap
  only speeds rare full rebuilds. See HANDOVER section 8.
- No OCR. All corpus documents have usable text layers (D3).
- Era filtering uses the vec0 metadata column, never the primary key (D2).
- Distribution is fetch-and-build. Nothing copyrighted is redistributed (D4).
