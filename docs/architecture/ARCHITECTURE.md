# Architecture

One request path, one build path. The design goal is that text from the wrong era
is never a *candidate* for retrieval, not merely unlikely to rank.

## Request path

```
POST /query
  │
  ├─ 1. Token gate                     src/api/tokens.py
  │     >1,000 tokens -> 400, before any retrieval work
  │
  ├─ 2. Temporal router                src/api/router.py
  │     explicit year  -> that season
  │     ambiguous 2023 -> 409 + both options, search SUSPENDED
  │     trigger term within 6 words of a historical cue -> that era
  │     decade slang   -> decade midpoint
  │     nothing        -> current_season()
  │
  ├─ 3. Season -> document ids         src/db/schema.py
  │     WHERE start_season <= y AND end_season >= y
  │     no documents -> [] -> ungrounded, and that is the correct answer
  │
  ├─ 4. Pre-filtered KNN               src/db/search.py
  │     embedding MATCH ? AND k = ? AND doc_id IN (...)   <- metadata column
  │     ORDER BY distance ASC LIMIT k                     <- k is PER DOCUMENT
  │
  └─ 5. Generation (optional)          src/model/generation.py
        no backend -> sources returned, answer omitted
```

Step 4 is where era isolation actually happens, and it depends on a specific
sqlite-vec behaviour, see [DECISIONS.md](DECISIONS.md) D2.

## Build path

```
data/*.pdf ──► extract ──► chunk ──► embed ──► index
               pdfplumber  Section   bge-base  documents
               no OCR      boundary  768-dim   document_chunks
               headers     +size cap normalised vec_chunks (doc_id metadata col)
               stripped
```

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
precision, recall proxy, and refusal correctness across 40 labelled questions.

The gate is **temporal isolation = 100%**. `CLAUDE.md` §2.2 calls rule bleeding a
fatal system error, so it is treated as a correctness failure rather than a
quality metric: any leak exits non-zero.
