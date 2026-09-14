# CLAUDE.md: Project Constitution & System Directives
## Project: Hoopcourt (V1.0)

---

## 1. Non-Negotiable Persona & Behavioral Rules

The AI advisor reading this file MUST strictly adhere to the following directives in every single response:

```
You are my advisor who happens to be smarter than me. You must follow these rules in every reply: 
1. Never start with agreement. Your first sentence must challenge my assumption, point out what I'm missing, or ask a question that exposes a gap in my thinking. 
2. Rate your confidence. Before any claim, tag it [Certain] if you have hard evidence, [Likely] if it's a strong inference, [Guessing] if you are filling gaps. If most of your reply is guessing, say so first. 
3. Kill these phrases for good: "Great question", "You're absolutely right", "That makes a lot of sense", "Absolutely", "Definitely". 
4. Disagree with structure. When I'm wrong, say: "I disagree because [reason]. Here's what I'd do instead [alternative]. The risk in your approach is [specific downside]." 
5. Give me the uncomfortable answer first. If there's a truth I probably don't want to hear, lead with it. 
6. No warm up paragraphs. Start with the most useful thing you can say. 
7. If I push back, don't fold. Hold your position unless I give you genuinely new information.
```

---

## 2. Project Mission & Grounding Rules

### 2.1 Core Mission
Hoopcourt is an era-agnostic legal NBA expert RAG engine designed to interpret the complex legal mechanisms of the NBA Collective Bargaining Agreement (CBA), Constitution, and draft procedures from the 1940s to the present day.

### 2.2 Chronological Neutrality & Anti-Bleed Mandate
* **Zero Rule Bleeding**: Historical queries must NEVER be contaminated by modern rules (e.g., applying 2023 CBA "Second Apron" rules to a 1995 query).
* **Grounding Rule**: Every answer must be strictly derived from retrieved database chunks or verified historical JSON timelines. Hallucinated citations or ungrounded claims are treated as fatal system errors.

---

## 3. Technology Stack & Deployment Profiles

* **API Layer**: FastAPI + Pydantic (Enforcing request validation and token limits).
* **Vector Engine**: SQLite + `sqlite-vec` (Native pure-C extension; `vec0` virtual table with cosine distance).
* **Local LLM**: `Qwen2.5-7B-Instruct` (`Q4_K_M` GGUF via `llama-cpp-python`; CUDA optional, CPU works). Apache-2.0, unlike the Llama 3.1 Community License, which carries acceptable-use restrictions and a 700M-MAU clause incompatible with this project's MIT licence. Llama-3.1-8B remains supported by passing its repo id.
* **Cloud LLM** *(optional, bring-your-own-key, never required)*: `claude-opus-5` (Anthropic API).
* **Embeddings**: `BAAI/bge-base-en-v1.5` (768 dimensions, MIT). Chosen over `nomic-embed-text-v1.5`, which requires `trust_remote_code=True`, arbitrary code execution at import, in a project whose security posture is about supply-chain integrity, and needs `search_document:`/`search_query:` task prefixes that were never applied.
* **Text Extraction**: `pdfplumber` (MIT). **No OCR.** All 18 corpus PDFs
  (3,385 pages) are single-column with usable text layers, including
  `CBA 1995.pdf`, whose scan already carries an Acrobat Paper Capture OCR layer.
  `scripts/audit_corpus.py` re-checks this, and also measures fused words per
  page: a document can have a perfect text layer and still extract unusably.
  `x_tolerance=1.5`, because the default fused 35% of CBA 2017's chunks into
  noise that embedded as garbage while every other check stayed green
  (DECISIONS.md D11).
* **Pre-1995 sources**: no public CBA text before 1995 appears to survive, so
  1946-1994 is carried by 7 public-domain court opinions from the Caselaw Access
  Project plus 21 curated timeline entries. `documents.source_tier`
  (`primary` / `judicial` / `timeline`) declares what a citation is worth.
* **Admin UI**: not built. Its purpose was correcting OCR output; with no OCR in the pipeline it would guard an empty queue. `is_verified` remains in the schema as defence-in-depth.

### 3.1 Supported Hardware Profiles
* **Default Laptop Profile**: NVIDIA RTX 4060 (8GB VRAM) + 16GB System RAM.
  * Model context (`n_ctx`) set to **8192**. The former 2048 cap was arithmetically impossible: a 1,000-token question plus five retrieved legal chunks plus the system prompt exceeds it before generation begins, silently truncating away the citations the design depends on. A 7-8B GQA model spends ~128 KiB/token of KV cache, so 8192 tokens is ~1 GiB on top of ~4.9 GiB of Q4_K_M weights, about 6 GiB, which fits 8 GB VRAM.
  * **System RAM is the binding constraint on WSL2, not VRAM.** WSL2 grants the
    Linux guest roughly half the Windows total by default, so the 16 GB profile
    above is 7.4 GB usable in practice. Below about 8 GB free, ollama logs
    `disabling mmap for llama-server load due to host memory pressure` and loads
    the weights into anonymous memory instead of a mapped file: 4.1 GiB on disk
    becomes ~6.3 GiB of RSS the kernel cannot evict, and the OOM killer takes
    llama-server. Measured on this machine, that cost 3 of 26 evaluation
    questions in one run. Raise the guest allocation in `.wslconfig`
    (`memory=12GB`) or do not run anything else during a generation run.
    `OllamaGenerator` retries the transport failure that follows a restart, so
    the answer is delayed rather than lost.
* **CPU-Only Fallback**: Startup script (`init.sh`) must warn users of degraded performance ($<3$ tokens/sec) and prompt for explicit confirmation or fallback to Cloud Mode.

---

## 4. Relational & Vector Data Model Contracts

```sql
-- Core Documents Catalog
CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_name TEXT UNIQUE NOT NULL,
    category TEXT CHECK (category IN ('Historical', 'Current Operational', 'Current Governing')) NOT NULL,
    start_season INTEGER NOT NULL,
    end_season INTEGER NOT NULL,
    source_url TEXT NOT NULL
);

-- Text Chunks with Verification Bit
CREATE TABLE document_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER NOT NULL,
    chunk_hash TEXT UNIQUE NOT NULL,
    article_num TEXT,          -- restored from the PRD schema: citations must
    section_num TEXT,          -- resolve to a section, not merely a page
    page_num INTEGER NOT NULL,
    is_verified INTEGER DEFAULT 0 CHECK (is_verified IN (0, 1)),
    text_content TEXT NOT NULL,
    FOREIGN KEY (doc_id) REFERENCES documents (id) ON DELETE CASCADE
);

-- Pure-C Virtual Vector Table (sqlite-vec).
-- doc_id is a METADATA COLUMN, and this is what makes era isolation work.
-- Measured on sqlite-vec v0.1.9: constraining the PRIMARY KEY
-- (chunk_id IN (subquery)) applies k FIRST and filters afterwards -- a
-- post-filter that returns ZERO rows when another era dominates the ranking.
-- Constraining a declared metadata column restricts candidates BEFORE the
-- search. See src/db/schema.py and the characterisation test in
-- tests/test_vector_retrieval.py.
CREATE VIRTUAL TABLE vec_chunks USING vec0(
    chunk_id INTEGER PRIMARY KEY,
    doc_id INTEGER,
    embedding float[768] distance_metric=cosine
);

-- Desynchronization Prevention Trigger
CREATE TRIGGER sync_vec_index_on_chunk_deletion
AFTER DELETE ON document_chunks
BEGIN
    DELETE FROM vec_chunks WHERE chunk_id = OLD.id;
END;

-- Historical Slang & Extinct Concept Analogies
CREATE TABLE historical_concept_mapper (
    concept_id INTEGER PRIMARY KEY AUTOINCREMENT,
    archaic_term TEXT UNIQUE NOT NULL,
    modern_analogy TEXT NOT NULL,
    simplified_explanation TEXT NOT NULL,
    valid_from_year INTEGER NOT NULL,
    valid_to_year INTEGER NOT NULL
);
```

---

## 5. Chronology Engine & Query Routing Logic

The system strictly bounds prompt size and context retrieval:
1. **Token Limit Gating**: requests over 1,000 tokens are dropped with HTTP 400
   (`src/api/tokens.py`). **Not `tiktoken`.** `cl100k_base` is OpenAI's BPE and
   matches neither backend this project ships, so the gate would be enforced
   against a number 10-30% off from what the model actually sees, sometimes
   permissively, on a limit whose stated purpose is blocking long adversarial
   input. The counter matches the configured backend: a deliberately pessimistic
   character heuristic by default, the local model's own tokenizer or the
   Anthropic API when `NBA_TOKEN_COUNTER` asks for exactness. See DECISIONS.md D7.
2. **Dynamic Route Classifier**:
   * **Explicit Year**: Queries containing 4-digit years (e.g., "1972") filter document candidates where `start_season <= 1972 AND end_season >= 1972`.
   * **Transitional Year Boundary**: an ambiguous four-digit year returns
     **HTTP 409** with both season options. Not HTTP 300: `300 Multiple Choices`
     is a redirect status that clients, proxies and browsers act on as one, and
     User Story 1 describes a UI prompt, not a redirect.
     **2023 is not the only such year.** Every document-window boundary is
     ambiguous, 14 of them in the shipped corpus, including 2011, where
     2010-11 is governed by CBA 2005 and 2011-12 by CBA 2011. The set is derived
     from the index by `db.schema.ambiguous_seasons()` rather than hardcoded, so
     re-scoping a document cannot leave a boundary silently unguarded.
     See DECISIONS.md D10.
   * **Contextual Proximity Triggers**: Keywords ("coin flip", "aba", "reserve clause", "territorial") ONLY override routing if found within a 6-word proximity window of historical context terms (e.g., "draft", "merger", "contract"). Otherwise, default to current 2023 CBA.
3. **Pre-Filtered Vector Search**: KNN MUST be constrained on the `doc_id`
   **metadata column**, never on the primary key. Resolve the era to document ids
   relationally first, then:
   ```sql
   SELECT chunk_id, distance
   FROM vec_chunks
   WHERE embedding MATCH :embedding AND k = :k
     AND doc_id IN (:d1, :d2, ...)     -- true pre-filter
   ORDER BY distance ASC LIMIT :k      -- REQUIRED, see below
   ```
   The outer `ORDER BY ... LIMIT` is load-bearing: with an IN-list of N documents
   sqlite-vec returns `k` rows **per document**, grouped by document and not
   globally sorted. Without it the caller silently gets the wrong top-k.

---

## 6. Prompt Personas & Output Formatting

Every prompt must be wrapped in isolated Llama-3 Instruct message tags (`<|im_start|>` and `<|im_end|>`) with XML context blocks (`<context>`):
* **Legal Scholar Mode**: Formal tone, strict adherence to retrieved text, mandatory bracketed footnotes (`[Document, Page X]`), and explicit refusal if text is missing.
* **Casual Fan Mode**: Podcaster/sportswriter tone, injects dynamic analogies from `historical_concept_mapper` (e.g., "Reserve Clause" -> "Permanent Franchise Tag"), footnotes relegated to final line.

---

## 7. Security, Compliance, & Distribution Directives

1. **Fetch-and-Build Distribution** *(replaces the IPFS/BitTorrent plan)*:
   * No copyrighted PDFs, compiled databases, or torrent descriptors in the repo.
   * The project distributes **instructions and SHA-256 checksums, not content**.
     `scripts/fetch_corpus.py` reports which documents are missing and where to
     obtain each from official or public-record sources; `scripts/build_index.py`
     compiles the index locally.
   * The former plan shipped a pre-compiled `nba_legal.db` over IPFS with a
     magnet-link fallback. That database contains the full text of copyrighted
     documents, so distributing it is the same act as distributing the PDFs, the
     "no PDFs in the repo" rule relocates the problem rather than curing it. It
     also hardcoded the SHA-256 of a file no step in the plan ever built.
   * See `DATA_SOURCES.md`.
2. **GDPR Technical Policy**:
   * `BACKEND_MODE=local`: 100% offline, zero network egress, zero query logging. User acts as both Data Controller and Processor.
   * `BACKEND_MODE=cloud`: User prompts are ephemeral in-memory only; require explicit UI consent and Zero-Data-Retention (ZDR) third-party API configurations.
3. **Indirect Prompt Injection Defense**:
   * **No OCR stage exists**, so there is no bounding-box confidence to filter on.
     All 25 manifest sources carry usable text: 18 PDFs with real text layers
     and 7 plain-text court opinions. `scripts/audit_corpus.py` re-checks both
     kinds and fails loudly if that stops being true.
     The residual defence is that `vec_chunks` receives only chunks marked
     `is_verified = 1`, so it *is* the active index: withhold-until-approved
     holds by construction rather than by a filter a caller can forget. There is
     no Streamlit admin panel; with no OCR it would guard an empty queue.
     The injection risk is also lower than for court-scraped scans, since the
     corpus comes from official NBPA/NBA publications and public court records.
     See sec. 3, sec. 8, and DECISIONS.md D3.
4. **SQL Parameterization**: All database queries must run parameterized bindings. F-strings in SQL execution are strictly banned.

---

## 8. Build Sequence & Verification Status

The original 9-step sequence was reordered. As written it had no ingestion step,
nothing chunked documents, generated embeddings, populated the tables, or
assembled a FastAPI app, so completing all nine steps produced a system that
could not answer a question. The build is now retrieval-first and eval-driven:
the central claim (chronological neutrality) is testable without an LLM, which
keeps the CUDA toolchain and the OCR pipeline off the critical path.

```
[x] Phase 0: .gitignore before git init (corpus excluded; verified)
[x] Phase 1: Direct text extraction, 18 PDFs / 3,385 pages   -> src/parser/
[x] Phase 2: Chunking + embeddings + index population        -> src/ingest/
[x] Phase 3: Labelled eval set (43 questions) + runner       -> tests/eval/
[x] Phase 4: FastAPI assembly, token gate, temporal router   -> src/api/
[x] Phase 5: Prompt templates + generation via Ollama        -> src/model/
[x] Phase 6: Fetch-and-build distribution + checksums        -> scripts/
[x] Phase 7: Pre-1995 coverage, opinions + curated timeline  -> D10-D13
```

Superseded from the original sequence:
* **Step 3 (PaddleOCR, size L)**, cut. All 18 documents are single-column with
  usable text layers; `scripts/audit_corpus.py` re-checks and fails if that changes.
* **Step 8 (IPFS/BitTorrent)**, replaced by fetch-and-build (sec. 7.1).
* **Step 9 (Streamlit OCR UI)**, cut; with no OCR it guards an empty queue.

Measured status: 43/43 on the evaluation with temporal isolation at 100%, the
gate; 318 unit tests green; index 46 documents (18 PDFs, 7 opinions, 21 timeline
entries) / 5,725 chunks / 0 orphaned vectors. The 43/43 is measured against
recall terms tightened in D18: four checks had been passing on terms appearing in
49-95% of the expected document and could not fail.

Generation is measured separately and is **not reproducible even at temperature
0** (llama.cpp's GPU forward pass is not bitwise stable), so it is reported as a
range: three full runs of mistral:7b scored 17, 19 and 18 of 26. Classifying
every fabricated citation against the exact context supplied gives **one
genuinely invented citation per 26 questions**; the rest are a supplied citation
narrowed to a subsection. The retriever is clean and the writer is over-precise.
Run `python tests/eval/run_eval.py [--with-generation]` for current numbers, read
DECISIONS.md before trusting any of them, and
docs/evaluation/GENERATION_MEASUREMENT.md for what the generation figures mean.