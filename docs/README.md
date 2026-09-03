# Documentation

| Area | Contents |
| --- | --- |
| [architecture/](architecture) | How the system is built and why it departs from the specification |
| [corpus/](corpus) | Where documents come from and how to obtain them |
| [operations/](operations) | Current status, known limits, what is measured |
| [security/](security) | Threat model and data-protection posture |
| [specification/](specification) | The original design documents, kept for context |
| [ai/](ai) | Handover notes for a new contributor, human or model |

## Start here

1. [architecture/DECISIONS.md](architecture/DECISIONS.md) records every place the
   implementation departs from the specification, with the measurement behind it.
   It is the most useful file in this directory.
2. [architecture/ARCHITECTURE.md](architecture/ARCHITECTURE.md) traces the request
   and build paths.
3. [operations/STATUS.md](operations/STATUS.md) states what works, what does not,
   and what the evaluation does not catch.

## A note on specification/

`specification/` holds the documents the project began from: a PRD, an
implementation plan, and a 2,300-line build sequence containing pre-written code.
That code was never executed. Several parts of it are provably wrong, most
seriously an era filter that returns nothing under the exact conditions the
project exists to handle.

Treat those files as history, not instruction. Where they disagree with
`architecture/DECISIONS.md`, DECISIONS.md is current.
