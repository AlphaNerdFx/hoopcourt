# Decision Record

Decisions that departed from the original specification, and the evidence for
each. Every measurement below is reproducible from the scripts named.

---

## D1, Build retrieval-first, not component-by-component

**Context.** `BUILD_SEQUENCE.md` specified nine steps: vector engine, model
loader, OCR parser, schema, router, search, prompt compiler, downloader, admin
UI.

**Problem.** The sequence had no ingestion step. Nothing chunked documents,
generated embeddings, populated the tables, or assembled a FastAPI app,
`grep "FastAPI(\|@app\.\|uvicorn"` over its 2,372 lines returns zero hits.
Step 8 downloads a pre-compiled `nba_legal.db` that no step ever builds.
Completing all nine steps yields a system that cannot answer a question.

**Decision.** Reorder into a retrieval-first walking skeleton, measured against a
labelled eval set written before the retrieval code.

**Consequence.** The project's central claim, chronological neutrality, is
testable with no LLM, no GPU, no API key. That matters more than it sounds:
CUDA does not currently work on this project's own reference hardware (torch
reports the NVIDIA driver too old for its build), so a local-inference-first
order would have blocked everything behind a driver upgrade.

---

## D2, Filter the vec0 metadata column, never the primary key

**This is the anti-bleed mechanism, and the specification had it backwards.**

`sqlite-vec` offers two ways to constrain a KNN search:

| Form | Behaviour |
| --- | --- |
| `chunk_id IN (subquery)`, the primary key, as specified | `k` applied **first**, filter applied after: a **post-filter** |
| `doc_id IN (...)`, a declared metadata column | candidates restricted **before** the search: a **pre-filter** |

Measured on sqlite-vec v0.1.9, 200 chunks across 4 documents, query sitting on
the modern cluster, asking for historical documents:

```
spec form  (chunk_id IN subquery), k=5  ->  0 rows
metadata   (doc_id IN (3,4)),      k=5  ->  5 correct historical rows
```

`IMPLEMENTATION_PLAN.md:235` rejected post-filtering by name, *"if modern chunks
dominate similarity scores, the filtered results will be empty"*, chose
pre-filtering, and then specified post-filtering's code. The spec's own Step 6
test cannot detect this: with two chunks and `k=1`, a post-filter passes by luck.

**Decision.** `vec_chunks` declares `doc_id INTEGER` as a metadata column.
`tests/test_vector_retrieval.py` carries a characterisation test that fails if a
future sqlite-vec makes the PK form a true pre-filter, so the deviation can be
revisited rather than silently outliving its reason.

### D2a, The outer `ORDER BY` is load-bearing

With an IN-list of N documents, sqlite-vec returns `k` rows **per document**,
grouped by document and not globally sorted:

```
k=3, doc_id IN (3,4,5)  ->  9 rows: doc 3's top-3, then doc 4's, then doc 5's
```

Without `ORDER BY distance ASC LIMIT k` on the outer query the caller gets the
wrong top-k in the wrong order, quietly, with no error.

---

## D3, No OCR

**Measured** (`scripts/audit_corpus.py`, all 18 documents, 3,320 pages): every
document has a usable text layer, median 558-4,572 characters per page. Every one
is single-column.

`CBA 1995.pdf` is the only true scan (1 font object, 295 image XObjects) and its
producer is *Adobe Acrobat 9.46 Paper Capture Plug-in*, it already carries an
OCR text layer, and extracts cleanly.

**Decision.** Cut Step 3 (PaddleOCR multi-column pipeline, sized L, the largest
step in the plan). 300-DPI OCR over born-digital text is slower *and* lossier
than direct extraction. `scripts/audit_corpus.py` re-runs the measurement and
exits non-zero if a future document needs OCR.

**Knock-on.** Step 9 (Streamlit OCR correction UI) also goes: it existed to
correct OCR output and would now guard an empty queue. `is_verified` stays in the
schema as defence-in-depth, with `vec_chunks` receiving only verified chunks so
the withhold-until-approved rule holds by construction.

---

## D4, Fetch-and-build instead of IPFS/BitTorrent

Step 8 proposed distributing a pre-compiled `nba_legal.db` over IPFS gateways
with a magnet-link fallback, to avoid shipping copyrighted PDFs.

The database contains the full text of those documents. Distributing it is the
same act as distributing the PDFs; moving it onto a peer-to-peer network
relocates the exposure rather than curing it. It also hardcoded the SHA-256 of a
file no step in the plan ever produced.

**Decision.** Distribute **instructions and checksums, not content**.
`scripts/fetch_corpus.py` reports what is missing and where to obtain it from
official or public-record sources, and records/verifies SHA-256 hashes;
`scripts/build_index.py` compiles the index locally. Nothing copyrighted is
redistributed, and the result is still reproducible and verifiable.

---

## D5, An unqualified question means *this season*, not 2023

`DEFAULT_MODERN_SEASON` was pinned to 2023, the year the standing CBA was signed.

That made every annually-reissued document unreachable without an explicit year:
the 2025-26 Rulebook, Officials Guide and Concussion Policy each govern season
2025 only, and 2023 is not in that window. "What are the shot clock rules?"
could only ever return CBA text, the rulebook was in the index and unreachable.

**Found by the eval set**, which is the argument for writing one before tuning
retrieval. The router's routing decision was self-consistent; only a question
with a known expected *source document* exposed the gap.

**Decision.** Unqualified questions route to `current_season()`, the NBA season
in progress, rolling over in October. Eval expectations use a `CURRENT` sentinel
so they track the rollover instead of rotting into a hardcoded year.

---

## D6, Licence-driven dependency choices

The project is MIT and intended for public distribution, so copyleft and
restricted-use dependencies were rejected in favour of permissive equivalents.

| Rejected | Licence problem | Chosen |
| --- | --- | --- |
| PyMuPDF / `fitz` | AGPL-3.0 copyleft | `pdfplumber` (MIT) |
| `nomic-embed-text-v1.5` | requires `trust_remote_code=True` (arbitrary RCE at import) | `BAAI/bge-base-en-v1.5` (MIT, same 768 dims) |
| Llama-3.1-8B | Community Licence: acceptable-use restrictions, 700M-MAU clause | Qwen2.5-7B-Instruct (Apache-2.0) |

Llama-3.1 remains supported by passing its repo id; it is simply not the default.

---

## D7, Token counting with the model's own tokenizer

Step 5 gated the 1,000-token limit with `tiktoken`/`cl100k_base`, OpenAI's BPE,
which matches neither backend. The count would be 10-30% off from what the model
actually sees, sometimes permissively, and the gate's stated purpose is blocking
long adversarial input.

**Decision.** `src/api/tokens.py` selects a counter matching the configured
backend. The default is a deliberately pessimistic character heuristic
(3.2 chars/token) because merely *importing* transformers costs ~70s on a cold
filesystem, which would be paid at application startup; exact counting is opt-in
via `NBA_TOKEN_COUNTER=local|cloud`. The heuristic over-counts, so the gate stays
conservative either way.

---

## D8, HTTP 409 for an ambiguous season, not HTTP 300

`300 Multiple Choices` is a redirect status; clients, proxies and browsers treat
it as one. PRD User Story 1 describes a UI clarification prompt, which is not a
redirect. `/query` returns **409** with both season options and
`resend_with: clarified_season`.

---

## D9, `n_ctx` 8192, not 2048

The 2048 cap was arithmetically impossible against the system's own numbers: a
1,000-token question cap, plus five retrieved legal chunks, plus the system
prompt, exceeds 2048 before generation starts, silently truncating away the
citations the whole design depends on.

A 7-8B GQA model spends ~128 KiB/token of KV cache, so 8192 tokens is ~1 GiB on
top of ~4.9 GiB of Q4_K_M weights: about 6 GiB, comfortably inside the 8 GB
RTX 4060 of `CLAUDE.md` §3.1.

---

## D10, Ambiguous years are derived from the corpus, not hardcoded to 2023

`CLAUDE.md` §5.2 and PRD User Story 1 single out **2023**: it may mean the
2022-23 season (CBA 2017) or 2023-24 (2023 CBA), so the system must ask which.
That reasoning is right and its scope is wrong. Nothing about 2023 is special,
*every* document-window boundary creates the same ambiguity.

Measured against the shipped manifest, **fourteen** years are ambiguous:

```
1995 1999 2003 2004 2005 2011 2017 2019 2023 2024 2025 2026 2027 2030
```

`2011` is the clearest example. The 2010-11 season is governed by CBA 2005 and
2011-12 by CBA 2011, two different agreements with different luxury-tax rules.
Asked "what was the luxury tax in 2011?", the system resolved
`start_season <= 2011 <= end_season`, silently picked CBA 2011, and returned a
confident answer with a real-looking citation that is wrong for half the
question's possible meanings.

That is precisely the failure this project exists to prevent, and the spec's own
mechanism for it, the clarification prompt, was wired to 1 of 14 cases.

**Decision.** `db.schema.ambiguous_seasons(conn)` derives the set from the index:
year *Y* is ambiguous when the seasons keyed *Y-1* and *Y* are covered by
different document sets. The API computes it at startup and injects it into the
router; the router keeps a static `{2023}` fallback for pure/offline use.

Deriving it rather than listing it matters for the same reason the windows
themselves carry comments: adding or re-scoping a document silently moves these
boundaries, and a hardcoded list would go stale without any test failing.

**Cost.** More questions now return 409 instead of an answer. That is the right
trade for this system, `CLAUDE.md` §2.2 treats an ungrounded or wrong-era answer
as a fatal error, not a degraded one, so one extra round-trip beats a confidently
wrong citation. `tests/eval/questions.yaml` carries a boundary-year regression
pair (`trigger-ambiguous-2011-boundary` / `-resolved`).

---

## D11, `x_tolerance=1.5` for text extraction

`pdfplumber` inserts a space when the horizontal gap between two characters
exceeds `x_tolerance` points. The default, 3, is wider than CBA 2017's kerning,
so whole phrases came out fused:

```
Minimum Annual Salary Scale for the 2018-19 Salary Cap Year shall apply
foreachSeasonoftheContract
```

**Scale of the problem.** 308 of 5,262 indexed chunks (5.9%) contained fused
tokens, and **289 of them were in CBA 2017**, 35% of that document. A fused span
tokenizes into garbage, so its embedding is noise: the chunk sits in the index,
is retrievable by `doc_id`, and cannot be found by meaning. That silently
degraded retrieval for the entire 2017-2022 era.

This is a nastier failure than an extraction error, because every downstream
check passed. The page had plenty of text, the audit reported a healthy text
layer, the citations were correct, and the chunk counts looked right.

**Measured across six documents** at `x_tolerance=1.5` (five-page samples):

| Document | fused (default) | fused (1.5) | over-split proxy |
| --- | --- | --- | --- |
| CBA 2017 | 16 | **0** | 46 → 49 |
| 2023 NBA CBA | 0 | 0 | unchanged |
| CBA 1995 | 0 | 0 | unchanged |
| CBA 2011 | 0 | 0 | unchanged |
| Rulebook | 0 | 0 | unchanged |
| NBPA CBA 1999 | 1 | 1 | unchanged |

Both failure directions were checked. Too *small* a tolerance splits words
("Sal ary"), so the table tracks short orphan tokens as an over-splitting proxy;
it moves by +3 on CBA 2017 and is unchanged elsewhere. Lower is safe here.

**Decision.** `X_TOLERANCE = 1.5` in `src/parser/extract.py`, and
`scripts/audit_corpus.py` now measures fused tokens per page alongside characters
per page, failing with `WORDS FUSED - tune X_TOLERANCE`. A document can have a
perfect text layer and still extract unusably; the audit had to check for that,
not just for the presence of text.

---

## D12, The Uniform Player Contract is scoped to the CBA it is an exhibit to

`NBA Player Contract Exhibit A.pdf` is Exhibit A to the **2017** CBA. It was
listed as `2017-2030`, on the reasoning that the contract is a standing template.

The template is standing; its contents are not. The specifics it embeds,
maximum-salary percentages, apron consequences, option and bonus mechanics, were
changed by the 2023 CBA and are not updated in this file. A window running to
2030 therefore let a 2024 question retrieve 2017 terms under a citation that
looks current. That is rule bleeding wearing a template's clothes: the era filter
did its job, and the document inside the era was stale.

**Decision.** Scope it `2017-2022`, the seasons its parent CBA governs, and
recategorise it `Historical`. Nothing is lost: the 2023 CBA contains its own
Exhibit A (113 indexed chunks reference the Uniform Player Contract; the exhibits
begin around p. 560), so 2023+ contract questions are answered by the governing
document itself.

**Measured afterwards, worth knowing.** The standalone extract is *inert*: 11 of
12 distinctive phrases in it appear verbatim in the indexed CBA 2017, and across
five contract-focused queries at k=5 it was retrieved **zero** times, CBA 2017's
~986 chunks outrank its 35, and no cross-document near-duplicates surfaced. So it
neither crowds results nor contributes them. It is 35 chunks of dead weight,
kept because a clearer citation (`Uniform Player Contract (2017 CBA Exhibit A),
p. 5`) is marginally better than a page deep in a CBA's exhibits if it ever does
surface. Its `source_url` remains the one open issue, see D13.

---

## D13, Manifest integrity is tested, not trusted

Five defects arrived in one round of hand-editing `corpus_manifest.yaml`, none of
which raised an error:

| Defect | Symptom without a guard |
| --- | --- |
| `.pdf` listed, `.PDF` on disk | Linux is case-sensitive; the build silently skips the document |
| 2012 Constitution `end_season: 2019` | Two constitutions govern 2019 |
| `source_url` pasted from the 2019 entry | The URL serves a different document |
| Contract window `2017-2030` | Stale terms retrievable for 2024 (D12) |
| Document renamed in the manifest | The old row survives with 35 orphaned, still-searchable chunks |

Only the last two are visible in retrieval at all, and both look like correct
answers. So the manifest is now checked mechanically:

* **`tests/test_manifest.py`**, schema, unique names and paths, no overlapping
  windows within a lineage, no gaps in the CBA lineage, no shared `source_url`
  between documents, and case-sensitive file existence.
* **`scripts/fetch_corpus.py --check-urls`**, every source is fetched and its
  size compared with the local file, catching URLs that serve the wrong document
  or an HTML viewer page rather than a PDF.
* **`scripts/build_index.py`** now prunes indexed documents the manifest no
  longer lists, so a rename cannot strand its predecessor.

**Resolved:** the entry was dropped. Its only source was a Scribd viewer page,
which `DATA_SOURCES.md` rules out, and D12 had already measured the document as
inert: zero retrievals across five contract-focused queries at k=5, because
CBA 2017 contains the same text in roughly thirty times as many chunks. Removing
it cost 35 chunks and no retrieval quality, and every source URL in the corpus
now resolves to the right document. The file itself is untouched under `data/`,
so relisting it is one manifest entry away.

---

## D14, Statistics belong in a table, not the vector index

Statistics were requested as a corpus expansion. They are not one.

"How many rebounds did Rodman average in 1996-97" is a query, not a passage to
retrieve. Embedding rows of numbers and relying on cosine distance to surface the
right one produces answers that are confident, plausible and wrong, which is the
precise failure mode this project was built to prevent. A near-miss in a legal
passage is still about the right subject; a near-miss in a statistics table is a
different player.

**Decision.** Statistics get their own path: a `stats` table and generated SQL
over it. They share `TemporalRouter` (`src/api/router.py`), because a season
still has to be resolved, and nothing else. They do not enter `vec_chunks`.

A classifier decides documentary versus statistical, and the response says which
engine answered. A number read from a table and a quotation from the CBA carry
different kinds of authority, which is the same distinction `source_tier` already
draws for documents.

**Sourcing follows the existing posture.** `nba_api` is MIT-licensed, but the
data behind stats.nba.com is not and no bulk-data licence is published. An open
client does not grant rights to the upstream data, which is the same trap that
disqualified Scribd for the Uniform Player Contract and Capsheets as a name. The
user fetches on their own machine; the project redistributes nothing.

---

## D15, The fine-tune may only see public-domain data

The goal is a published, FOSS-licensed model. That single word, published,
determines the training set.

Weights memorise. A model trained on the corpus and uploaded to Hugging Face
distributes derived copyrighted text, which is exactly the act D4 rejected when
it killed the plan to ship a compiled `nba_legal.db` over IPFS. Moving the text
from a database into a set of weights does not change what is being handed out.

**Decision.** Training data is limited to sources the project may lawfully
redistribute:

* the seven public-domain court opinions from the Caselaw Access Project,
* `historical_timeline.yaml`, which is the project's own writing,
* synthetic question-answer pairs derived from those two.

No CBA, Constitution or rulebook text, at any stage, including in prompts
captured for training.

**The target is narrow on purpose**: citation discipline. Copy the permitted
citation verbatim, never invent a pinpoint, refuse when the context is thin. That
is the measured gap, retrieval scores 100% while citation validity does not, and
it is a behaviour rather than knowledge, so it can be taught without the model
needing to have read the agreements.

**Gate.** The adapter ships only if it beats the base model plus the closed-list
prompt on the same 43 evaluation questions, measured the same way. If it loses,
the negative result gets published instead. Note also that only `mistral:7b` has
ever been measured: trying stronger off-the-shelf models is the cheap experiment
that must precede this expensive one.

---

## D16, Serving infrastructure is sequenced to load, not to ambition

vLLM and llm-d were both requested for the MVP. Both solve concurrency, and the
MVP has one user.

vLLM's advantage appears at roughly five or more simultaneous requests; below
that it reserves more GPU memory than Ollama and returns nothing for it. llm-d is
a CNCF Kubernetes project that disaggregates prefill and decode across
compute-optimised and memory-optimised *nodes*. On one 8GB laptop GPU there is
nothing to disaggregate, and adopting it would buy a Kubernetes dependency to
serve a single person.

**Decision.**

| Stage | Serving | Trigger |
| --- | --- | --- |
| now | Ollama | one user |
| small | vLLM, single GPU | sustained concurrency, roughly 5+ |
| large | llm-d on Kubernetes | multiple GPUs or nodes |

Ollama is not a compromise being tolerated until something better arrives. It
already holds the model entirely in VRAM through its own `cuda_v12` runtime, it
manages eviction so a 7B runs where an in-process load would not fit, and at this
scale it is the correct tool.

**The real gate is not technical.** Every copyright decision in this project
rests on users fetching documents and building an index locally, so nothing is
redistributed. A hosted service inverts that: the project would hold the corpus
and serve answers derived from it to the public. No serving stack addresses that,
and it needs a qualified answer before any public endpoint exists.

---

## D17, Hoopcourt is a tool, not a service

An earlier roadmap ended in a hosted service, with vLLM and llm-d as the serving
stack. That end state is dropped.

**What it removes.** vLLM and llm-d leave the project entirely rather than being
deferred: both exist to serve many simultaneous requests, and a tool that runs on
one person's laptop has one. Ollama, already holding the model in VRAM through
its own CUDA runtime, is not a placeholder for something better. At this scale it
is the right answer.

**What it removes that matters more.** Every copyright position here rests on the
user fetching documents themselves and building their own index, so nothing
copyrighted is redistributed (D4, D12, D13). A hosted service would have inverted
that: the project holding the corpus and serving derived answers to the public.
No serving technology addresses it, and it would have needed a qualified legal
answer before a single public request. As a tool the posture holds end to end.

**What it changes about the fine-tune.** D15's purpose narrows. It is no longer
about answer quality at scale for strangers; it is about one person's local
experience. The public-domain-only training boundary is unaffected, because that
was never about serving. It was about publishing weights.

**Reversing this** reopens the copyright question in full. It is a product
decision, not an infrastructure one.

---

## D18, The embedded query is not the query the user typed

An explicit year in a question is consumed twice by the obvious implementation:
once by the era filter, which is what it is for, and again by the embedding,
where it matches any passage that happens to mention that year. The second use
is not neutral, it is actively harmful, and the reason is structural rather than
incidental.

A governing document states a rule **once** and then works through **dated
examples** of it for pages. The 2023 CBA states the Maximum Annual Salary in
Article II, Section 7, and then discusses the 2024-25 Salary Cap Year in dozens
of apron, trade and extension examples. Embedding "2024" therefore ranks the
examples above the rule, reliably, every time.

**Measured.** For "What was the maximum annual salary a player could receive in
2024?" the top five were a CBA 101 extension worked example, three apron and
traded-player-exception passages, and a cap-hold passage. Article II Section 7
did not appear at all. With the year removed from the embedded text and nothing
else changed, that provision ranks **2nd**.

`src/api/router.retrieval_text` removes years from the text passed to the
embedder, and only when `route_action` is `strict_season_filter`, meaning the
era filter has already restricted the candidate documents to that season.
Nothing about the temporal scope is lost: it has simply moved to the mechanism
built for it. If a year was never used for routing it may carry meaning of its
own, so it is left alone.

**Why this went unnoticed.** The evaluation's `recall` check accepts any one of
several terms. Four questions were passing on a term that appears throughout the
expected document: `Salary Cap` in 49% of CBA 101's chunks, `Agent` in 95% of
the agents regulations, `Members` in 60% of the Constitution. A disjunction
containing one near-universal term cannot fail, so it asserted nothing, and a
question whose answer was never retrieved still scored as recalled. Those four
were tightened to discriminative terms (each under 30%, most under 3%), which
dropped the suite to 41/43 and exposed the defect. With D18 it is 43/43 against
the harder terms. (The evaluation held 43 questions when this was measured. D19
added two colloquial-phrasing questions, so the same suite now reads 45/45.)

This is the blind spot `docs/operations/STATUS.md` had already warned about,
caught in the act: a green evaluation meant routing was right and nothing bled
across eras, not that the operative passage was retrieved.

**The general lesson**, which outlives this fix: a retrieval metric built on
"does any expected term appear" is only as strong as its rarest accepted term.
Check the corpus frequency of every term before trusting the check that uses it.

---

## D19, Colloquial rule names are expanded for retrieval, never for the answer

The corpus is written in contract English. Users ask in the language of
broadcasts and forums. Where those vocabularies share no words **and** no
semantic bridge, retrieval does not degrade, it fails outright: the query
embedding has nothing to be near.

**Measured.** Ten common NBA terms appear in **0 of 5,724 chunks**, including
"Bird rights", "luxury tax", "hard cap" and "supermax". That count alone is not
the criterion, because the embedding model bridges most of them unaided: asked
on the shipped index, "luxury tax" reaches "Tax Level" at rank 3, "hard cap"
reaches "Apron Level" at rank 2, and "supermax" reaches "Designated Veteran" at
rank 3. None of those phrases appear verbatim anywhere.

Two did fail completely:

| question | before | after |
| --- | --- | --- |
| "What is the Stepien Rule?" | not in top 5 | rank 1, d=0.189 |
| "What are Bird rights?" | not in top 5 | rank 1 |

The Stepien case shows the mechanism clearly. "Stepien" is a surname the model
has no useful representation for, and the remaining content word, "Rule",
matches a document named **Official 2025-26 Rulebook**. The top five were
playing rules about flopping and jump balls. The governing passage, NBA
Constitution 2024 p85, never uses the name.

**The rule for adding an entry:** the nickname must be measured *failing to
retrieve the governing language* first. Absence from the corpus is not enough,
or the list would carry ten entries of which eight are noise. Every entry in
`concept_aliases.yaml` carries the measurement that justified it, and a test
asserts that field is non-empty.

**Substitution, not addition.** Appending the expansion would leave the nickname
in the embedded text, and in the Stepien case the nickname *is* the noise.

**Retrieval only.** `build_messages` receives the user's own words, exactly as
D18 strips the year for the embedding alone. Rewriting someone's question and
then answering the rewrite returns an answer to a question they did not ask.

**Why this is not the `historical_concept_mapper` table.** That table maps
archaic terms to modern analogies for Casual Fan mode, so a reader meeting
"reserve clause" gets "permanent franchise tag". Its purpose is explanation for
a human; this is query rewriting for an embedding model. Same shape, different
job, and overloading it would make both harder to reason about, for the same
reason `historical_record` is a fourth source tier rather than an overloaded
`timeline`.

**The eval question this exposed.** The suite already had a `bird-rights`
question that passed. It asks "What are Bird rights *for a qualifying veteran
free agent*?", smuggling the governing term into the question, so it never
tested the nickname. A question written by someone who knows the answer can
encode the answer. The two questions added here ask the way a person asks, and
they fail 0/2 with the alias file removed.

---

## D20, The primary-key filter is not portable, which strengthens D2

D2 recorded that the specification's era filter, constraining the vec0 PRIMARY
KEY through a subquery, is applied after `k` and therefore returns zero rows
when another era dominates the ranking. That measurement was correct and is
still reproducible: SQLite 3.37.2 with sqlite-vec v0.1.9 returns 0 rows.

It is not universal. The first CI run this repository has ever executed failed
the characterisation test on **the same sqlite-vec version**, returning 5 rows.
The variable is the SQLite build underneath: a newer query planner pushes the
`chunk_id IN (...)` constraint into the virtual-table scan, so the specification's
form happens to work there.

**This makes the case for the metadata column stronger, not weaker.** The
original argument was "the PK form is broken". The accurate argument is worse
for the PK form: *whether it works depends on which SQLite the user happens to
have*. A project whose central guarantee is that a 1975 question never sees 2023
text cannot have that guarantee vary by interpreter build. Era isolation has to
hold on the oldest SQLite a user might run, and the metadata column holds on
every build tested.

The characterisation test was rewritten to match. It now records which behaviour
the local SQLite exhibits and prints it, while a second test asserts the thing
that must be true everywhere: the metadata-column filter returns rows, and every
row belongs to the requested era. Demanding one planner behaviour made the suite
fail on a correct system.

**The general lesson.** A characterisation test pins behaviour you do not
control. When it fails, the first question is whether the world changed or the
test was over-specified. Here it was over-specified: it asserted a symptom
(zero rows) rather than the property that mattered (isolation holds regardless).

---

## D21, A quantisation is not a filename, and a swallowed exception hid it

`DEFAULT_LOCAL_FILE` named `qwen2.5-7b-instruct-q4_k_m.gguf`. No such file has
ever existed. `Qwen/Qwen2.5-7B-Instruct-GGUF` publishes whole files only up to
q3_k_m; from q4_0 upwards every quantisation is split, and q4_k_m exists solely
as `...-q4_k_m-00001-of-00002.gguf` and `...-00002-of-00002.gguf`. So the
default local backend named in CLAUDE.md sec. 3 raised, on every machine, from
the commit that introduced it:

```
ValueError: No file found in Qwen/Qwen2.5-7B-Instruct-GGUF
that match qwen2.5-7b-instruct-q4_k_m.gguf
```

**Two failures, and the second is the one worth recording.** The first is a
wrong constant, which is ordinary. The second is that nothing could report it.
`build_generator` caught `Exception` and returned `None`; `/health` then
reported `generator: null`, which is also exactly what it reports on a machine
with no generation backend installed at all. A null generator is a *supported*
state here: retrieval is the part that has to be right and the API still answers
with cited sources (D16). That design is correct, and it is precisely what made
the defect invisible. A user without Ollama saw a system that looked configured
as documented, with a backend that had never once loaded.

**Why `Llama.from_pretrained` is no longer used.** It matches the
filename with one `fnmatch` and insists on exactly one hit, so the unsharded
name raises `No file found` and the glob `...-q4_k_m*.gguf` raises `Multiple
files found`. It does accept `additional_files`, so it can be made to work by
naming shard 1 as the filename and shard 2 as an extra. That puts the upstream
split layout into two constants in this repo, where a re-quantisation upstream
breaks it again, silently, in the same way.

**The fix.** Resolution moved here. `resolve_gguf_files` matches a quantisation
*stem* against the repository listing and returns either the single file or
every shard in load order; an incomplete split is refused rather than
half-downloaded, because a lone shard 1 is a file llama.cpp opens and then fails
partway through loading. The constant is now `DEFAULT_LOCAL_QUANT`, a
quantisation, which is the thing a person actually chooses. Every failure in
`build_generator` is logged with the backend and the cause.

**Measured, 2026-09-21, on a clean virtualenv built without
`--system-site-packages`:** `requirements-local.txt` installs at exit 0.
`llama-cpp-python` 0.3.35 is sdist-only on PyPI, so it always compiles, but it
needs **no cmake on the host**: `scikit-build-core` pulls cmake and ninja as
PEP-517 build dependencies into the isolated build environment, and a C/C++
compiler is the real prerequisite. Build takes about seven minutes on twelve
cores. Total footprint is 1.4 GB alongside the CPU build of torch, which is the
same figure as `requirements.txt` alone; the binding itself is ~40 MB.
With Ollama pointed at a refused port, `build_generator` falls through to
`LocalGGUFGenerator` in both configurations:

* **`NBA_GGUF_PATH` set** to a 3B on disk: app startup 32s, `/health` reports
  the loaded model, and `/query` answers in 110-175s with five retrieved chunks.
  A 2023 query still returned 409 and the Stepien question still reached NBA
  Constitution 2024 p85, so routing and D19 are unaffected by the backend.
* **Nothing set**, the default: both shards resolved, 4.68 GB fetched in 768s
  (3.99 + 0.69), model loaded, and `build_generator` returned
  `local:Qwen/Qwen2.5-7B-Instruct-GGUF/qwen2.5-7b-instruct-q4_k_m`. One chunk
  in, 76s to a correct answer citing `[2023 NBA CBA, Article II, Section 7,
  p. 37]`, exactly the citation it was handed. Loading the cached 4 GB file
  again on a cold page cache cost 438s, so startup is slow on every run here,
  not only the first.

These are the degraded CPU figures CLAUDE.md sec. 3.1 warns about rather than a
fault, and the two models are not comparable to each other: different sizes,
different context.

**One regression the fix introduces.** `build_generator` runs inside the API's
lifespan. Before, a machine with no Ollama and no `NBA_GGUF_PATH` failed in
about a second and served retrieval only. Now it downloads several GB while
`uvicorn` appears to hang. `download_gguf` therefore logs at warning level
before fetching, naming the size and the `NBA_GGUF_PATH` escape.

**The general lesson.** TESTING.md rule 4 says what is not exercised is not
measured. It was written about evaluation styles; it applies with equal force to
install paths and to backends. And an `except Exception` that a documented
feature depends on has to say what it caught, or the feature's absence is
indistinguishable from its being switched off.
