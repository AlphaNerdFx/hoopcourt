# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Versions stay below 1.0.0 until a generation backend ships and the answer layer
is measured, not just the retrieval layer.

## [Unreleased]

### Added

- Ollama generation backend, tried before llama-cpp because it needs no compiler
  and manages memory itself. A 7B model at Q4_K_M does not fit in-process on an
  8GB machine; through Ollama the same model runs.
- Citation verification (`src/model/verify.py`). An answer is checked against the
  chunks it was actually handed, so citing a real document with an invented
  pinpoint is caught. On its first run against a local 7B it found a fabricated
  citation to a "1996 NBA Collective Bargaining Agreement", an agreement that
  does not exist.
- `run_eval.py --with-generation` measures citation validity alongside retrieval.
- `grounding` block on `/query` responses, so a caller can see whether the
  answer cited only what it was given without running the evaluation.
- `.env.example` documenting all eight configuration variables at their defaults.
- Explicit closed list of permitted citations in the prompt, which raised
  citation validity from 7/10 to 8/10 and removed every invented pinpoint.
- Single-page web UI served by the API at `/`. No build step, no CDN and no
  package manager: a tool people install should not need npm to display its own
  output, and a CDN would break the offline mode this project is designed for.
  It renders source tiers, the timeline channel, the coverage block and the
  grounding result, and distinguishes a fabricated citation from an uncited
  claim, which are different failures.
- Tests covering the API-to-page field contract, including a `node --check`
  parse of the inline script. String assertions pass over JavaScript that does
  not parse; the page then serves fine and every button does nothing.
- Tests for `scripts/audit_corpus.py`, which had none.

### Fixed

- The corpus audit crashed on every court opinion. Phase 7 added 7 plain-text
  opinions to a manifest the audit read with `pdfplumber`, so the guard named in
  CLAUDE.md and TODO.md raised `PdfminerException` on every run from the moment
  pre-1995 coverage shipped. Text sources are now measured the same way, and a
  truncated download fails the audit as loudly as a missing text layer.
- Two concurrency defects that only appear under a real client. SQLite
  connections are opened with `check_same_thread=False`, because FastAPI runs
  sync dependencies in a threadpool and a connection can be closed on a
  different worker thread than it was opened on. The embedder's lazy load is
  guarded by double-checked locking, because two simultaneous first requests
  otherwise load the model twice on a machine with room for one.
- The timeline fallback widened backwards in time. A question about a season
  later than any timeline entry should reach for the nearest entry; a question
  about an earlier one must not, or a 1985 entry answers a 1975 question.
- Ollama timeout raised to 900s with a 30m keep_alive. A cold 7B load takes
  140-190s, and the previous 300s ceiling killed requests mid-load.
- A generation failure is now recorded against its question rather than aborting
  the evaluation run and discarding every result already gathered.

### Changed

- Context blocks carry one identifier, not two. Given both an `id` and a
  `citation` the model merged them into `[1, citation: ...]`, so correct
  citations were scored as fabrications.
- `QueryResponse` forbids extra fields. A `grounding=` argument was constructed,
  passed, and silently dropped from every response while every test passed,
  because Pydantic ignores unknown keywords by default.
- `--check-urls` expects a format per source tier. Court opinions come from the
  Caselaw Access Project as JSON, and demanding PDF everywhere reported all
  seven as viewer pages.
- The tier label is separated from the citation locator. `[... , part 29]` and
  `[... , part 29 [court opinion]]` are both accepted, because the label is
  added for the reader rather than being part of the reference.

## [0.1.0] - 2026-09-03

First tagged release. Era-aware retrieval over NBA governing documents, covering
1946 to 2029, with routing and isolation measured rather than asserted.

### Added

- Text extraction for 19 PDFs and 7 court opinions, 3,412 pages, no OCR path.
  All documents carry a usable text layer, re-checked by `scripts/audit_corpus.py`.
- Structure-aware chunking that tracks Article and Section per line, so citations
  resolve to a provision rather than only a page.
- Local embeddings (`BAAI/bge-base-en-v1.5`, MIT) and a `sqlite-vec` index.
- Temporal router: explicit years, decade slang, and historical trigger terms
  gated by a six-word proximity window.
- Era-isolated retrieval using a vec0 metadata pre-filter on `doc_id`.
- FastAPI service with `/query` and `/health`.
- Pre-1995 coverage from public-domain court opinions (Caselaw Access Project)
  and a curated 21-entry timeline, both era-scoped.
- `source_tier` on documents (`primary`, `judicial`, `timeline`) so a citation
  states what authority it carries.
- Second retrieval channel for the curated timeline, kept separate from
  authoritative sources and filtered by a measured relevance threshold. It
  widens beyond the routed era only when that era has no entry of its own, so an
  undated question such as "when was the salary cap introduced?" is answered
  without letting a 1985 entry answer a 1975 question.
- Coverage block on `/query` responses that distinguishes an uncovered era from
  a failed match.
- Corpus tooling: `fetch_corpus.py` (status, checksums, `--check-urls`),
  `fetch_opinions.py`, `audit_corpus.py`, `build_index.py`, `seed_concepts.py`.
- Evaluation harness: 43 labelled questions across four categories, with
  temporal isolation as a hard gate.
- 254 unit tests.

### Fixed

Defects found in the pre-existing specification, each verified before changing:

- Era pre-filter was a post-filter. Filtering the vec0 primary key applies `k`
  first, returning zero rows when another era dominates the ranking. Measured at
  200 chunks: the specified form returned 0 results, a metadata-column filter
  returned the correct 5. This was the anti-bleed mechanism.
- sqlite-vec returns `k` rows per document for an IN-list, grouped and not
  globally sorted, so an outer `ORDER BY distance LIMIT k` is required.
- Ambiguous-season clarification was wired to 2023 only. Every document boundary
  is ambiguous; the corpus yields 15. The set is now derived, not hardcoded.
- Unqualified questions defaulted to season 2023, making annually reissued
  documents such as the 2025-26 Rulebook unreachable without an explicit year.
- Extraction fused words in CBA 2017 (289 of 822 chunks) because the default
  `x_tolerance` exceeded that document's kerning. Fused text embeds as noise.
- `tiktoken` counted tokens for a model neither backend uses.
- `n_ctx` of 2048 could not hold the specified prompt budget.
- Renaming a document in the manifest stranded its previous rows in the index.
- The "reserve clause" trigger required a context cue despite having no modern
  sense, which suppressed correct historical routing.

### Changed

- Distribution model is fetch-and-build. The project ships instructions and
  checksums; no copyrighted document or compiled index is redistributed.
- `pdfplumber` (MIT) instead of PyMuPDF (AGPL-3.0), and Qwen2.5 (Apache-2.0) as
  the default local model instead of Llama-3.1.
- Ambiguous seasons return HTTP 409 with both options, not HTTP 300.

### Security

- Only verified chunks enter the vector index, so the withhold-until-approved
  rule holds by construction.
- Extension loading is re-disabled immediately after `sqlite-vec` loads.
- All SQL values are bound parameters.

[Unreleased]: https://github.com/AlphaNerdFx/hoopcourt/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/AlphaNerdFx/hoopcourt/releases/tag/v0.1.0
