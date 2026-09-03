# GDPR Technical Compliance Specification
## Project: Courtroom-to-Court (V1.0)

This document specifies the technical architecture and data processing boundaries required to conform with the General Data Protection Regulation (GDPR) (EU 2016/679) for both Local (offline) and Cloud (API-backed) execution profiles. [Certain]

---

## 1. Data Classification Map

The Courtroom-to-Court RAG architecture processes three distinct categories of data:

| Data Category | Description | Data Type | Storage Location | GDPR Status |
| :--- | :--- | :--- | :--- | :--- |
| **Ingested Corpus** | NBA CBA, Constitution, Rulebooks, and draft tables. | Public Legal Text | `nba_legal.db` (Local SQLite) | Out of Scope (Contains zero PII/personal data). [Certain] |
| **User Queries** | Plain-text inputs submitted by users for rule analysis. | Potential PII | Ephemeral (In-memory) | In Scope (Article 4(1)). [Certain] |
| **System Embeddings** | 768-dimensional float arrays representing vector states. | Pseudonymized Data | `vec_chunks` (SQLite Virtual Table) | In Scope (Recital 26) if derived from user-submitted PII. [Likely] |

---

## 2. Privacy-by-Design Architecture (Article 25)

The application enforces strict data isolation based on the running profile configured in `init.sh` via the `BACKEND_MODE` variable. [Certain]

```
                       ┌───────────────────────────────┐
                       │       User Input Prompt       │
                       └───────────────┬───────────────┘
                                       │
                      Is "BACKEND_MODE=local" or "cloud"?
                                      / \
                                     /   \
                                LOCAL     CLOUD
                                 /         \
                                ▼           ▼
           ┌────────────────────────┐   ┌────────────────────────┐
           │      Local Loopback    │   │  FastAPI Router Gate   │
           │  - Processing: GPU/CPU │   │  - Zero logs stored    │
           │  - SQLite: Local memory│   │  - Scrub PII (Future)  │
           │  - 0% Network Outbound │   │  - Stream to Sub-Proc  │
           └────────────────────────┘   └───────────┬────────────┘
                                                    │
                                                    ▼ (Requires DPA / ZDR)
                                        ┌────────────────────────┐
                                        │  Third-Party Cloud API │
                                        │   (Anthropic/OpenAI)   │
                                        └────────────────────────┘
```

### 2.1 Local Execution Mode (Default)
`[Certain]` When `BACKEND_MODE=local` is active:
* **Zero Data Transmission**: No user queries, embeddings, or intermediate results are transmitted over the network. All computation occurs locally in VRAM/System RAM on your RTX 4060 laptop.
* **No Server Logging**: No central diagnostic logs are collected. The user acts as both the **Data Controller** and **Data Processor**, achieving total compliance by default.

### 2.2 Cloud Execution Mode
`[Certain]` When `BACKEND_MODE=cloud` is active:
* **Sub-Processor Boundary**: The application acts as an ephemeral pipeline passing prompts to Third-Party APIs (Anthropic/OpenAI).
* **Zero-Retention Enforcement**: API configurations must enforce Zero Data Retention (ZDR) options to block providers from utilizing user prompt inputs for model training or permanent caching.
* **Consent Gating**: If the system starts up in Cloud Mode, the UI must display a clear, interactive warning requiring affirmative consent (Article 6(1)(a)) before any payload is sent.

---

## 3. Data Subject Rights Implementation

### 3.1 Right to Erasure / "Right to Be Forgotten" (Article 17)
`[Certain]` If a user requests the deletion of their personal data or search inputs:
* **Local Mode**: The user simply purges the local database files or deletes the application folder. No remnants remain on any remote host.
* **Cloud Mode (FastAPI)**: The application does not maintain a database log of historical user queries in V1.0. All transactions are ephemeral and held in-memory only during the lifespan of the HTTP request. Once the response is sent, the query is purged from application RAM.

### 3.2 Data Portability (Article 20)
`[Certain]` Since the local application does not store user account profiles or persistent query logs, there is no structured data repository to export. If a user wishes to export the legal corpus, they can copy the SQLite `nba_legal.db` file directly.

---

## 4. Technical and Organizational Security Measures (Article 32)

To prevent unauthorized access, alteration, or leakage of user query inputs, the system enforces the following security boundaries:

1. **Parameterization**: Prevent SQL injection attacks (which could leak database structures) by strictly enforcing parameterized bindings on all SQLite searches (enforced in Step 6). [Certain]
2. **Token Enforcer Gating**: Enforce the 1,000-token payload limit (enforced in Step 5) to block resource-exhaustion attacks that could trigger diagnostic dumps containing active system memory states. [Certain]
3. **No-Log Middleware**: The FastAPI router must disable any database logging or disk logging of incoming query strings.

---

## 5. GDPR Compliance Verification checklist for Deployment

```
[ ] Set "BACKEND_MODE=local" as the default startup configuration in init.sh.
[ ] Verify that the FastAPI endpoints do not write incoming request payloads to disk or stderr logs.
[ ] Ensure all third-party API clients (Anthropic/OpenAI) are instantiated with API keys bound to business accounts that explicitly opt out of model-training data usage.
[ ] Implement the terminal-level consent prompt when falling back to Cloud Mode (Step 2/Step 9).
```