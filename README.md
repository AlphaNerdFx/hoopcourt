# Hoopcourt

**Every NBA rule, as it stood.**

An era-aware retrieval engine over NBA governing documents, the Collective
Bargaining Agreements, the Constitution, the rulebook, and the draft rules, that
answers a question using the rules that were actually in force at the time it is
about.

The problem it solves is **rule bleeding**: ask a general-purpose assistant about
a 1997 trade and it will happily explain it using 2023 second-apron rules. This
system makes that structurally impossible rather than merely unlikely. A query is
routed to a season, the season resolves to a set of documents, and the vector
search is *pre-filtered* to those documents before similarity is computed. Text
from the wrong era is never a candidate.

Everything required to run it is free and offline: local embeddings, a local
SQLite vector index, and an optional local LLM. No API key is needed to install,
build, query, or evaluate.

## Status

| Layer | State |
| --- | --- |
| Text extraction (18 PDFs + 7 opinions, 3,385 pages) | working |
| Structure-aware chunking with article/section citations | working |
| Embeddings + `sqlite-vec` index | working |
| Temporal routing | working, 15/15 on the routing eval |
| Era-isolated retrieval | working, anti-bleed regression tests pass |
| FastAPI service (`/query`, `/health`) | working |
| Pre-1995 coverage (opinions + curated timeline) | working, 1946 onward |
| Generation (Ollama, local GGUF, or optional cloud) | working |
| Web interface at `/` | working |

## Quick start

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

python scripts/fetch_corpus.py      # what to download, and from where
python scripts/fetch_corpus.py --check-urls   # do the sources still serve it?
python scripts/audit_corpus.py      # confirm every source carries usable text
python scripts/build_index.py       # compile the local index (slow; see below)
python scripts/seed_concepts.py     # historical analogies for casual mode

python tests/eval/run_eval.py       # routing + anti-bleed measurement
uvicorn src.api.main:app --reload   # http://127.0.0.1:8000
```

The corpus is not in this repository and never will be, see
[DATA_SOURCES.md](docs/corpus/DATA_SOURCES.md). You download the documents from official and
public-record sources and build your own index; the project ships instructions
and checksums, not content.

Building the index is CPU-bound on embedding: roughly **2.5-3 seconds per page**,
so the full 3,412-page corpus takes a couple of hours. It is a one-time cost, and
`--only "<doc name>"` rebuilds a single document.

## Using it

Open `http://127.0.0.1:8000` for the web interface, or `POST /query` for the API
(`/docs` has the schema). The page shows the season your question resolved to,
the passages it drew on with their source tier, when the rule changed, and
whether every citation in the answer was one the model was actually given.

Some questions get a question back. Asking about "2011" returns both options,
because the 2010-11 season is governed by one agreement and 2011-12 by another,
and guessing would produce a confident wrong answer. Asking about a season no
document covers returns nothing and says so, which is the correct outcome rather
than a failure.

## How the era isolation works

`sqlite-vec` offers two ways to constrain a KNN search, and only one of them is
a real pre-filter. Constraining the **primary key** (`chunk_id IN (subquery)`)
applies `k` *first* and filters afterwards, a post-filter that returns nothing
at all when another era dominates the similarity ranking. Constraining a declared
**metadata column** (`doc_id IN (...)`) restricts candidates before the search
runs. Measured on sqlite-vec v0.1.9 with 200 chunks and a query sitting on the
modern cluster, the first returns 0 rows and the second returns the correct
historical top-5.

So `vec_chunks` declares `doc_id` as a metadata column, and retrieval is:

1. Route the question to a season (`src/api/router.py`).
2. Resolve the season to document ids (`documents.start_season/end_season`).
3. KNN with `doc_id IN (...)` as a true pre-filter (`src/db/search.py`).
4. Re-sort globally and cap at `k`, sqlite-vec returns `k` rows *per document*,
   grouped and not globally ordered, so the outer sort is load-bearing.

`tests/test_vector_retrieval.py` includes a characterisation test that fails if a
future sqlite-vec makes the primary-key form a true pre-filter, so the deviation
can be revisited rather than silently outliving its reason.

## Evaluation

`tests/eval/questions.yaml` holds 43 labelled questions across four categories,
temporal isolation, grounded citation, refusal, and trigger routing. Every
assertion is checkable without an LLM, so the whole suite runs offline and free.

The gate is the **temporal isolation rate**, which must be 100%: rule bleeding is
a correctness failure, not a quality one, and `run_eval.py` exits non-zero on any
leak.

Refusal cases matter as much as the rest. Asked about 1952, an era no document
in the corpus covers, the correct behaviour is to return nothing, not the
nearest plausible text.

## Layout

```
src/parser/     PDF text extraction (no OCR; see scripts/audit_corpus.py)
src/ingest/     chunking, embeddings, index population
src/db/         connection, schema, era-isolated search
src/api/        FastAPI app, temporal router, token gate
src/model/      prompt templates, generation backends
scripts/        corpus fetch/audit, index build, concept seeding
tests/eval/     labelled question set and the evaluation runner
```

## Scope

The MVP claim is deliberately narrow: an era-aware question answering system over
NBA governing documents, with verifiable citations, that a person can install and
use. Statistics, contracts, a fine-tuned model and a hosted service are all
sequenced after it.

[TODO.md](TODO.md) is the working checklist.
[docs/project/ROADMAP.md](docs/project/ROADMAP.md) explains the sequence, and
[docs/architecture/DECISIONS.md](docs/architecture/DECISIONS.md) records why each
call was made, with the measurement behind it.

## Licence

MIT, see [LICENSE](LICENSE). Dependencies are deliberately kept to permissive
licences: `pdfplumber` (MIT) rather than PyMuPDF (AGPL-3.0), `bge-base-en-v1.5`
(MIT) rather than a model requiring `trust_remote_code`, and Qwen2.5 (Apache-2.0)
as the default local model rather than Llama-3.1, whose community licence carries
acceptable-use restrictions and a 700M-MAU clause.

The NBA and NBPA documents this operates on are copyrighted by their respective
owners and are neither included nor redistributed.
