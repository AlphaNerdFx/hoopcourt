# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Versions stay below 1.0.0 until a generation backend ships and the answer layer
is measured, not just the retrieval layer.

## [Unreleased]

### Added

- `docs/project/VERSIONING.md`, `docs/project/TESTING.md` and
  `docs/project/CODE_REVIEW.md`: what each version digit means here, what each
  testing tier may depend on and why CI cannot cover all of them, and the
  two-axis review rubric.
- `pyproject.toml` with pytest configuration and a `corpus` marker. Coverage is
  reported in CI and deliberately not gated: a number that blocks a merge
  invites tests written to raise the number rather than to catch a defect.
- **Colloquial rule names are expanded into the corpus's own language before
  retrieval** (`concept_aliases.yaml`, DECISIONS D19). Ten common NBA terms
  appear in 0 of 5,724 chunks; the embedding model bridges most of them unaided,
  but "Stepien Rule" and "Bird rights" failed outright. "What is the Stepien
  Rule?" returned five playing rules about flopping and jump balls, because
  "Stepien" is a surname the model cannot place and "Rule" matches a document
  named Official 2025-26 Rulebook. It now reaches NBA Constitution 2024 p85 at
  distance 0.189. Expansion is substitution, and applies to the embedded text
  only: the prompt always receives the user's own words.
- `tests/test_local_backend.py`, the first tests to touch either local
  generation backend. Twenty-one of them, needing no model and (with one opt-in
  exception) no network: the shard resolver runs against the real Hugging Face
  listing captured as a fixture, `download_gguf` and the `LocalGGUFGenerator`
  constructor run with `huggingface_hub` and `llama_cpp` faked as modules so CI
  exercises them without the binding installed, and `build_generator`'s backend
  order, its fallback, its passthrough of `NBA_GGUF_PATH` and what it logs when
  nothing is available are asserted directly.
  Mutation-tested per TESTING.md rule 1: restoring the old unsharded filename
  turns two red, deleting the llama-cpp fallback turns three, returning the
  wrong shard turns two, downloading only shard 1 turns one, and removing the
  startup warning turns one.
- A `network` pytest marker, opt-in via `NBA_NETWORK_TESTS`. One test uses it,
  checking that the default quantisation still resolves against the live
  Hugging Face listing. Every other test here runs against a snapshot, and a
  snapshot is structurally blind to upstream moving, which is the whole of D21.
- A **Generation backends** section in the README: the three backends, what
  each needs installed, the environment variables that configure them, the size
  and timing of the default model's first run, and the measured CPU latency.
  None of that was written down anywhere a user would look.
- Two evaluation questions covering colloquial phrasing. The suite already had a
  `bird-rights` question that passed while the nickname failed, because it asks
  "Bird rights *for a qualifying veteran free agent*" and so smuggles the
  governing term into the question. The new pair score 0/2 with the alias file
  removed.

### Fixed

- **The documented install had never been performed, by anyone, once.** The
  developer virtualenv was created with `--system-site-packages` and resolved
  fastapi, uvicorn, pdfplumber, yaml, torch and httpx from `~/.local`, so a
  clean checkout was never exercised. Building the first genuinely isolated
  virtualenv this project has had found three things: `httpx` was undeclared and
  `tests/test_api.py` could not even be collected without it; `fastapi~=0.115`
  permitted any 0.x so CI and the developer machine ran different stacks; and
  `pytest` sat in the runtime requirements despite nothing in `src/` or
  `scripts/` importing it.
- **The install is 5.8 GB, not "small".** `requirements.txt` claimed the core
  install "stays small, free, and CPU-only". Measured on a clean virtualenv it
  is 5.8 GB with 15 NVIDIA packages, because `sentence-transformers` pulls
  PyTorch and PyTorch's default wheels carry the CUDA stack. Installing the CPU
  build of torch first gives 1.4 GB with none. Both pass the evaluation at 45/45
  with isolation at 100%. README Quick start now carries the command and the
  numbers.
- **The release workflow could not build the public-domain index.** The
  fused-word gate, which exists to catch PDF kerning failures like
  `foreachSeasonoftheContract`, was firing on proper-noun intercaps: a single
  Robertson plaintiff list reading "Jon McGlocklin, McCoy McLemore" trips it
  three times in one sentence, pushing a judicial-only build to 1.26% against a
  1% limit. Name particles (Mc, Mac, De, Di, La, Le, Van, Von, O') are now
  ignored by both the indexer and `audit_corpus.py`. Measured: 3 chunks flagged
  before, 0 after, real fusion still caught. Never noticed because `release.yml`
  has never run, there being no remote.
- The release workflow runs the whole evaluation on that index rather than one
  category, so the temporal-isolation gate actually runs at release.
  Expectations a partial index cannot meet are skipped rather than failed,
  because a release log full of expected failures teaches people to ignore
  failures.
- **Scanner debris reached chunk text and user-facing source previews.** The
  running-header strip examined only the first line of a page, so marks left by
  CBA 1995's scan survived mid-page (`,----,`, `~. ,.)`). 89 of that document's
  432 chunks carried one; 171 lines index-wide, no other document affected. A
  line with no letter or digit anywhere is not text, so that is the whole rule:
  `84`, `;1` and `(a).` all survive, because a bare number can be a real figure
  and the enumeration is what citations resolve against. Inline debris inside
  lines that also carry words is deliberately left alone.
- **Citation counts were under-reported in the UI.** A bracket only counted as a
  citation if it held a word of four or more letters, which discarded 8 of the 46
  indexed documents, the 2023 NBA CBA and every historical CBA among them,
  because "CBA" is three letters. An answer carrying three citations displayed
  "1/1 citations verified". A page or part locator now qualifies too; quoted
  enumeration still does not.
- **Casual Fan mode could never pass the grounding check.** It puts references on
  a trailing "Sources:" line, as CLAUDE.md sec.6 asks, and writes them
  unbracketed, so every casual answer reported "cites nothing". The block is now
  read, and only lines matching a supplied citation exactly are counted.

- **A fabricated source inside a "Sources:" block was unreportable.** The first
  version of the fix above counted only lines matching a supplied citation and
  silently dropped the rest, so a list of one real and two invented references
  reported as fully grounded. That cured under-reporting by building in
  over-reporting, which is the worse error: CLAUDE.md sec.2.2 calls a
  hallucinated citation a fatal system error, and this made one invisible. The
  block now returns every citation-shaped line and `verify_citations` classifies
  it. Found by a two-axis code review, which reached it independently on both
  axes.
- A trailing list is now read alongside inline citations rather than only when
  none exist, deduplicated so a reference written both ways counts once.
- Heading forms the model actually writes are matched: bare, bolded, singular,
  and with the first reference on the heading line.
- A bare document name with a year (`[2023 NBA CBA]`) is no longer discarded.
  The test that should have caught this asserted only `.ok`, which is true when
  nothing is extracted at all, so it passed while the citation was dropped.
- The source preview cuts on any whitespace, not only a space; a passage whose
  tail was a line break fell back to the mid-word cut the change removed.

Both original defects were found by reading transcripts of real sessions.

- **The default local model named a file that does not exist.**
  `DEFAULT_LOCAL_FILE` was `qwen2.5-7b-instruct-q4_k_m.gguf`, and
  `Qwen/Qwen2.5-7B-Instruct-GGUF` has never published it: whole files stop at
  q3_k_m and q4_k_m ships as a two-part split. So the llama-cpp backend
  documented in CLAUDE.md sec. 3 raised `ValueError: No file found` on every
  machine, `build_generator` swallowed it, and `/health` reported
  `generator: null` -- identical to a machine with no backend installed. The
  constant is now `DEFAULT_LOCAL_QUANT`, a quantisation rather than a filename,
  and `resolve_gguf_files` matches it against the repository listing, returning
  one file or every shard in load order and refusing an incomplete split.
  `Llama.from_pretrained` is no longer used: it matches with a single `fnmatch`
  and rejects both spellings of a split model. See DECISIONS.md D21.
- **`build_generator` now says which backend failed and why.** Every path
  through it logged nothing, so a misconfigured backend and an absent one were
  the same observation. That silence is how the defect above survived the whole
  project.
- The first verification of `requirements-local.txt` and the llama-cpp backend,
  on a virtualenv built without `--system-site-packages`. It installs at exit 0;
  `llama-cpp-python` is sdist-only so it always compiles, but it needs **no
  cmake on the host**, because `scikit-build-core` supplies cmake and ninja to
  its own PEP-517 build environment. About seven minutes on twelve cores, ~40 MB
  added, 1.4 GB total alongside the CPU build of torch, no CUDA packages.
  `requirements-local.txt` said "Needs cmake and a C toolchain"; the C toolchain
  is the real prerequisite and the note was corrected. Both configurations were
  then exercised with Ollama pointed at a refused port: a local `.gguf` via
  `NBA_GGUF_PATH`, and the default, which fetched both Qwen shards and answered
  citing exactly the passage it was handed. Numbers in DECISIONS.md D21.
- `download_gguf` warns before fetching. `build_generator` runs in the API's
  lifespan, so the shard fix turned "no backend, fails in a second, serves
  retrieval" into "downloads 4.7 GB while uvicorn appears to hang". The warning
  names the size and the `NBA_GGUF_PATH` escape.
- **Every published number re-measured, and six of them were wrong.** Found by
  the two-axis review run before tagging. `CLAUDE.md` said "389 unit tests",
  `pyproject.toml` said 428, `STATUS.md` and `HANDOVER.md` said 351; the real
  figure is 460 collected, 456 passing with the index and 431 without it.
  CLAUDE.md sec. 8 gave both 45/45 and 43/43 in the same paragraph, the second
  being the question count from before D19 added two. Five files said the index
  holds 5,725 chunks and one said 5,724; it holds **5,724**. The corpus is
  **3,385 pages**, confirmed twice: `pdfplumber` opened all 18 manifest PDFs and
  summed their page counts, and `scripts/audit_corpus.py` prints
  "3,385 PDF pages". An earlier pass through this section briefly changed the
  figure to 3,320 by trusting D3's stale copy instead of re-running the tool D3
  cites, which is the reconciliation error the rest of this entry exists to
  avoid. D3 now carries the verified number. The Stepien
  retrieval was published three ways -- "rank 2, top hit d=0.189", "distance
  0.189", and "ranks 1st at distance 0.276"; re-measured it is **rank 1 at
  d=0.189**, against five Official 2025-26 Rulebook pages at d>=0.468 without
  the alias expansion. Historical records keep their original figures and now
  say which question count they were measured against: a changelog section for
  a shipped release is a record, not a status page.
- **The README claimed embedding runs on CPU either way.** It does not.
  `Embedder` passes `device=None`, so sentence-transformers picks the device and
  will use CUDA when the default torch wheels have put it there. The
  install-size advice was right; the reason given for it was false.
- **`make test` printed no pass or fail count.** The target passed `-q` while
  `pyproject.toml` already set it in `addopts`, and two of them make `-qq`,
  which suppresses the summary line entirely. On a project whose own rule is to
  check the result rather than trust the absence of noise, the headline test
  command printed dots and nothing else.
- **`GENERATION_MEASUREMENT.md` documented behaviour that had been reversed.**
  Section 10 said a line under a "Sources:" heading "is counted only when it
  matches a supplied citation exactly". That filter was deliberately removed,
  because it reported a model listing one real source and two invented ones as
  fully grounded. The document now matches `extract_sources_block`.
- **Two tests that could not fail.** `test_vector_retrieval.py` asserted
  `behaviour in {"pre-filter", "post-filter"}`, where `behaviour` came from a
  two-branch conditional, and sent the observation it exists to capture to
  `print`, which `-q` swallows. It now records that observation with
  `record_property` and asserts something real in each branch: a build that
  pre-filters must not leak a chunk from another era, and a build that
  post-filters must still reach historical chunks through the metadata form.
  `test_timeline_sources.py` called `pytest.xfail()` in the test body, which
  aborts immediately and can never xpass, so a *fixed* entry would have stayed
  reported as xfailed for ever on a list the module says "can only go down". It
  is now `xfail(strict=True)`, scoped per check rather than shared, so
  `baa-nbl-merger` is no longer exempted from a rule-number check it passes.
  Six xfails become three, and three real checks start running.

### Security

- A pasted UI transcript containing verbatim corpus text was removed from git
  history, not merely untracked. It had been swept in by a `git add -A` against
  sec.7.1, which keeps content out of this repository. The purge rewrote only
  the nine commits after `v0.9.0`: no commit was lost, both tags kept their
  original SHAs, and nothing had been pushed. Neither was visible to
the test suite, because no test read an answer the way a person does, and because
the evaluation only ever runs Legal Scholar mode.


## [0.9.0] - 2026-09-15

Release candidate for 1.0.0, not 1.0.0 itself. Everything listed below is done;
the reason for the lower number is at the end of this section.

An era-aware question answering system over NBA governing documents, with
verifiable citations.

Retrieval is 43/43 on the evaluation with temporal isolation at 100%, the gate,
measured against recall terms deliberately tightened in this release. Generation
is measured separately and honestly: 14 to 18 of 26 answerable questions across
three runs, because it is not reproducible even at temperature 0. Both numbers,
and what they do and do not mean, are in
[docs/evaluation/GENERATION_MEASUREMENT.md](docs/evaluation/GENERATION_MEASUREMENT.md).

**Why this is not 1.0.0.** It was briefly tagged as such, on the strength of a
green test suite and a green evaluation, without the application ever being
launched. Launching it took ten minutes to find three defects, all fixed here:
`make serve` invoked a console script that does not exist in this virtualenv;
`/query` returned HTTP 500 when the generation backend hiccuped, discarding
retrieval that had already succeeded; and the development virtualenv is created
with `include-system-site-packages`, so fastapi, uvicorn, pdfplumber, yaml and
torch all resolve from the developer's home directory. The documented install
has therefore never actually been performed, by anyone, once.

1.0.0 requires a clean-checkout install on a machine that has never built this
project. A green test suite is not evidence that software runs.

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
- `run_eval.py --id` runs named questions, for repairing what a backend restart
  cost without re-running the whole suite.
- `docs/evaluation/GENERATION_MEASUREMENT.md`: what the citation figure measures,
  why it is a range rather than a number, the model comparison and its verdict.

### Fixed

- **An explicit year in a query was competing with the era filter.** The year was
  consumed twice: by the filter, which is its job, and by the embedding, where it
  matched any passage mentioning that year. A governing document states a rule
  once and then works through dated examples of it, so the examples outranked the
  rule. "What was the maximum annual salary a player could receive in 2024?"
  returned five apron and extension worked examples and never reached Article II
  Section 7, the provision that states the rule; with the year removed from the
  embedded text it ranks 2nd. See DECISIONS.md D18.
- **Four recall checks could not fail**, which is what hid the defect above. The
  check accepts any one of several terms, and those four accepted a term
  appearing in 49% to 95% of the expected document. Tightened to discriminative
  terms, which dropped the suite to 41/43 and exposed the retrieval defect; it is
  43/43 again after fixing it, now against the harder terms.
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

[Unreleased]: https://github.com/AlphaNerdFx/hoopcourt/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/AlphaNerdFx/hoopcourt/compare/v0.1.0...v0.9.0
[0.1.0]: https://github.com/AlphaNerdFx/hoopcourt/releases/tag/v0.1.0
