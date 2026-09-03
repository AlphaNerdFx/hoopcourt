# Project PRD: Hoopcourt (V1.0)

## 1. Problem Statement & Success Metrics

### Problem Statement
Die-hard and casual NBA fans struggle to interpret the dense, highly technical legal text of the NBA Collective Bargaining Agreement (CBA), Constitution, and draft rules across different eras. Existing conversational AI tools lack the temporal awareness to restrict answers to the rules active at a specific historical moment, causing severe "rule bleeding" (e.g., applying 2023 CBA "Second Apron" rules to a 2011 trade query) and factual hallucinations.

### Success Metrics
* **Accuracy (Grounding)**: Zero hallucinations on trade exceptions, cap space mechanics, and draft rules across 95% of test scenarios.
* **Temporal Routing Accuracy**: 100% correct matching of queries to their respective historical rulesets.
* **Response Latency**: Under 2.5 seconds in Cloud Mode; under 4.0 seconds in Local Mode on supported hardware.

---

## 2. Scope & Data Sourcing Strategy

### Legally Compliant Sourcing (V1)
No raw PDFs or pre-compiled databases will be hosted or distributed in the public GitHub repository to avoid copyright infringement.

* **`DATA_SOURCES.md`**: The repository documentation will contain instructions pointing *only* to official, authorized public domains for download:
  1. NBPA Official Resources (Current CBAs).
  2. CourtListener/RECAP (For historical CBAs filed as public exhibits in antitrust lawsuits).
  3. Official Internet Archive entries (For pre-1980 NBA Guides).
* **Fetch-and-Build** *(replaces the hydration script)*: the repository ships
  `scripts/fetch_corpus.py` (reports what is missing and where to obtain it, and
  records/verifies SHA-256 checksums) and `scripts/build_index.py` (compiles the
  index locally). Nothing copyrighted is redistributed, not the PDFs and not the
  compiled database, which contains their full text and would carry the same
  exposure. See `DATA_SOURCES.md`.
* **Strict Warning**: Linking to unauthorized personal cloud storage drives (MEGA, Google Drive, Dropbox) is strictly forbidden in the documentation to prevent contributory copyright infringement claims.

### V1 Document Index Scope
* **Modern Era**: 2023 NBA CBA, 2024-25 CBA 101, Official 2025-26 Rulebook, 2025-26 NBA Officials Guide.
* **Historical Era (1940s-1990s)**: Historical draft probabilities, 1995/1999 CBAs, and historical rule changes (coin flips, territorial picks, option clauses).

### Post-V1 Ingestion & Update Pipeline
Implement an automated, CI/CD-driven **Vector-DB Update Pipeline** (not model re-training).
* The pipeline will compute automatic document hash checks on official NBA and NBPA press release feeds. If a new rule/amendment hash is detected, it runs the parsing and upsert pipeline to refresh the vector store.

---

## 3. Technology Stack & Deployment Profiles

* **Framework**: FastAPI. **No LlamaIndex**, the value here is custom temporal
  pre-filtering, which fights a framework's retriever abstractions rather than
  benefiting from them; direct `sqlite-vec` + `sentence-transformers` is ~200
  lines and fully debuggable.
* **Vector Database**: SQLite + **`sqlite-vec`** (not `sqlite-vss`), with `doc_id`
  as a vec0 metadata column, see CLAUDE.md sec. 4.
* **Embeddings**: `BAAI/bge-base-en-v1.5` (768-dim, MIT, local, free).
* **Local LLM**: `Qwen2.5-7B-Instruct` Q4_K_M GGUF via `llama-cpp-python`
  (Apache-2.0; CPU works without CUDA).
* **Cloud LLM** *(optional, bring-your-own-key, never required)*: `claude-opus-5`.
* **Text extraction**: `pdfplumber` (MIT). **No OCR**, measured unnecessary
  across all 18 documents; see `scripts/audit_corpus.py`.

---

## 4. Hardware Profiles & CPU Warning System

A standard laptop with an RTX 4060 (8GB VRAM) and 16GB of System RAM cannot run Llama-3.1-8B-Instruct at full 16-bit precision alongside an embedding model without triggering out-of-memory (OOM) errors. It requires strict quantization.

### Startup Profiling Logic (`init.sh`)
```bash
if detect_nvidia_gpu; then
    vram=$(get_vram_gb)
    if [ "$vram" -ge 8 ]; then
        echo "GPU Profile Active: Loading 4-bit quantized Llama-3.1-8B into VRAM..."
        load_local_gpu_pipeline
    else
        echo "Low VRAM detected ($vram GB). Fallback to Cloud Mode recommended."
        prompt_fallback_choice
    fi
else
    echo "WARNING: No NVIDIA GPU detected. Running on CPU will degrade generation speeds to <3 tokens/sec."
    read -p "Do you want to proceed with degraded CPU performance? (y/n) " choice
    if [ "$choice" = "y" ]; then
        load_cpu_only_pipeline
    else
        switch_to_cloud_config
    fi
fi
```

---

## 5. System Architecture & Routing Engine

The system uses a 1,000-token maximum limit on user prompts, strictly enforced at the backend middleware level.

### Dual-Path Routing Logic
* **Case A (No year mentioned, no historical trigger terms)**: Default to the **Current 2023 CBA**.
* **Case B (Explicit year mentioned, e.g., "1972")**: Search is strictly bound to documents where `start_season <= 1972` AND `end_season >= 1972`.
* **Case C (No year mentioned, but Historical Trigger detected)**: Trigger keywords automatically bypass the current CBA and route to the corresponding era:

| Trigger Term detected | Routed Era Target | Conceptual Analogy Map (For Casual Mode) |
| :--- | :--- | :--- |
| **"coin flip"** | Pre-1985 Lottery | Draft lottery was a literal coin toss between the worst teams. |
| **"territorial"** | Pre-1966 Draft | Allowed teams to bypass the draft to claim local college players. |
| **"reserve clause"** | Pre-1976 Free Agency | Teams legally owned players indefinitely with no free agency. |
| **"aba"** | 1976 Merger | The merger that absorbed 4 ABA teams into the NBA. |

---

## 6. OCR Quality Verification & Correction Pipeline

Because historical documents are prone to transcription errors, the administrative pipeline must support human-in-the-loop correction before database compilation.

### The UI Reference Correction Flow
1. **Source Mapping**: Every chunk generated via OCR is flagged with `is_verified = FALSE` and stores its bounding box coordinates alongside the source page image link.
2. **Interactive UI**: The admin interface displays the source PDF scan side-by-side with the generated markdown output.
3. **Manual Override**: The user reviews, edits the raw text, and saves. 
4. **Ingestion**: Saving updates the local database chunk to `is_verified = TRUE`, generating a new local chunk vector embedding. Only `is_verified = TRUE` chunks are compiled into the master release database.

---

## 7. Data Model Schema (Local SQLite Implementation)

### `documents` Table
```sql
CREATE TABLE documents (
    doc_id TEXT PRIMARY KEY,
    doc_name TEXT NOT NULL,
    category TEXT CHECK (category IN ('Historical', 'Current Operational', 'Current Governing')),
    start_season INTEGER NOT NULL,
    end_season INTEGER NOT NULL,
    source_url TEXT NOT NULL
);
```

### `document_chunks` Table
```sql
-- SUPERSEDED by CLAUDE.md sec. 4, which is authoritative. Two differences
-- matter: integer primary keys (vec0 rowids are integers), and the embedding
-- lives in a separate vec0 virtual table rather than an inline BLOB, because
-- only a vec0 metadata column gives a true pre-filter. article_num/section_num
-- from this schema were kept -- citations must resolve to a section.
CREATE TABLE document_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    chunk_hash TEXT UNIQUE NOT NULL,
    article_num TEXT,
    section_num TEXT,
    page_num INTEGER NOT NULL,
    is_verified INTEGER DEFAULT 0,
    text_content TEXT NOT NULL
);
```

### `historical_concept_mapper` Table
```sql
CREATE TABLE historical_concept_mapper (
    concept_id TEXT PRIMARY KEY,
    archaic_term TEXT UNIQUE NOT NULL,
    modern_analogy TEXT NOT NULL,
    simplified_explanation TEXT NOT NULL,
    valid_from_year INTEGER,
    valid_to_year INTEGER
);
```

---

## 8. User Stories & Acceptance Criteria

### User Story 1: Temporal Context Clarification
> **As an** avid fan,
> **I want to** search "What were the luxury tax penalties in 2023?",
> **So that** the system asks me to clarify whether I mean the 2022-23 season or the 2023-24 season before giving me an answer.

* **Acceptance Criteria**:
  * Parsing detecting year "2023" returns **HTTP 409** with both season options
    (not HTTP 300, a redirect status clients act on), triggering a clarifying UI prompt.
  * System holds vector search in suspense until the user selects the season window.
  * Selection of "2023-24" correctly applies the `2023 NBA CBA` metadata filter.

### User Story 2: CPU Fallback Confirmation
> **As a** developer with a non-GPU laptop,
> **I want to** start the self-hosted setup,
> **So that** I am warned about performance bottlenecks and given an option to input a cloud API key instead of crashing.

* **Acceptance Criteria**:
  * If `torch.cuda.is_available()` returns `False`, the boot process must pause.
  * System displays a terminal-based prompt warning of `<3 tokens/second` speeds on CPU.
  * Choosing "No" redirects the system config to load the OpenAI/Anthropic cloud module.

---

## 9. Edge Cases & Failure States

* **Prompt Overflow**: User inputs a massive 2k-token paste of player contract history.
  * *System Action*: Backend middleware rejects submission before processing, warning: *"Prompts are strictly capped at 1,000 tokens to ensure retrieval accuracy. Your input was [X] tokens."*
* **Low-Quality Scan (OCR Fail)**: A court-scraped PDF has heavy handwritten marks, causing PaddleOCR to spit out corrupted text.
  * *System Action*: Database marks page `ocr_confidence` as `< 70%` and routes the raw image to the manual correction queue. Chunk is excluded from search index until approved.
* **SQL Injection Attempt**: User submits: `"); DROP TABLE document_chunks;--`.
  * *System Action*: The query parser does not execute raw SQL queries constructed from user inputs. It uses parameterized SQLite bindings exclusively.