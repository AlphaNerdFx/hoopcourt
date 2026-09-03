# Handover

What a new contributor (human or AI) needs to know before changing anything.

## Read these first, in order

1. `README.md`, what the system does and how to run it.
2. `docs/architecture/DECISIONS.md`, **the important one.** Nine decisions where
   the implementation deliberately departs from the specification documents, each
   with the measurement behind it.
3. `docs/architecture/ARCHITECTURE.md`, the request and build paths.
4. `docs/operations/STATUS.md`, what works, what does not, known rough edges.

## The specification documents are historical, not authoritative

`BUILD_SEQUENCE.md`, `IMPLEMENTATION_PLAN.md` and parts of `PRD.md` describe a
design that was substantially revised once it met the actual data. They are kept
because the reasoning in them is useful, and they have been annotated where they
were superseded, but **the code is the source of truth**, and where they
disagree with `DECISIONS.md`, `DECISIONS.md` is current.

Three things in those documents will actively mislead you if taken at face value:

* **The 9-step build sequence has no ingestion step.** No chunking, no
  embeddings, no table population, no FastAPI app. It was reordered; see
  `CLAUDE.md` §8 for the phases that replaced it.
* **The pre-filter SQL in `BUILD_SEQUENCE.md` Step 6 is a post-filter** and
  returns zero rows under exactly the conditions the project exists to handle.
  See DECISIONS.md D2 before touching `src/db/search.py`.
* **Step 3's OCR pipeline is unnecessary** for this corpus, and Step 8's IPFS
  distribution was replaced. Both are marked in `CLAUDE.md`.

## Things that look like bugs but are not

* **`src/parser/extract.py` has no OCR path.** Measured, not assumed,
  `scripts/audit_corpus.py` re-checks and fails if a document ever needs it.
* **The token counter defaults to a character heuristic.** Importing transformers
  costs ~70s on a cold filesystem, at application startup, for a gate whose
  fallback deliberately over-counts. Exact counting is opt-in via
  `NBA_TOKEN_COUNTER=local|cloud`.
* **`vec_chunks` duplicates `doc_id` from `document_chunks`.** That denormalisation
  *is* the era-isolation mechanism (D2). Do not "normalise" it away.
* **The outer `ORDER BY distance ASC LIMIT k` in `search.py` looks redundant.**
  It is not: sqlite-vec returns `k` rows per document in an IN-list, grouped and
  not globally sorted.
* **`/query` can return 200 with `answer: null`.** That is the no-generation-backend
  state, not a failure. `grounded` tells you whether sources were found.
* **Returning zero sources for a 1952 question is correct behaviour**, not a
  retrieval miss. The corpus starts at 1995.

## Where to be careful

`corpus_manifest.yaml` season windows *are* the routing logic. A wrong window is
a rule-bleeding bug that no amount of retrieval tuning will fix, and it will not
show up as an error, only as a confidently wrong answer with a real-looking
citation. Change one only with a reason recorded in the comment beside it, and
re-run `python tests/eval/run_eval.py`.

## The gate

```bash
make check     # 178 unit tests + the evaluation
```

Temporal isolation must be 100%. If a change drops it, the change is wrong.

## Working style for this repository

`CLAUDE.md` §1 sets out how the project owner wants an AI advisor to behave:
lead with the disagreement, tag confidence, no warm-up, hold your position under
push-back unless given new information. That is not decoration, most of the
decisions in `DECISIONS.md` exist because a specification was checked against
reality instead of implemented as written.

Measure before you argue. Every claim in `DECISIONS.md` has a reproducible
command behind it, and that is the standard for adding to it.
