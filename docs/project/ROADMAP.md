# Roadmap and scope

The working checklist is [TODO.md](../../TODO.md). This file is the reasoning
behind it: what the project is for, where it stops, and why the sequence is what
it is.

---

## The MVP claim

**Hoopcourt v1.0 is an era-aware question answering system over NBA governing
documents, with verifiable citations, that a person can install and use.**

That is the entire claim. It is narrow on purpose. Without a boundary every good
idea looks equally urgent and nothing can ever be called finished.

Almost all of it exists. Retrieval scores 100% on every check, the evaluation is
43/43 with temporal isolation as a hard gate, generation runs on GPU through
Ollama, and citations are verified both in the evaluation and at runtime. What is
missing is a face and an honest number: a thin web UI, and a citation-validity
figure measured over all 43 questions rather than ten.

Everything else in this document happens after that ships.

---

## Three things worth arguing about before building them

### Running a service is a different legal act from shipping a tool

Every copyright decision this project has taken rests on one posture: the user
fetches documents themselves and builds their own index, so nothing copyrighted
is ever redistributed. That posture is why the IPFS distribution plan was killed
(D4), why the Uniform Player Contract was dropped rather than sourced from a
viewer page (D12, D13), and why `DATA_SOURCES.md` refuses personal mirrors.

A hosted service inverts it. You would hold the corpus, generate answers from it,
and serve those answers to the public at scale. That is distribution wearing
different clothes, and the fetch-and-build defence does not reach it.

This is the largest strategic risk in the roadmap. It is not an infrastructure
problem, and vLLM does not solve it. Treat it as a gate answered by someone
qualified before any public endpoint exists, not as a deployment detail.

### vLLM and llm-d are concurrency technologies

vLLM's advantage appears at roughly five or more simultaneous requests. Below
that it consumes more memory than Ollama and returns nothing for it. llm-d is a
CNCF Kubernetes project that disaggregates prefill and decode across
compute-optimised and memory-optimised *nodes*; on a single 8GB laptop GPU there
is nothing to disaggregate.

Both belong in the roadmap. Neither belongs in the MVP. Adopting them early buys
a Kubernetes dependency and an architecture with no load to justify it.

Ollama already runs the model entirely in VRAM through its own `cuda_v12`
runtime, so the current setup is not a compromise being tolerated. It is the
correct tool at this scale.

### Statistics are not a retrieval problem

"How many rebounds did Rodman average in 1996-97" is a query, not a passage.
Embedding numbers and hoping cosine distance finds the right row produces
confident wrong answers, which is the precise failure this project exists to
prevent.

Statistics need a table and generated SQL. They share the temporal router, since
a season still has to be resolved, but they do not share the retrieval path. Any
design that puts box scores in the vector index has made a category error.

---

## Phases

### A. Corpus expansion

Officiating material and league history reuse every existing mechanism: the
manifest, era windows, source tiers, the audit, the fetch-and-build posture. No
new architecture, which makes this the cheapest value in the roadmap.

One addition: narrative history is neither a governing document nor a curated
claim, so it earns a fourth tier (`historical_record`) rather than being crammed
into `timeline`.

### B. Statistics via SQL

`nba_api` is MIT-licensed, but the data behind stats.nba.com is not, and there is
no published bulk-data licence. An open client does not grant rights to the
upstream data. So statistics follow the same model as the documents: the user
fetches on their own machine, and the project redistributes nothing.

The response must say which engine answered. A number from a table and a
quotation from the CBA carry different kinds of authority, and the source tiers
already establish that pattern for documents.

### C. The fine-tune

Worth doing only if off-the-shelf models cannot close the citation gap. Only
`mistral:7b` has ever been measured, so that cheap experiment comes first.

If it is needed, the target is one measurable skill: citation discipline. Copy
the permitted citation verbatim, never invent a pinpoint, refuse when context is
thin. Success is defined by the existing evaluation, not by a loss curve.

**The training data boundary is the part that matters.** Weights memorise. A
model trained on the copyrighted corpus and published on Hugging Face
redistributes derived copyrighted text, which is the same act D4 rejected for the
compiled index. Training data is therefore limited to the seven public-domain
court opinions, the project's own timeline entries, and synthetic pairs derived
from those. No CBA text.

Ship the adapter only if it beats base plus prompt on the same 43 questions. If
it loses, publish the negative result.

### D. Service

| Stage | Serving | Trigger |
| --- | --- | --- |
| now | Ollama | one user, already GPU-resident |
| small | vLLM, single GPU | sustained concurrency, roughly 5+ |
| large | llm-d on Kubernetes | multiple GPUs or nodes |

Gated on the legal question above, not on readiness of the infrastructure.

### E. Contracts and cap, blocked

The mechanics already work from the indexed CBA: exceptions, aprons, cap holds,
and how they interact. What is missing is current per-team numbers, and the
sources that maintain them are commercial products whose data `DATA_SOURCES.md`
rules out taking.

Blocked pending a licensable feed. Do not scrape. If the feature is redefined as
"explain the mechanism", it already ships today.

---

## What would change this plan

* A public pre-1995 CBA surfacing would reduce the judicial and timeline tiers
  from necessity to supplement.
* An official or licensable statistics feed would move Phase B from
  fetch-and-build to something distributable.
* A qualified legal opinion permitting hosted serving would unblock Phase D
  early; one forbidding it would remove the service goal entirely and make the
  self-hosted tool the whole product.
