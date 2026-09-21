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
| Text extraction (18 PDFs / 3,320 pages, + 7 opinions) | working |
| Structure-aware chunking with article/section citations | working |
| Embeddings + `sqlite-vec` index | working |
| Temporal routing | working, 15/15 on the routing eval |
| Era-isolated retrieval | working, anti-bleed regression tests pass |
| FastAPI service (`/query`, `/health`) | working |
| Pre-1995 coverage (opinions + curated timeline) | working, 1946 onward |
| Generation (Ollama, local GGUF, or optional cloud) | working |
| Web interface at `/` | working |
| Citation grounding | 14-15 of 26, Legal Scholar mode, see Limitations |

## Quick start

```bash
python -m venv venv && source venv/bin/activate

# Optional, and worth it unless you want GPU embeddings. See the note below.
pip install torch --index-url https://download.pytorch.org/whl/cpu

pip install -r requirements.txt

python scripts/fetch_corpus.py      # what to download, and from where
python scripts/fetch_corpus.py --check-urls   # do the sources still serve it?
python scripts/audit_corpus.py      # confirm every source carries usable text
python scripts/build_index.py       # compile the local index (slow; see below)
python scripts/seed_concepts.py     # historical analogies for casual mode

python tests/eval/run_eval.py       # routing + anti-bleed measurement
uvicorn src.api.main:app --reload   # http://127.0.0.1:8000
```

**Install size.** `sentence-transformers` pulls PyTorch, and PyTorch's default
wheels carry the full CUDA stack. Measured on a clean virtualenv: **5.8 GB and
15 NVIDIA packages** by default, against **1.4 GB and none** if you install the
CPU build of torch first, as above. `Embedder` passes `device=None`, so
sentence-transformers picks the device: with the default wheels it will use CUDA
if it finds it, and with the CPU build there is nothing to find. Install the CPU
build unless you actually want GPU embeddings. Both were verified against the
full evaluation: 45/45, isolation at 100%.

The corpus is not in this repository and never will be, see
[DATA_SOURCES.md](docs/corpus/DATA_SOURCES.md). You download the documents from official and
public-record sources and build your own index; the project ships instructions
and checksums, not content.

Building the index is CPU-bound on embedding: roughly **2.5-3 seconds per page**,
so the full 3,320-page corpus takes a couple of hours. It is a one-time cost, and
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

## Generation backends

Retrieval works with no model installed at all: the API returns cited passages
and `/health` reports `generator: null`. Prose answers need one of three
backends, and `BACKEND_MODE=local` (the default) tries the first two in order.

| | Install | Configure |
| --- | --- | --- |
| **Ollama** | `ollama pull mistral:7b` | `NBA_OLLAMA_MODEL`, `NBA_OLLAMA_URL` |
| **llama-cpp** | `pip install -r requirements-local.txt` | `NBA_GGUF_PATH` |
| **Anthropic** | `pip install -r requirements-cloud.txt` | `BACKEND_MODE=cloud`, `ANTHROPIC_API_KEY` |

Ollama is preferred because it needs no compiler and manages weights and memory
itself. The llama-cpp backend compiles from source, which needs a C/C++ compiler
but **not** cmake on the host, and adds about 40 MB. With no `NBA_GGUF_PATH` it
downloads Qwen2.5-7B-Instruct at q4_k_m, 4.7 GB across two shards, on first use,
and it does that **during startup**, so the server will sit there for ten
minutes or more saying nothing except the warning it logs first. Point
`NBA_GGUF_PATH` at a `.gguf` you already have to skip it entirely.

CPU inference is slow, which is the degraded performance the hardware profile
warns about rather than a fault. Measured on this project's reference machine
(WSL2, no GPU offload): a 3B answered `/query` in **110-175 seconds** over five
retrieved chunks, and the default 7B took **76 seconds** on a single chunk after
a **438-second** load. Those two are not comparable to each other.

If neither backend can be built, the reason is logged rather than swallowed, so
stderr will name which one failed and why.

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

`tests/eval/questions.yaml` holds 45 labelled questions across four categories,
temporal isolation, grounded citation, refusal, and trigger routing. Every
assertion is checkable without an LLM, so the whole suite runs offline and free.

The gate is the **temporal isolation rate**, which must be 100%: rule bleeding is
a correctness failure, not a quality one, and `run_eval.py` exits non-zero on any
leak.

Refusal cases matter as much as the rest. Asked about 1952, an era no document
in the corpus covers, the correct behaviour is to return nothing, not the
nearest plausible text.

## Limitations

Stated plainly, because a system about grounding should be honest about its own.

**Retrieval is the strong half.** Routing, era isolation, recall and refusal are
45/45 across the evaluation, exactly reproducible, and measured without an LLM.
Temporal isolation is a hard gate: any leak exits non-zero.

**Generation is the weak half, and its number is a range.** Six full runs of
`mistral:7b` over the same 26 answerable questions scored **18, 14, 14, 14, 15
and 14**; the most recent three, on the current code, were 14, 15 and 14.
Nothing changed between them. Generation is **not reproducible on this stack even
at temperature 0**: sampling is greedy, but llama.cpp's GPU forward pass is not
bitwise stable. Treat any single generation figure, including one you measure
yourself, as a sample.

**That number went down when retrieval got better, and the reason matters.**
Before the era-filter fix the same runs scored 17, 19 and 18. Fabrication did not
change at all; refusal doubled. A question like "what was the maximum annual
salary in 2013?" used to retrieve dated worked examples containing dollar
figures, which the model happily answered and cited. It now retrieves the
provision that states the rule, which contains no dollar figure at all, only
"the greater of 25% of the Salary Cap or 105% of the prior Salary". The corpus
does not state that number; it states how to compute it. The higher score was
partly earned by citing real passages that were not the governing rule.

**What a citation failure usually is.** Classifying every fabricated citation
against the exact context the model was handed: **one genuinely invented
citation per 26 questions**. The rest are a supplied citation made finer, `p. 57`
written as `p. 57 (a)`. That is over-precision, not invented law, and the answer
still rests on a passage the system actually retrieved. The prompt already
forbids it and gives that exact counterexample; a 7B at Q4 does it anyway.

**The citation check verifies provenance, not relevance.** It asks whether a
citation was in the context, never whether the cited passage supports the claim.
An answer can cite perfectly and be wrong about what the provision says.

**The evaluation does not measure ranking within a document.** It measures which
documents were reached and whether an expected term appeared. Four recall checks
were once passing on terms present in half to nearly all of the expected
document, which hid a real retrieval defect for some time. If you add questions,
check the corpus frequency of every term you accept.

Every claim here is reproducible: `python tests/eval/run_eval.py --db nba_legal.db
[--with-generation]`. Details and the full breakdown are in
[docs/evaluation/GENERATION_MEASUREMENT.md](docs/evaluation/GENERATION_MEASUREMENT.md).

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
