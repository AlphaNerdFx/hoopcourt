# Code review

Two axes, reviewed separately and reported separately.

* **Standards**: does the code follow this repository's documented conventions?
* **Spec**: does it do what was actually asked?

They are kept apart because a change can pass one and fail the other, and
merging the reports lets the pass hide the failure:

* Follows every convention, implements the wrong thing: Standards pass, Spec fail.
* Does exactly what was asked, ignores the repo's conventions: Spec pass, Standards fail.

The `code-review` skill runs both as parallel sub-agents against
`git diff <fixed-point>...HEAD` and prints them side by side without reranking.

## Standards axis

### Documented conventions

Read `CLAUDE.md` and `CONTRIBUTING.md` first; they win over anything below.
The ones most often breached:

* **Comments explain why, with evidence.** A comment restating the code is
  noise. A comment recording the measurement that forced the code is the most
  valuable thing in the file. Compare: "strip the year" against "the year is
  consumed twice, and the second use ranks dated examples above the rule that
  states them; measured, the provision went from absent to rank 2".
* **SQL uses bound parameters.** F-strings in SQL execution are banned
  (`CLAUDE.md` sec.7.4).
* **No content in the repository.** No corpus documents, no compiled index, no
  pasted transcripts. This has been breached once, by a `git add -A` that swept
  in a UI transcript containing verbatim CBA text.
* **Commit messages under 256 characters, brief.**
* **No em dashes. Bold only where it carries weight.**

### Smell baseline

Applied in addition to the documented conventions. A documented convention
always overrides it, and every smell is a judgement call rather than a
violation. Skip anything ruff already enforces.

From Fowler, *Refactoring* ch.3:

| Smell | What it is | Fix |
| --- | --- | --- |
| Mysterious Name | name does not reveal what it does or holds | rename; if no honest name comes, the design is murky |
| Duplicated Code | the same logic shape in more than one place | extract, call from both |
| Feature Envy | a method reaching into another object's data more than its own | move it onto the data |
| Data Clumps | the same few fields always travelling together | bundle into a type |
| Primitive Obsession | a string or int standing in for a domain concept | give the concept a type |
| Repeated Switches | the same cascade on the same type, in several places | polymorphism, or one shared map |
| Shotgun Surgery | one logical change forcing scattered edits | gather what changes together |
| Divergent Change | one module edited for several unrelated reasons | split it |
| Speculative Generality | abstraction for needs the spec does not have | delete it |
| Message Chains | long `a.b().c().d()` navigation | hide the walk behind one method |
| Middle Man | a class that mostly delegates onward | cut it |
| Refused Bequest | a subclass ignoring most of what it inherits | use composition |

## Spec axis

Report three things:

* **(a)** Requirements asked for that are missing or partial.
* **(b)** Behaviour in the diff nobody asked for.
* **(c)** Requirements that look implemented but are implemented wrongly.

Quote the spec line for each finding. Where there is no issue tracker, the spec
is this repository's own documented contracts: `CLAUDE.md` sec.2.2 for grounding,
sec.6 for the answer styles, and the module docstrings that state a contract,
such as `src/model/verify.py`.

Category (c) is the one that earns the axis. A review that only checks whether
the boxes were ticked misses a fix that ticks the box and introduces a worse
defect, which is exactly what happened when a citation fix cured under-reporting
by building in over-reporting, so a hallucinated source became invisible. Both
axes found it independently, which is the case for running both.

## Fixed point

Review against the last release tag by default. Confirm the ref resolves and the
diff is non-empty before dispatching, so a bad ref fails early rather than
inside two sub-agents.
