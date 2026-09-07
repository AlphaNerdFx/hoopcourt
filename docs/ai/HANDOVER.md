# Handover

Everything a new contributor, human or model, needs to pick this up cold.
Written 2026-09-07 at the end of the session that built the project.

---

## 1. What this is

Hoopcourt is an era-aware retrieval engine over NBA governing documents. Ask it
about 1975 and it answers from the rules in force in 1975, not from the 2023 CBA.

The problem it solves is rule bleeding: a general assistant asked about a 1997
trade will explain it using 2023 second-apron rules. Hoopcourt makes that
structurally impossible rather than unlikely. A query resolves to a season, the
season resolves to a set of documents, and the vector search is pre-filtered to
those documents before similarity is computed. Text from another era is never a
candidate.

Everything needed to run it is free and offline: local embeddings, a local
SQLite vector index, and an optional local LLM. No API key is required to
install, build, query or evaluate.

Licence MIT. Dependencies deliberately permissive throughout.

---

## 2. Current state

```
git       8 commits on master, tagged v0.1.0, nothing pushed, no remote
tests     273 passing, ruff clean
eval      43/43, temporal isolation 100% (the gate)
index     46 documents, 5,725 chunks, 0 orphaned vectors, 0.42% fused text
corpus    25 manifest documents, coverage 1964-2029, plus timeline from 1946
sources   all 25 source URLs verified reachable and correct
```

Index tiers: 18 primary, 7 judicial, 21 timeline.

Generation runs through Ollama on `mistral:7b`. Citation validity measured at
80% on the ten grounded-citation questions. See section 7, that number has a
history worth reading before you trust it.

---

## 3. How it works

### Request path

```
POST /query
  1. Token gate            src/api/tokens.py    >1,000 tokens -> 400
  2. Temporal router       src/api/router.py    query -> season
  3. Season -> doc ids     src/db/schema.py     start_season <= y <= end_season
  4. Pre-filtered KNN      src/db/search.py     two channels, see below
  5. Generation            src/model/           optional; absent is supported
  6. Citation check        src/model/verify.py  runtime grounding block
```

### The three mechanisms that matter

**Era isolation.** `vec_chunks` declares `doc_id` as a vec0 **metadata column**
and retrieval filters on it. This is not interchangeable with filtering the
primary key. Measured on sqlite-vec v0.1.9 with 200 chunks and a query sitting
on the modern cluster: filtering the primary key returned 0 rows, filtering the
metadata column returned the correct 5. The primary-key form is a post-filter,
`k` applied first. The original specification chose pre-filtering by name and
then wrote post-filtering's code. `tests/test_vector_retrieval.py` carries a
characterisation test that fails if upstream ever changes this.

**The outer sort is load-bearing.** With an IN-list of N documents, sqlite-vec
returns `k` rows *per document*, grouped by document and not globally sorted.
Without `ORDER BY distance ASC LIMIT k` on the outer query you silently get the
wrong top-k in the wrong order.

**Two retrieval channels.** `sources` (primary + judicial) answers what the rule
was. `timeline` answers when it changed. They are retrieved separately because
curated summaries are dense and query-shaped and would outrank governing text in
a shared top-k. The timeline channel widens beyond the routed era only when that
era has no entry of its own, so an undated question ("when was the salary cap
introduced?") is answered without letting a 1985 entry answer a 1975 question.

### Data model

```
documents            1 --< document_chunks        1 --1 vec_chunks
  id                       id                            chunk_id
  doc_name UNIQUE          doc_id  FK CASCADE ------>    doc_id  (metadata)
  category                 chunk_hash UNIQUE             embedding float[768]
  start_season -+ era      article_num
  end_season   -+ window   section_num
  source_url               page_num
  source_tier              is_verified  -- gates entry to vec_chunks
                           text_content
```

Two independent mechanisms keep the index consistent: `ON DELETE CASCADE` from
documents to chunks, and the `sync_vec_index_on_chunk_deletion` trigger from
chunks to vectors. `tests/test_database_schema.py` asserts they chain.

### Source tiers

| Tier | Meaning | Renders as |
| --- | --- | --- |
| `primary` | the governing document | `2023 NBA CBA, Article II, Section 7, p. 37` |
| `judicial` | a court opinion describing the rule | `Robertson v. NBA (S.D.N.Y. 1975), part 18 [court opinion]` |
| `timeline` | a curated, cited entry | `Reserve clause (1946-1976) [curated timeline entry]` |

Tiers exist because pre-1995 coverage rests on weaker sources than the rest of
the corpus, and rendered identically a curated summary would look exactly like
the governing text.

---

## 4. The pre-1995 problem and how it was solved

No public copy of any NBA collective bargaining agreement before 1995 appears to
survive. The archive in use was enumerated through the GitHub API: seven files,
earliest 1995. Archive.org's NBA results are team media guides being resold.

Two source classes were used instead.

**Court opinions**, public domain and complete, fetched from the Caselaw Access
Project (`static.case.law`) by `scripts/fetch_opinions.py`. CAP was chosen over
CourtListener because CourtListener's full-text API needs a key and its pages
sit behind an AWS WAF challenge; CAP is static JSON, open and unauthenticated.
CourtListener remains better for *finding* a case.

| Case | Covers | Seasons |
| --- | --- | --- |
| Haywood v. NBA (1971) | four-year eligibility rule | 1966-1971 |
| Denver Rockets v. All-Pro (1971) | same rule, struck as group boycott | 1966-1971 |
| Robertson v. NBA (1975) | reserve clause, draft, ABA merger | 1964-1976 |
| Robertson v. NBA (1977) | the settlement | 1976-1982 |
| Wood v. NBA (1987) | 1983 cap and draft upheld | 1983-1987 |
| Bridgeman v. NBA (1987) | cap, right of first refusal | 1983-1988 |
| NBA v. Williams (1995) | terms surviving expiration | 1988-1994 |

**A curated timeline**, `historical_timeline.yaml`, 21 entries covering 1946-1994
with no gaps. 13 are high confidence, citing an opinion that is in the index and
can be checked. 8 are medium confidence, drawn from the league's published
history; answers say so. `CLAUDE.md` §2.2 sanctioned this mechanism from the
start and it had never been built.

Important discovery while doing this: the word "territorial" appears in Robertson
four times, but always in the antitrust sense of "territorial division of
markets", never as NBA territorial draft picks. A keyword match would have
surfaced entirely the wrong concept.

---

## 5. Decisions, and where to read them

`docs/architecture/DECISIONS.md` holds 13 numbered decisions, each with the
measurement behind it. This is the most useful file in the repository. Summary:

| | Decision |
| --- | --- |
| D1 | Build retrieval-first, not component-by-component |
| D2 | Filter the vec0 metadata column, never the primary key |
| D3 | No OCR; all documents have usable text layers |
| D4 | Fetch-and-build distribution, not IPFS/BitTorrent |
| D5 | An unqualified question means *this season*, not 2023 |
| D6 | Licence-driven dependency choices |
| D7 | Token counting with the model's own tokenizer, not tiktoken |
| D8 | HTTP 409 for an ambiguous season, not HTTP 300 |
| D9 | `n_ctx` 8192, not 2048 |
| D10 | Ambiguous years derived from the corpus, not hardcoded to 2023 |
| D11 | `x_tolerance=1.5` for text extraction |
| D12 | The Uniform Player Contract scoped to its parent CBA, then removed |
| D13 | Manifest integrity is tested, not trusted |

---

## 6. The specification documents are historical, not authoritative

`docs/specification/` holds the documents the project began from: a PRD, an
implementation plan, and a 2,300-line build sequence containing pre-written code.
That code was generated in a chat and never executed. Several parts are provably
wrong. Where they disagree with `DECISIONS.md`, `DECISIONS.md` is current.

Three things there will actively mislead you:

1. **The 9-step build sequence has no ingestion step.** No chunking, no
   embeddings, no table population, no FastAPI app. `grep "FastAPI(\|@app\.\|uvicorn"`
   over its 2,372 lines returns zero hits. Step 8 downloads a database no step
   ever builds. Completing all nine steps yields a system that cannot answer a
   single question.
2. **The Step 6 pre-filter is a post-filter** and returns nothing under exactly
   the conditions the project exists to handle.
3. **Step 3's OCR pipeline is unnecessary** for this corpus and Step 8's
   distribution model was replaced.

---

## 7. Measured findings, including the ones that went backwards

**Retrieval is solid. Generation fabricates.** On the ten grounded-citation
questions, every retrieval check scores 10/10 while citation validity does not.
This is the argument for measuring them separately: a single end-to-end score
would hide a perfect retriever behind a fabricating writer.

Citation validity history, same ten questions, `mistral:7b` Q4_K_M, one run each:

| Prompt state | Score | Note |
| --- | --- | --- |
| negative instruction only | 7/10 | baseline, after fixing checker bugs |
| plus explicit closed citation list | **8/10** | eliminated every invented pinpoint |
| plus "cite what you claim" and no-commentary rules | 4/10 | **regression, reverted** |

The regression matters. Telling the model to cite every supported claim pushed
it to manufacture finer granularity than it had: `Section IV(a)`, `p. 57 (a)`,
`Section 4(ii)(B)`. More citations, less truth. The current prompt is the 8/10
version plus one narrow rule aimed at that exact failure ("if the list says
p. 57, cite p. 57, never p. 57 (a)"), and **that combination has not been
measured**. Re-run before trusting it.

An earlier reading of 50% was three-fifths my own measurement error: the
extractor treated bracketed enumeration like `[5a, i]` as citations, counted
`[Doc, p. 1, p. 2, p. 4]` as one fabrication rather than three real references,
and scored `part 29` as fabricated because the allowed form was
`part 29 [court opinion]`. Treat any citation number as provisional until its
false-positive modes have been examined.

**What the evaluation does not catch.** It measures which documents retrieval
reaches and whether an expected term appears in the top-5. It does not measure
ranking quality *within* a document. A defect once fused 35% of CBA 2017's chunks
into unsearchable noise and the suite still reported full marks. Run
`scripts/audit_corpus.py` after touching any document; a green eval will not tell
you the text went bad.

---

## 8. This machine

```
GPU               RTX 4060 Laptop
Windows driver    576.52          supports CUDA up to 12.9
Installed torch   2.12.1+cu130    requires driver 580+
torch.cuda        False
RAM               7GB total, ~5GB available
cores             12
ollama            running, mistral:7b (4.4GB) and llama3.2:3b (2.0GB) pulled
```

The CUDA message is misleading: the GPU is fine, the wheel is too new for the
driver. In WSL2 the CUDA driver comes from the Windows host, so nothing inside
Linux fixes it. Either update the Windows driver to 580+, or install a matching
build, which is faster and changes nothing else:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu126
```

**This is the open crossroad.** It would take index rebuilds from ~80 minutes to
a few, and generation from a 190-second cold load to seconds. It is a 2.5GB
download replacing a working install, so it was left for the owner to approve.

RAM matters too: a 7B at Q4_K_M is 4.4GB of weights against 5GB free, so it will
not load in-process. Ollama memory-maps and evicts, which is why it works there
and why Ollama is tried before llama-cpp.

---

## 9. Things that look like bugs but are not

* `src/parser/extract.py` has no OCR path. Measured, not assumed.
* The token counter defaults to a character heuristic. Importing transformers
  costs ~70s at startup for a gate whose fallback deliberately over-counts.
* `vec_chunks` duplicates `doc_id` from `document_chunks`. That denormalisation
  *is* the era-isolation mechanism. Do not normalise it away.
* The outer `ORDER BY distance ASC LIMIT k` in `search.py` looks redundant.
* `/query` can return 200 with `answer: null`. That is the no-backend state.
* Returning zero sources for a 1952 question is correct behaviour.
* `_NOISE` in `extract.py` is built from separate literals with dashes as
  `–`/`—`. A find-and-replace over dash characters corrupted that
  regex into an invalid range **twice**, once after a comment warning about it.
  A comment is not a guard.

---

## 10. Traps

* **`corpus_manifest.yaml` season windows are the routing logic.** A wrong window
  is not a crash. It is a confident wrong answer with a real-looking citation.
  Five defects arrived in one round of hand-editing and none raised an error:
  a `.pdf` where the file was `.PDF` (Linux is case-sensitive, the build silently
  skipped it), an overlapping `end_season`, a `source_url` pasted from the
  neighbouring entry, a window extending past the parent agreement, and a rename
  that stranded 35 orphaned chunks. `tests/test_manifest.py` now catches all five.
* **Pydantic ignores unknown keyword arguments.** A `grounding=` field was
  constructed, passed, and dropped from every response while every test passed.
  `QueryResponse` now sets `extra="forbid"`.
* **Never commit the corpus.** `.gitignore` excludes `data/`, `*.pdf`, `*.db`,
  `*.log`. Verify with `git check-ignore -v` before any first push.

---

## 11. Running it

```bash
make install                       # venv + core deps
python scripts/fetch_corpus.py     # what to download, and from where
python scripts/fetch_opinions.py   # public-domain opinions, automatic
python scripts/audit_corpus.py     # text layers and fused-word check
python scripts/build_index.py      # ~80 min on CPU, one-time
python scripts/seed_concepts.py    # historical analogies

make check                         # lint + 273 tests + eval
python tests/eval/run_eval.py --db nba_legal.db --with-generation
uvicorn src.api.main:app --reload
```

Configuration is documented in `.env.example`; every variable there is optional
and shown at its default.

Useful diagnostics:

```bash
python scripts/fetch_corpus.py --check-urls   # do sources still serve the doc
python scripts/fetch_corpus.py --verify       # checksums
```

---

## 12. Next, in priority order

1. **Re-measure citation validity.** The current prompt is untested in its exact
   form. Warm the model first (`keep_alive` is 30m) or the first request pays a
   190-second cold load.
2. **Decide the CUDA question** (section 8). Everything else is gated on speed.
3. **Run the full 43-question generation eval.** Only the ten grounded-citation
   questions have been measured with generation on.
4. **Upgrade medium-confidence timeline entries.** Eight of 21 rest on the
   league's published history. Any that a court opinion can support becomes
   checkable inside the corpus.
5. **Push and claim namespaces.** `hoopcourt` is free on Hugging Face and PyPI.
   `CHANGELOG.md` and the issue templates point at
   `github.com/AlphaNerdFx/hoopcourt`; the wiki in `wiki/` needs pushing to the
   separate `.wiki.git` repo, instructions in `wiki/README.md`.

---

## 13. Working style for this repository

`CLAUDE.md` §1 sets out how the owner wants an AI advisor to behave: lead with
the disagreement, tag confidence, no warm-up, hold your position under push-back
unless given new information. That is not decoration. Most of the decisions in
`DECISIONS.md` exist because a specification was checked against reality instead
of implemented as written.

Owner preferences established in session: no em dashes anywhere, minimal bold,
commit messages under 256 characters and brief, no Claude co-author trailers or
contributor attribution, tests written only after a feature is working (to avoid
writing tests against behaviour that turns out wrong), documentation outside
README/LICENSE/CONTRIBUTING/CHANGELOG/SECURITY lives under `docs/` in categorical
subdirectories. `CLAUDE.md` stays at the repository root because Claude Code
only reads it from there.

Measure before you argue. Every claim in `DECISIONS.md` has a reproducible
command behind it, and that is the standard for adding to it.
