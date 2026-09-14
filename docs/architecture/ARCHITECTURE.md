# Architecture

One request path, one build path. The design goal is that text from the wrong era
is never a *candidate* for retrieval, not merely unlikely to rank.

## Request path

```
GET  /                               src/api/static/index.html
     single page, no build step, no dependencies

POST /query
  |
  +- 1. Token gate                   src/api/tokens.py
  |     >1,000 tokens -> 400, before any retrieval work
  |
  +- 2. Temporal router              src/api/router.py
  |     explicit year      -> that season
  |     ambiguous boundary -> 409 + both options, search SUSPENDED
  |     extinct term       -> fires on presence ("reserve clause")
  |     live term          -> needs a cue within 6 words ("coin flip")
  |     decade slang       -> decade midpoint
  |     nothing            -> current_season()
  |
  +- 3. Season -> document ids       src/db/schema.py
  |     start_season <= y <= end_season, filtered by source_tier
  |
  +- 4. Two retrieval channels       src/db/search.py
  |     sources : primary + judicial, era-filtered, top-k
  |     timeline: curated entries, era-filtered, distance-gated
  |     both use: MATCH ? AND k = ? AND doc_id IN (...)  <- metadata column
  |               ORDER BY distance ASC LIMIT k          <- k is PER DOCUMENT
  |
  +- 5. Coverage                     src/api/main.py
  |     no documents for the era -> covered=false, names the nearest
  |     documents but no match    -> covered=true, reason=no_match
  |
  +- 6. Generation (optional)        src/model/generation.py
  |     Ollama first, then llama-cpp; absent -> sources only, answer null
  |
  +- 7. Citation check               src/model/verify.py
        every citation matched against the passages actually supplied
        a real document with an invented pinpoint is still fabrication
```

Step 4 is where era isolation happens and it depends on a specific sqlite-vec
behaviour, see [DECISIONS.md](DECISIONS.md) D2.

### Why two channels rather than one ranking

Curated timeline summaries are dense and query-shaped, so in a shared top-k they
outrank the governing text they summarise. Retrieved separately, `sources`
answers *what the rule was* and `timeline` answers *when it changed*, and neither
displaces the other.

The timeline channel widens past the routed era only when the question concerns a
season later than any entry covers. That answers undated questions like "when was
the salary cap introduced?" without letting a 1985 entry answer a 1975 question,
or a 1946 entry answer a 1940 one.

### Concurrency

Two bugs lived here and both only appeared under load, which is worth knowing
before adding a third.

FastAPI runs sync handlers and their dependencies in a threadpool. A SQLite
connection could therefore be opened on one thread and closed on another, so
connections are created with `check_same_thread=False`. That is safe only because
no connection is ever shared: each request opens and closes its own.

The embedding model is loaded once behind a lock and warmed at startup. The
unguarded lazy version let several first-requests race into the same load, which
surfaces as `NotImplementedError: Cannot copy out of meta tensor` and reads like
a hardware fault rather than a race.

## Build path

```
data/*.pdf ──► extract ──► chunk ──► embed ──► index
data/*.txt     pdfplumber  Section   bge-base  documents
               no OCR      boundary  768-dim   document_chunks
               headers     +size cap normalised vec_chunks (doc_id metadata col)
               stripped
```

Two kinds of source enter the same path. The 18 PDFs go through `pdfplumber`;
the 7 court opinions arrive from the Caselaw Access Project as plain text and
skip extraction. `scripts/audit_corpus.py` measures both, because a truncated
download and a missing text layer are the same failure once indexed.

`scripts/build_index.py` runs the whole path and is idempotent per document.
Cost is dominated by embedding on CPU: roughly 2.5-3 s/page, ~1.5 chunks/page.

## Data model

```
documents               1 ──< document_chunks           1 ──1 vec_chunks
  id                           id                             chunk_id  (= chunks.id)
  doc_name UNIQUE              doc_id  FK ─── CASCADE ───►    doc_id    (metadata)
  category                     chunk_hash UNIQUE              embedding float[768]
  start_season ─┐              article_num
  end_season  ──┴─ era window  section_num
  source_url                   page_num
                               is_verified ── gates entry to vec_chunks
                               text_content
```

Two independent mechanisms keep the vector index from outliving its text:
`ON DELETE CASCADE` from `documents` to `document_chunks`, and the
`sync_vec_index_on_chunk_deletion` trigger from `document_chunks` to
`vec_chunks`. `tests/test_database_schema.py` asserts they chain, a document
delete must leave zero orphaned vectors.

`is_verified` is enforced at insertion rather than at query time: only verified
chunks are written to `vec_chunks`, so it *is* the active index and the
withhold-until-approved rule cannot be forgotten by a caller.

## Module boundaries

| Module | Owns | Deliberately does not |
| --- | --- | --- |
| `src/parser/` | PDF -> per-page text, running headers, article/section state | know about chunks or embeddings |
| `src/ingest/` | chunking, embeddings, index population | know about HTTP or routing |
| `src/db/` | connection, schema, era-isolated search | know what a "question" is |
| `src/api/` | token gate, routing, request/response contract | know how text was extracted |
| `src/model/` | prompt construction, generation backends | be required for the system to work |

The last row is the important one. Generation sits behind a one-method protocol
and returns `None` when no backend is installed; retrieval, routing and the whole
evaluation suite run without it, on CPU, offline, free.

## What is measured

`tests/eval/run_eval.py` reports routing accuracy, temporal isolation, retrieval
precision, recall proxy, refusal correctness and anachronism avoidance across 43
labelled questions. With `--with-generation` it also measures citation validity:
whether the answer cited only what it was handed.

Retrieval and generation are scored separately on purpose. They fail differently
and have different fixes, and a single end-to-end number would hide a clean
retriever behind a fabricating writer.

The gate is **temporal isolation = 100%**. `CLAUDE.md` §2.2 calls rule bleeding a
fatal system error, so it is treated as a correctness failure rather than a
quality metric: any leak exits non-zero.
