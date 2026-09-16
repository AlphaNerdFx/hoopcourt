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

Sequencing moved to the commercial repository. What remains here is the
reasoning that is settled, because settled reasoning is a fact about the project
and a phase list is a guess about the future.

The three arguments above are the durable part: this is a tool rather than a
service, serving infrastructure is sequenced to real load, and statistics are
not a retrieval problem. Each is recorded in
[../architecture/DECISIONS.md](../architecture/DECISIONS.md) with the evidence.

---

## What would change this plan

* A public pre-1995 CBA surfacing would reduce the judicial and timeline tiers
  from necessity to supplement.
* An official or licensable statistics feed would move Phase B from
  fetch-and-build to something distributable.
* A decision to revisit hosting would reopen Phase D and, with it, the
  copyright question that made it risky. The self-hosted tool is now the whole
  product by choice, not by constraint.
