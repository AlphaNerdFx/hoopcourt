# Status

_**This page is the single source of truth for measured numbers.** Other
documents link here rather than restating them: a count copied "for
convenience" was wrong in every copy within a fortnight. Re-generate with the
commands shown._

## Working

| Capability | Evidence |
| --- | --- |
| Text extraction, 18 docs / 3,385 pages, no OCR | `python scripts/audit_corpus.py` |
| Structure-aware chunking with article/section citations | `tests/test_extract.py` |
| Embeddings + `sqlite-vec` index, cascade-consistent | `tests/test_database_schema.py` |
| Temporal routing | 12/12, `run_eval.py --category trigger_routing` |
| Era-isolated retrieval (anti-bleed) | `tests/test_vector_retrieval.py` |
| Grounded citation retrieval | 10/10, `run_eval.py --category grounded_citation` |
| FastAPI `/query` + `/health` | `tests/test_api.py` |
| Fetch / verify / build scripts | `scripts/fetch_corpus.py --verify` |
| Source-URL checking | `scripts/fetch_corpus.py --check-urls` |
| Manifest integrity | `tests/test_manifest.py` (44 checks) |

**518 tests collected**, and **51/51 on the evaluation** (`make eval`) with
temporal isolation at 100% across 25 queries, the gate.

How many of the 484 run depends on what the machine has. All three figures are
measured, because the difference between them is the point: a suite that skips
32 tests in CI is not the suite a developer runs.

| Environment | Passed | Skipped | xfailed |
| --- | --- | --- | --- |
| Full index + corpus dir (`make test`, ~60-85 s) | 514 | 1 | 3 |
| Full corpus dir, index hidden | 511 | 4 | 3 |
| CI: no corpus, judicial-tier `ci.db` only (~32 s) | see the PR run | | |

The one skip present everywhere is the opt-in network check. The three extra
skips without the index are the index-gated checks in
`tests/test_documented_numbers.py`. The remaining CI skips are corpus-gated: the
18 copyrighted PDFs cannot be in CI, by design. The three xfails are deliberate,
each a timeline entry whose source needs a human with network access to
replace.

Measured 2026-09-30. Re-derive with `make test` and `make eval`; the three
index-derived counts (46 documents, 5,724 chunks, 15 ambiguous seasons) are
asserted by `tests/test_documented_numbers.py`, so a rebuild that moves them
fails the suite rather than quietly staling this page. Those three tests skip in
CI, which builds a smaller judicial-tier index and would otherwise assert the
wrong numbers; they fire on a machine with the full index, which is where a
rebuild happens.

Read 51/51 with one caveat: four recall checks were passing on terms that appear
in half to nearly all of the expected document, so they could not fail. They were
tightened, which dropped the suite to 41/43 and exposed a real retrieval defect
(D18). The evaluation held 43 questions at that point; D19 added two
colloquial-phrasing questions, taking it to 45. The figure below is measured
**after** both changes, against the harder terms.

```
CATEGORY                 PASS  TOTAL   RATE
grounded_citation          12     12   100.0%
refusal                     6      6   100.0%
temporal_isolation         12     12   100.0%
trigger_routing            21     21   100.0%
OVERALL                    51     51   100.0%

no_bleed            25/25   100.0%     <- the gate
in_expected_docs    25/25   100.0%
recall              22/22   100.0%
```

Index: 47 documents (19 primary, 7 judicial, 21 timeline), 5,760 chunks,
5,760 vectors, 0 orphaned. Coverage runs 1946 to 2029.
Text quality: 21/5,522 chunks with fused words (0.38%), down from 5.9% before
D11; the remainder are genuine CamelCase in the source, not extraction failures.
All 19 source URLs reachable and size-matched to the local files, bar one, see
below.

Verified live against the real index: `400` on an oversized prompt, `409` with
both season options on an ambiguous "2023", and retrieval landing on
*"Section 7. Maximum Annual Salary."* (2023 NBA CBA, Article II, p. 60) and on
the rulebook's *"Section II, Starting and Stopping of Shot Clock"* (p. 28).

## Not yet done

* **Generation runs but is slow here.** Ollama is used when reachable, ahead of
  llama-cpp. Cold model load is 140 to 190 seconds on this machine; once warm a
  query answers in 10 to 15 seconds. A full 43-question generation run is
  therefore minutes, not seconds, so `--with-generation` is opt-in.
* **A 7B does not fit in-process here.** 4.4GB of weights against 5GB of free
  RAM. Ollama memory maps and evicts, so the same model runs through it.
* **CUDA unavailable on the reference machine.** torch reports the NVIDIA driver
  too old for its build (`CUDA available: False`), so embedding runs on CPU and a
  local GGUF backend would too. Not blocking: nothing on the critical path needs
  a GPU.
* **Casual-mode analogies** are seeded but unexercised end-to-end, since that
  path needs a generation backend.

## Known rough edges

* **Index builds are slow**, ~2.5-3 s/page on CPU, so the full 3,385-page corpus
  takes a couple of hours. One-time; `--only "<doc name>"` rebuilds one document.
* **Extraction tolerance is tuned corpus-wide** (`X_TOLERANCE = 1.5`). A new
  document with unusually tight or loose kerning may need it revisited,
  `scripts/audit_corpus.py` reports fused tokens per page and fails if any
  document regresses. See DECISIONS.md D11.
* **`CBA 1995.pdf` carries OCR debris** on a handful of pages (`30 --~;1`,
  `~i`). Only the leading header line is stripped, so a second junk line can
  survive into chunk text. Affects one document; stripping more aggressively
  risks eating real body text, which is the worse failure.
* **Era windows are judgement calls.** `corpus_manifest.yaml` records the
  reasoning per document. The CBA lineage is contiguous and non-overlapping
  (1995→2029), but a wrong window is a rule-bleeding bug that no retrieval
  tuning can fix, review it before trusting historical answers.
* **The Uniform Player Contract's source is unresolved.** It points at
  `scribd.com`, which `DATA_SOURCES.md` rules out and which serves an HTML viewer
  rather than a PDF. The document is also inert, never retrieved in testing,
  because CBA 2017 contains the same text and outranks it. Either source it
  properly or drop the entry; see DECISIONS.md D12/D13.
* **Pre-1995 rests on weaker sources.** No public CBA text before 1995 appears to
  survive, so 1946 to 1994 is carried by public-domain court opinions and 21
  curated timeline entries. Citations declare which via `source_tier`. Eight of
  the timeline entries are medium confidence, drawn from the league's published
  history rather than from a document in the index.

## Generation is measured, and the number is a range

A local 7B (`mistral:7b` via Ollama, Q4_K_M) answers end to end on GPU.

**Generation is not reproducible on this stack even at temperature 0.** Sampling
is greedy; llama.cpp's GPU forward pass is not bitwise stable. The same
five-question batch run twice scored 4/5 then 3/5. So a single run is a sample.

Three full runs over all 43 questions, measured before D19 added the two
colloquial-phrasing questions. The generation figure has not been re-measured
over all 45, and TESTING.md rule 5 says a figure is a range with a named style,
so read this as Legal Scholar mode over 43:

```
citations   14/26   15/26   14/26        54% - 58%
```

Retrieval in the same runs is 100% on every check, every time. That separation
is the whole point of measuring them apart: a single end-to-end score would hide
a clean retriever behind an inconsistent writer.

**What the citation check asserts.** That every citation in an answer was one the
model was handed, matched exactly, and that a substantive answer cited
something. It verifies **provenance, not relevance**, and says nothing about
whether the answer is factually right.

**Not all failures are equal.** Classifying every fabricated citation against the
exact context the model was given: **one genuinely invented citation per 26
questions**, for both candidate models. The rest are a supplied citation made
finer, `p. 57` written as `p. 57 (a)`. The prompt already forbids this and gives
that exact counterexample; a 7B at Q4 does it anyway.

See [../evaluation/GENERATION_MEASUREMENT.md](../evaluation/GENERATION_MEASUREMENT.md)
for the full breakdown, the model comparison, and why it does not justify a
fine-tune.

## What the evaluation does not catch

Worth knowing before trusting a green run.

The eval measures **which documents** retrieval reaches and whether any chunk in
the top-5 contains an expected term. It does not measure **ranking quality within
a document**. The fused-word defect (D11) degraded 35% of CBA 2017's chunks into
unsearchable noise, and the suite still reported 42/42, the era-correct document
was still reached, and enough surviving chunks carried the expected terms.

So a green eval means *"routing is right and nothing bled across eras"*. It does
not mean *"the best available passage was retrieved"*. Catching that class of
problem needs either graded relevance judgements (which passage, not which
document) or a data-quality check upstream, `scripts/audit_corpus.py` now does
the latter for this specific failure.

### The corpus can age out from under a green run (F5)

Measured 2026-10-01. The router derives the current season from the clock and
rolls over on 1 October, so an unqualified modern question moved from season 2025
to 2026 overnight. Four documents scoped `2025-2025` left the candidate set at
the same moment, and they are the operational ones:

| document | chunks |
| --- | --- |
| Official 2025-26 Rulebook | 147 |
| 2025-26 NBA Officials Guide | 84 |
| 2025-26 NBA Concussion Policy | 7 |
| 2025-26 NBA Officiating Staff | 2 |

All 38 "shot clock" passages are in the rulebook. `corpus_manifest.yaml` is not
wrong, a 2025-26 rulebook genuinely does not govern 2026-27; the corpus simply
has no 2026-27 rulebook yet. The failure was that **nothing said so**:
`resolve_era_documents(2026)` still returned six documents, so coverage looked
complete while the playing rules were gone, and shot-clock questions were
answered from the CBA and the Constitution.

The API now says it. `coverage.operational_gap` is set whenever the routed season
runs past the newest annually reissued document, named by
`db.schema.stale_operational_season()` and derived from window width rather than
`category`, because the CBA is "Current Governing" exactly like the rulebook.
The affected evaluation question carries `known_gap: recall`, and the runner
re-derives the gap rather than trusting the marker: once a 2026-27 rulebook is
indexed the marker fails and has to be deleted, so it cannot become a permanent
excuse.

Remaining limitation: retrieval still cannot answer a playing-rules question for
the current season. Fetching the 2026-27 rulebook is the actual remedy.

Two consequences:

* Run `scripts/audit_corpus.py` after adding or re-extracting any document. A
  green eval will not tell you the text went bad.
* If you add graded relevance labels later, put them in the same YAML rather than
  a parallel file, the question set is the requirement, and splitting it invites
  the two halves to drift.

## Next

1. Report a narrowed permitted citation as its own grounding state rather than
   calling it fabrication. The closed list is already in hand, so the system can
   distinguish "invented a document" from "added a subsection to a real
   citation". Do not rewrite the citation to make it pass.
2. Audit the remaining recall terms the way D18's four were audited. A
   disjunction is only as strong as its rarest accepted term.
3. Corpus expansion (officiating, league history), which reuses every existing
   mechanism. See [../../TODO.md](../../TODO.md).
