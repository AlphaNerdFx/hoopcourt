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

### The project is a tool, not a service (settled)

An earlier version of this roadmap treated a hosted service as the end state and
flagged it as the largest legal risk in the project. That risk is now gone,
because the goal changed: Hoopcourt is something people install and run.

The reasoning is worth keeping, because it explains why the decision matters.
Every copyright position this project holds rests on one posture: the user
fetches the documents themselves and builds their own index, so nothing
copyrighted is ever redistributed. That is why the IPFS plan was killed (D4), why
the Uniform Player Contract was dropped rather than sourced from a viewer page
(D12, D13), and why `DATA_SOURCES.md` refuses personal mirrors. A hosted service
would have inverted it: the project holding the corpus and serving derived
answers to the public at scale. No infrastructure choice fixes that.

As a tool, the posture holds end to end, and the serving stack collapses to
"whatever runs on the user's own machine", which today is Ollama.

### vLLM and llm-d are out of scope, not deferred

Both exist to serve many simultaneous requests. vLLM's advantage appears at
roughly five or more concurrent users; below that it reserves more GPU memory
than Ollama and returns nothing for it. llm-d is a CNCF Kubernetes project that
splits prefill and decode across separate machines.

With no service, there are no concurrent users and no cluster, so neither has a
problem to solve here. Ollama already holds the model entirely in VRAM through
its own CUDA runtime. It is not a placeholder for something better; at this scale
it is the right answer.

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

### D. Dropped

Hoopcourt is a tool, not a service. vLLM and llm-d leave the roadmap with it.

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
* A decision to revisit hosting would reopen Phase D and, with it, the
  copyright question that made it risky. The self-hosted tool is now the whole
  product by choice, not by constraint.
