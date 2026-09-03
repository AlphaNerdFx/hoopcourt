# Implementation Plan: 
## Step 1: Vector Engine Verification

### 1. File Status Directory (Today)
* **`requirements.txt`**: `[DoesNotExist]` (Target: Holds core project dependencies).
* **`src/db/__init__.py`**: `[DoesNotExist]` (Target: Registers the database module).
* **`src/db/connection.py`**: `[DoesNotExist]` (Target: Provides the SQLite connection factory with `sqlite-vec` compiled binary loading).
* **`tests/test_vector_engine.py`**: `[DoesNotExist]` (Target: Verification suite asserting that vector cosine-distance matches execute).

---

### 2. Behavior Mapping

* **Current Behavior**: No codebase structure exists. Python cannot execute native high-performance vector searches because the standard library `sqlite3` does not support vector virtual tables natively.
* **Target Behavior**: A clean, reproducible Python environment that initializes a connection, loads the compiled `sqlite-vec` binary natively, inserts mock high-dimension float vectors, and queries using cosine distance with zero external database dependencies.

---

### 3. Alternative Approaches

#### Approach A: System-level Compilation from Source
* **Details**: Clone `sqlite-vec`'s raw C repository, compile it to a shared library (`.so`, `.dylib`, or `.dll`) using the host's native C compiler (gcc/clang/msvc), and load the path manually in Python.
* **Pros**: Absolute control over compilation flags and native optimization.
* **Cons**: Extreme complexity. Requires host compilation tools. High chance of failing on Windows setups without MSVC.
* **Risk / Blast Radius**: High. Destroys portability.

#### Approach B: Standard Python Package Wrapper (Recommended)
* **Details**: Install the official pre-compiled python package wrapper (`sqlite-vec`), which bundles the platform-specific pre-compiled C binaries and exposes a safe loader (`sqlite_vec.load(conn)`).
* **Pros**: Low complexity. Zero compilation dependencies on your laptop. Fully portable across Windows, Mac, and Linux.
* **Cons**: Dependent on upstream packaging releases.
* **Risk / Blast Radius**: Low. Completely isolated to the `src/db` library space.

---

### 4. Approach Selection & Justification
I select **Approach B**. 
Using the pre-compiled `sqlite-vec` python wrapper eliminates host compilation requirements, guarantees multi-platform support (Mac, Linux, Windows) out of the box, and wraps extension loading inside a single portable line of Python code.

---

### 5. Micro-Build & Verification Steps

#### Sub-step 1.1: Project & Environment Initialization
* **Actions**: Create root folder `courtroom_rag`, initialize git, and set up a Python virtual environment.
* **Verification Check**: Run `python --version` (ensuring 3.10+) and check that `(venv)` is active in your terminal prompt.

#### Sub-step 1.2: Dependencies Setup
* **Actions**: Create `requirements.txt` containing `sqlite-vec` and `pytest`, then run `pip install -r requirements.txt`.
* **Verification Check**: Run `pip show sqlite-vec` and verify it reports a valid installation path and version ($\ge 0.1.6$).

#### Sub-step 1.3: Connection Factory Setup
* **Actions**: Create `src/db/__init__.py` and `src/db/connection.py` containing the `sqlite_vec` loader logic.
* **Verification Check**: Execute:
  ```bash
  python -c "import sys; sys.path.append('src'); from db.connection import get_vector_db_connection; get_vector_db_connection()"
  ```
  Ensure it exits with code 0 (no load-extension errors or missing package exceptions).

#### Sub-step 1.4: Query Validation Test Run
* **Actions**: Create `tests/test_vector_engine.py` and execute the 3-dimensional vector float32 cosine search test.
* **Verification Check**: Run `pytest -v tests/test_vector_engine.py` and verify all tests return `PASSED`.

---

### 6. Risks & Rollbacks

* **Risk 1: Dynamic loading is blocked by system-level SQLite library constraints (common on macOS).**
  * *Exact Rollback*: Re-route the connection logic to enforce `pysqlite3` injection or wipe the current venv (`rm -rf venv`) and recompile Python using `pyenv` with shared libraries enabled.
* **Risk 2: Architecture incompatibility (e.g. older CPU lacking vectorized instruction sets like AVX).**
  * *Exact Rollback*: Uninstall the pre-compiled package (`pip uninstall -y sqlite-vec`) and switch to Approach A (native C compilation with safe fallback instruction flags).

---

### 7. Security & Isolation Check [AUTH / PAYMENTS / PROD DATA]
This step is completely isolated to a local, offline environment. No external databases, production hosting environments, user accounts, or payment processors are touched. Zero security risk.

---

## Step 2: Local Model Execution Spike & CUDA Verification [Size: L]

### 1. File Status Directory (Post-Step 1)
* **`requirements.txt`**: `[Exists]` (Target: Append `huggingface_hub` to download GGUF).
* **`src/model/__init__.py`**: `[DoesNotExist]` (Target: Registers model package namespace).
* **`src/model/inference.py`**: `[DoesNotExist]` (Target: Houses model downloader and strict VRAM-limiting loader).
* **`tests/test_local_model.py`**: `[DoesNotExist]` (Target: Test asserting that model loads on CUDA and runs text generation).

### 2. Behavior Mapping
* **Current Behavior**: Local environment can perform vector math in SQLite, but has no LLM capability.
* **Target Behavior**: Python environment compiles `llama-cpp-python` with CUDA flags, programmatically downloads `Llama-3.1-8B-Q4_K_M`, loads it with context bound strictly to 2048, and runs text completion offloaded entirely to the GPU at $\ge 20$ tokens/second. [Likely]

### 3. Alternative Approaches
* **Approach A: GGUF via `llama-cpp-python` (Recommended)**: Runs model quantized in 4-bit, allocating ~4.8GB VRAM, allowing the model and cache to fit comfortably on an 8GB RTX 4060. [Certain]
* **Approach B: AutoModel via `transformers` / PyTorch**: Demands standard HF pipelines, leading to immediate out-of-memory (OOM) errors on 8GB VRAM when running 16-bit or 8-bit weights. [Certain]

### 4. Approach Selection & Justification
I select **Approach A**. It utilizes highly optimized GGUF format weights, enables strict VRAM context allocation limits, and avoids external CUDA wrapping overhead to prevent OOM errors on consumer-grade laptop GPUs. [Certain]

### 5. Micro-Build & Verification Steps
* **Sub-step 2.1**: Force-compile `llama-cpp-python` using local CUDA tools (`CMAKE_ARGS="-GGML_CUDA=on"`).
  * *Check*: Execute `python -c "import llama_cpp"` (Must load with no DLL search errors).
* **Sub-step 2.2**: Implement `src/model/inference.py` to programmatically download the model from Hugging Face.
  * *Check*: Verify model cache folder contains `Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf` (~4.8GB). [Certain]
* **Sub-step 2.3**: Implement the CUDA validation test `tests/test_local_model.py`.
  * *Check*: Run `pytest -s tests/test_local_model.py` and inspect logging to confirm `n_gpu_layers > 0` and generation speed is fast.

### 6. Risks & Rollbacks
* **Risk**: Local CUDA compilation fails due to mismatched or missing CUDA Toolkit dependencies on host OS. [Certain]
* **Rollback**: Force-uninstall and compile standard CPU-only fallback: `CMAKE_ARGS="" pip install llama-cpp-python --no-cache-dir`.

### 7. Security & Isolation Check [AUTH / PAYMENTS / PROD DATA]
This step is 100% local and offline. No credentials, hosting, or client-sensitive data are touched. No sign-off required.

---

## Step 3: PaddleOCR Multi-column PDF Table Parser [Size: L]

### 1. File Status Directory
* **`requirements.txt`**: `[Exists]` (Target: Append `paddleocr`, `paddlepaddle`, `pdf2image`, `pillow`).
* **`src/parser/__init__.py`**: `[DoesNotExist]` (Target: Registers the parser package).
* **`src/parser/pdf_ocr.py`**: `[DoesNotExist]` (Target: Converts PDF pages to images and parses them column-by-column).
* **`tests/test_pdf_ocr.py`**: `[DoesNotExist]` (Target: Test verifying that left-column is parsed before right-column).

### 2. Behavior Mapping
* **Current Behavior**: System has no ingestion pipeline; historical legal documents are unreadable.
* **Target Behavior**: PDF files are programmatically split, analyzed, OCR-scanned, and reassembled using coordinate sorting to preserve strict columnar reading order (Left Column, then Right Column). [Certain]

### 3. Alternative Approaches
* **Approach A: Flat OCR Engine (PyPDF / Tesseract)**: Reads left-to-right blindly, weaving two distinct legal columns into mixed sentences. [Certain]
* **Approach B: Coordinate-Sorted OCR (Recommended)**: Utilizes `pdf2image` to convert pages to images, runs `PaddleOCR`, detects page midpoint, and sorts boxes vertically in separate left/right columns. [Certain]

### 4. Approach Selection & Justification
I select **Approach B**. Standard OCR engines completely mangle parallel table text and column structures. Rebuilding reading order based on bounding box coordinates is the only way to generate clean context chunks for the RAG index. [Certain]

### 5. Micro-Build & Verification Steps
* **Sub-step 3.1**: Install system poppler utilities and pip packages (`paddleocr`, `pdf2image`).
  * *Check*: Run `python -c "import paddleocr"` with no dynamic library linking errors.
* **Sub-step 3.2**: Implement `src/parser/pdf_ocr.py` layout parser.
  * *Check*: Validate that midpoint coordinate math successfully divides bounding boxes.
* **Sub-step 3.3**: Write and execute `tests/test_pdf_ocr.py` with mock 2-column inputs.
  * *Check*: Assert that left-column text strings are indexed before right-column strings.

### 6. Risks & Rollbacks
* **Risk**: System fails to locate `poppler` binaries on Windows, throwing `pdf2image` initialization errors. [Certain]
* **Rollback**: Uninstall packages (`pip uninstall -y paddleocr pdf2image`) and switch to a static image-based parser pipeline or manually configure PATH environment variables.

### 7. Security & Isolation Check [AUTH / PAYMENTS / PROD DATA]
Completely local. Offline data ingestion. No sign-off required.

---

## Step 4: Database Schemas & Concept Mapper Migration [Size: M]

### 1. File Status Directory
* **`src/db/connection.py`**: `[Exists]` (Target: Read-only, provides the load-extension connection).
* **`src/db/schema.py`**: `[DoesNotExist]` (Target: Setup relational schema and `sqlite-vec` virtual index).
* **`tests/test_database_schema.py`**: `[DoesNotExist]` (Target: Verifies trigger execution and relational cascades).

### 2. Behavior Mapping
* **Current Behavior**: No relational tables or index-synchronization boundaries are established in SQLite.
* **Target Behavior**: Table schemas (`documents`, `document_chunks`, `historical_concept_mapper`, `vec_chunks`) compile cleanly, with automatic `AFTER DELETE` triggers that instantly delete vector embeddings when text chunks are deleted. [Certain]

### 3. Alternative Approaches
* **Approach A: Manual Decoupled Vector Deletion**: Rely on application logic in FastAPI to delete vectors from `vec_chunks` when chunks are deleted.
  * *Cons*: Highly vulnerable to desynchronization if a network/DB connection drops mid-operation. [Likely]
* **Approach B: SQLite Trigger Deletion (Recommended)**: Write a native database trigger inside SQLite (`sync_vec_index_on_chunk_deletion`) to execute automatic cascades. [Certain]

### 4. Approach Selection & Justification
I select **Approach B**. Relying on application code to keep relational data and vector indices synchronized is a major risk. Native database triggers enforce transactional synchronization at the SQLite kernel level, preventing dead references. [Certain]

### 5. Micro-Build & Verification Steps
* **Sub-step 4.1**: Implement `src/db/schema.py` database initialize script.
  * *Check*: Run initialization on local SQLite and inspect tables using `.tables` to verify all schemas compiled.
* **Sub-step 4.2**: Implement the triggers and performance indices.
  * *Check*: Verify trigger exists using `PRAGMA index_list`.
* **Sub-step 4.3**: Write and run Cascade Integration Test (`tests/test_database_schema.py`).
  * *Check*: Verify that deleting a row in `documents` triggers automatic empty cascades in `document_chunks` and `vec_chunks`.

### 6. Risks & Rollbacks
* **Risk**: SQLite version installed on host machine is older than 3.38, which blocks virtual table trigger interactions. [Likely]
* **Rollback**: Drop all tables using `DROP TABLE IF EXISTS` commands, update the python package `pysqlite3-binary` to force-override the local system's outdated SQLite libraries.

### 7. Security & Isolation Check [AUTH / PAYMENTS / PROD DATA]
No external cloud database tables, user access controls, or financial databases are touched. Completely offline. No sign-off required.

---

## Step 5: Token Limit Middleware & Contextual Routing Engine [Size: M]

### 1. File Status Directory
* **`requirements.txt`**: `[Exists]` (Target: Append `fastapi`, `tiktoken`).
* **`src/api/__init__.py`**: `[DoesNotExist]` (Target: Registers API namespace).
* **`src/api/router.py`**: `[DoesNotExist]` (Target: Unified validation schemas, tiktoken enforcer, and proximity parser).
* **`tests/test_routing_middleware.py`**: `[DoesNotExist]` (Target: Test suite asserting token limits and contextual negations).

### 2. Behavior Mapping
* **Current Behavior**: Queries are unfiltered, allowing massive input payloads and matching dates blindly via standard regex.
* **Target Behavior**: FastAPI middleware blocks payloads $> 1000$ tokens, and the routing logic uses token-proximity mapping to ensure historical overrides (like "coin flip" or "aba") only trigger if they are used near valid historical keywords. [Certain]

### 3. Alternative Approaches
* **Approach A: Static Keyword String Matching**: Standard regex checks for trigger terms anywhere in the string.
  * *Cons*: Extreme rate of false positives (e.g. routing modern playoff seeding coin flips to 1985 draft rules). [Certain]
* **Approach B: Contextual Proximity Matching (Recommended)**: Utilizes a proximity function that checks if the trigger keyword resides within a 6-word window of historical terms (e.g., "draft", "merger"). [Certain]

### 4. Approach Selection & Justification
I select **Approach B**. It enforces security boundaries via `tiktoken` while preventing broken routing paths on normal conversational language, ensuring the system remains chronological neutral under complex query variations. [Certain]

### 5. Micro-Build & Verification Steps
* **Sub-step 5.1**: Install pip packages (`fastapi`, `tiktoken`).
  * *Check*: Import tiktoken and verify encoder can parse a mock string.
* **Sub-step 5.2**: Implement unified payload validation schemas and enforcers in `src/api/router.py`.
  * *Check*: Verify token counter successfully rejects strings longer than limit bounds.
* **Sub-step 5.3**: Build and run test suite (`tests/test_routing_middleware.py`).
  * *Check*: Confirm that modern coin-flip queries resolve to the default modern 2023 CBA path while historical queries trigger correct overrides.

### 6. Risks & Rollbacks
* **Risk**: Tokenizer load latency slows down incoming API calls on low-resource machines. [Likely]
* **Rollback**: Disable `tiktoken` execution on the fly and fallback to raw character-limit checks (`len(query) > 4000`) by commenting out the dependency module.

### 7. Security & Isolation Check [AUTH / PAYMENTS / PROD DATA]
No external network calls, payments, or cloud data. Completely local. No sign-off required.

---

## Step 6: Dynamic SQL Query Builder & Segmented Retrieval [Size: S]

### 1. File Status Directory
* **`src/db/search.py`**: `[DoesNotExist]` (Target: Compiles dynamic pre-filtered SQL vector queries).
* **`tests/test_vector_retrieval.py`**: `[DoesNotExist]` (Target: Validates metadata-isolated query execution).

### 2. Behavior Mapping
* **Current Behavior**: Relational tables exist, but no pipeline exists to retrieve relevant contexts.
* **Target Behavior**: The retriever generates custom SQLite pre-filtered vector queries, constraining `vec_chunks` search space to the document IDs of the target year *prior* to executing similarity math. [Certain]

### 3. Alternative Approaches
* **Approach A: Semantic Post-Filtering**: Run a global KNN search of size 10, then filter out chunks that don't match the year target.
  * *Cons*: If modern chunks dominate similarity scores, the filtered results will be empty, failing to return historical documents. [Certain]
* **Approach B: Semantic Pre-Filtering (Recommended)**: Embed a relational subquery inside the `sqlite-vec` MATCH parameters, filtering document IDs first. [Certain]

### 4. Approach Selection & Justification
I select **Approach B**. It is mathematically impossible for modern document contexts to bleed into historical searches when pre-filtering is strictly locked to specific years or document IDs at the database driver level. [Certain]

### 5. Micro-Build & Verification Steps
* **Sub-step 6.1**: Implement vector search builder inside `src/db/search.py`.
  * *Check*: Verify SQL statements compile with no syntax errors.
* **Sub-step 6.2**: Seed conflicting database entries (e.g. CBA 1970 vs CBA 2023) with identical vector values but different era-text.
  * *Check*: Assert that searching 1972 returns only CBA 1970 context, and 2024 returns only CBA 2023. [Certain]
* **Sub-step 6.3**: Run `pytest -v tests/test_vector_retrieval.py`.
  * *Check*: Verify all assertions pass with `PASSED` status.

### 6. Risks & Rollbacks
* **Risk**: SQL subquery syntax is rejected if nested inside virtual table operators on old `sqlite-vec` builds. [Likely]
* **Rollback**: Convert to a two-step query: (1) Fetch valid document IDs, (2) Pass IDs as an array of constants directly into the MATCH `WHERE` clause.

### 7. Security & Isolation Check [AUTH / PAYMENTS / PROD DATA]
No payments, user credentials, or remote cloud DBs are touched. Completely offline. No sign-off required.

---

## Step 7: Dual Prompt Templates & Generation Engine [Size: S]

### 1. File Status Directory
* **`src/model/prompt_templates.py`**: `[DoesNotExist]` (Target: System prompts and message packing configurations).
* **`src/model/generation.py`**: `[DoesNotExist]` (Target: Ingestion orchestrator executing local GGUF completions).
* **`tests/test_prompt_generation.py`**: `[DoesNotExist]` (Target: Test asserting prompt compilation accuracy).

### 2. Behavior Mapping
* **Current Behavior**: RAG context is retrieved but cannot be combined with prompt templates or executed.
* **Target Behavior**: Prompt compiler formats retrieved chunks using structured tags, queries historical concept mapper tables for casual-mode, compiles the final Instruct envelope, and runs inference. [Certain]

### 3. Alternative Approaches
* **Approach A: Single Dynamic System Prompt**: Let the model decide the tone and formatting inside a single broad prompt.
  * *Cons*: Extremer rates of persona bleeding (legal citations bleeding into casual explanations on local 8B models). [Certain]
* **Approach B: Structurally Isolated Dual-Prompts (Recommended)**: Enforce distinct "Legal Scholar" (with forced XML citations) and "Casual Fan" templates. [Certain]

### 4. Approach Selection & Justification
I select **Approach B**. Quantized local models require strict constraint boundaries and clear system profiles to prevent formatting leakage and maintain stable reasoning formats. [Certain]

### 5. Micro-Build & Verification Steps
* **Sub-step 7.1**: Implement `src/model/prompt_templates.py` with custom XML tag structures.
  * *Check*: Verify that user inputs and retrieved records compile with no format breaking.
* **Sub-step 7.2**: Implement `src/model/generation.py` to handle database lookups and model execution.
  * *Check*: Run generator using mock LLM interfaces to verify parameter passing.
* **Sub-step 7.3**: Write and run mock inference validation tests (`tests/test_prompt_generation.py`).
  * *Check*: Confirm that casual setting pulls DB analogies and packs prompts correctly.

### 6. Risks & Rollbacks
* **Risk**: Local 8B GGUF struggles to output consistent citations or respect negative constraints. [Likely]
* **Rollback**: Introduce strict, one-shot formatting examples into the System Prompts to force the desired output structure.

### 7. Security & Isolation Check [AUTH / PAYMENTS / PROD DATA]
Offline and local. No sign-off required.

---

## Step 8: Decoupled BitTorrent / Hydration Client [Size: M]

### 1. File Status Directory
* **`requirements.txt`**: `[Exists]` (Target: Append `requests`).
* **`src/db/db_hydrate.py`**: `[DoesNotExist]` (Target: Manages decentralized streaming and SHA-256 validation).
* **`tests/test_hydration.py`**: `[DoesNotExist]` (Target: Test asserting integrity validation and cleanup).

### 2. Behavior Mapping
* **Current Behavior**: No dataset distribution mechanics exist; developer must build index manually.
* **Target Behavior**: Script checks local DB hash, downloads missing database from decentralized IPFS gateways, performs cryptographic validation, and prints fallback magnet instructions if gateways fail. [Certain]

### 3. Alternative Approaches
* **Approach A: Native Python BitTorrent Client**: Install `libtorrent` wrapper to download files directly.
  * *Cons*: Requires compiling binary wheels on target host OS, creating heavy installation friction. [Certain]
* **Approach B: Decoupled IPFS Gateway Bootstrap (Recommended)**: Stream database from public IPFS P2P gateways via standard HTTPS, with a clear fallback printing a raw Magnet Link if the gateway pool fails. [Certain]

### 4. Approach Selection & Justification
I select **Approach B**. It achieves your decentralized distribution goal while bypassing platform compilation issues, ensuring that the script executes natively on any machine running a standard Python installer. [Certain]

### 5. Micro-Build & Verification Steps
* **Sub-step 8.1**: Install requests and update `requirements.txt`.
  * *Check*: Verify requests imports successfully in virtual environment.
* **Sub-step 8.2**: Implement `src/db/db_hydrate.py` streaming client.
  * *Check*: Run download with dummy payload to confirm chunk-saving and temp-cleanup logic works.
* **Sub-step 8.3**: Write and run mock verification tests (`tests/test_hydration.py`).
  * *Check*: Assert that checksum validation triggers correct rollbacks and displays the backup Magnet Link on failure.

### 6. Risks & Rollbacks
* **Risk**: Host machine runs out of disk space or local network blocks IPFS gateway IPs. [Likely]
* **Rollback**: Clean up temp download files immediately and print the raw magnet link in the console so users can download it manually.

### 7. Security & Isolation Check [AUTH / PAYMENTS / PROD DATA]
No payment gateways or user account databases. Download targets a static, public legal index file. Safe for distribution.

---

## Step 9: Streamlit Admin OCR Correction UI [Size: S]

### 1. File Status Directory
* **`requirements.txt`**: `[Exists]` (Target: Append `streamlit`).
* **`src/admin/__init__.py`**: `[DoesNotExist]` (Target: Registers admin namespace).
* **`src/admin/app.py`**: `[DoesNotExist]` (Target: Streamlit web dashboard for editing unverified chunks).
* **`tests/test_admin_ui.py`**: `[DoesNotExist]` (Target: Test verifying database write transactions).

### 2. Behavior Mapping
* **Current Behavior**: Ingested scanned chunks must be verified manually via direct database operations.
* **Target Behavior**: A local dashboard displays unverified chunks (`is_verified = 0`), lets administrators edit text, and executes thread-safe SQLite transaction writes to sync text updates and vector embeddings. [Certain]

### 3. Alternative Approaches
* **Approach A: Complex React/Node Frontend**: Build a modern web application with a separate UI compilation tier.
  * *Cons*: Drastically increases project complexity and setup friction for local users. [Certain]
* **Approach B: Streamlit Python Dashboard (Recommended)**: Build a simple, thread-safe dashboard using pure Python. [Certain]

### 4. Approach Selection & Justification
I select **Approach B**. Using a Python-native interface avoids adding Javascript compilation layers, matches the FOSS design philosophy, and allows direct integration with local SQLite connection pools. [Certain]

### 5. Micro-Build & Verification Steps
* **Sub-step 9.1**: Install streamlit and update `requirements.txt`.
  * *Check*: Run `streamlit hello` to confirm local server starts up.
* **Sub-step 9.2**: Implement `src/admin/app.py` dashboard.
  * *Check*: Verify that connection pooled sessions are initiated safely.
* **Sub-step 9.3**: Write and execute transactional tests (`tests/test_admin_ui.py`).
  * *Check*: Confirm that database updates and vector-sync operations roll back completely if an error is encountered.

### 6. Risks & Rollbacks
* **Risk**: SQLite database locks occur if the user submits concurrent edits inside Streamlit's reactive thread pool. [Certain]
* **Rollback**: Force SQLite connection limits (`timeout=10` or single-writer transaction locks) and rollback state changes to maintain file consistency.

### 7. Security & Isolation Check [AUTH / PAYMENTS / PROD DATA]
Runs entirely offline on a local port (`8501`). No public authentication, payment setups, or cloud database tables are exposed. Completely safe.