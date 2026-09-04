# Status

_Snapshot; re-generate the numbers with the commands shown._

## Working

| Capability | Evidence |
| --- | --- |
| Text extraction, 18 docs / 3,320 pages, no OCR | `python scripts/audit_corpus.py` |
| Structure-aware chunking with article/section citations | `tests/test_extract.py` |
| Embeddings + `sqlite-vec` index, cascade-consistent | `tests/test_database_schema.py` |
| Temporal routing | 12/12, `run_eval.py --category trigger_routing` |
| Era-isolated retrieval (anti-bleed) | `tests/test_vector_retrieval.py` |
| Grounded citation retrieval | 10/10, `run_eval.py --category grounded_citation` |
| FastAPI `/query` + `/health` | `tests/test_api.py` |
| Fetch / verify / build scripts | `scripts/fetch_corpus.py --verify` |
| Source-URL checking | `scripts/fetch_corpus.py --check-urls` |
| Manifest integrity | `tests/test_manifest.py` (44 checks) |

**238 unit tests green in ~6 s** (`make test`) and **43/43 on the evaluation**
(`make eval`) against the complete 19-document index, with temporal isolation at
100%, the gate.

```
CATEGORY                 PASS  TOTAL   RATE
grounded_citation          10     10   100.0%
refusal                     6      6   100.0%
temporal_isolation         12     12   100.0%
trigger_routing            15     15   100.0%
OVERALL                    43     43   100.0%

no_bleed            23/23   100.0%     <- the gate
in_expected_docs    23/23   100.0%
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

* **Index builds are slow**, ~2.5-3 s/page on CPU, so the full 3,320-page corpus
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

## Generation is measured, and it fabricates

A local 7B (mistral:7b via Ollama, Q4_K_M) now answers end to end. Measured over
the ten grounded-citation questions with `run_eval.py --with-generation`:

```
route              10/10   100%
no_bleed           10/10   100%
in_expected_docs   10/10   100%
recall             10/10   100%
citations           7/10    70%     <- generation
```

Retrieval is perfect and the model still invents a citation in roughly three
answers out of ten: an invented Article and Section in the 2023 CBA, a page that
was not in context, and once the max-salary provision cited in answer to a draft
lottery question. Every one of those would read as a correct answer.

This is the argument for measuring the two separately. They fail differently and
they have different fixes, and a single end-to-end score would have hidden a
perfect retriever behind a fabricating writer.

Two cautions on the number itself. It was 50% before three measurement errors
were removed from the checker, so treat any citation figure as provisional until
the false-positive modes have been examined. And it is one model at one
quantisation on ten questions.

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

Two consequences:

* Run `scripts/audit_corpus.py` after adding or re-extracting any document. A
  green eval will not tell you the text went bad.
* If you add graded relevance labels later, put them in the same YAML rather than
  a parallel file, the question set is the requirement, and splitting it invites
  the two halves to drift.

## Next

1. Install a local generation backend and re-run the eval with generation on,
   measuring citation validity separately from retrieval.
2. Add pre-1995 documents (`DATA_SOURCES.md` → Internet Archive) so the historical
   triggers have something to retrieve.
3. Expand the eval set as coverage grows, new documents change which eras exist,
   which changes what the refusal cases should refuse.
