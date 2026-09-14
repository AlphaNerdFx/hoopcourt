# Measuring generation: what the citation number means

Retrieval and generation are measured separately because they fail differently.
This document is about the second. The retrieval numbers need no caveats: they
are computed without the LLM and are exactly reproducible at 100%.

Measured on 2026-09-14 against the 46-document index, all 43 evaluation
questions, `mistral:7b` and `qwen2.5:7b-instruct` through Ollama on an RTX 4060.

---

## 1. Generation is not reproducible, even at temperature 0

This was assumed and then tested, and the assumption was wrong.

* `bird-rights` failed for qwen in the full run and passed in three isolated
  re-runs of the same question.
* The same five-question batch, same order, same model, run twice: 4/5 then 3/5.

`options.temperature` is 0.0, so sampling is greedy and nothing is being drawn
from a distribution. The variation is in the forward pass: llama.cpp on a GPU
backend is not bitwise reproducible across runs, and a seed does not help
because there is no sampling to seed.

**Consequences.**

* A single run is a sample, not a measurement. The citation figure is reported
  as a range across repeated full runs.
* An isolated `--id` re-run does **not** reproduce that question's full-run
  result. `--id` is for repairing what a backend restart cost, not for
  recomputing a score.
* Any model comparison carries two sources of variance, question sampling and
  run-to-run drift, so a difference has to be large to mean anything at n = 26.

### The range

Three full runs of `mistral:7b` over all 43 questions, same index, same prompt,
nothing changed between them:

| run | citations |
| --- | --- |
| 1 | 17/26 (65.4%) |
| 2 | 19/26 (73.1%) |
| 3 | 18/26 (69.2%) |

**17 to 19 out of 26.** Quoting any single one of those as *the* number would be
picking a sample and calling it a measurement.

## 2. What the citation check actually asserts

`verify_citations` marks an answer `ok` when it cited at least one thing and
fabricated nothing. Per answer, binary, strict. Matching is exact against the
citations the model was handed, never by substring, because a substring test
accepts a real document carrying an invented pinpoint, which is the exact
failure the check exists to catch.

It does **not** measure whether the answer is factually right. An answer can
cite perfectly and still be wrong about what the provision says.

Two questions are excluded from the check by construction: those where retrieval
correctly returns nothing, since there is no context to cite.

## 3. Not all fabrications are the same failure

The strict count conflates three things with very different severity. Every
fabricated citation from both models was classified by rebuilding the exact
context the model was handed, which retrieval makes reproducible.

| Kind | mistral | qwen | What it means |
| --- | --- | --- | --- |
| Invented: base citation never supplied | 1 | 1 | The fatal case. CLAUDE.md sec.2.2. |
| Narrowed: supplied citation plus a subdivision present in the chunk | 6 | 2 | Grounded at page level, unverified below it |
| Narrowed: subdivision not found in the chunk | 1 | 0 | Closer to invention |
| Not a citation at all (`implied from context`) | 1 | 0 | Visible nonsense, not misleading |

**One invented citation each, across 26 answered questions.** The headline
failure rate is dominated by over-precision, not by hallucinated law:

    handed    2023 NBA CBA, Article II, Section 6, p. 57
    written   2023 NBA CBA, Article II, Section 6, p. 57 (a)

The strict rule still calls that a fabrication and the rule is not being
relaxed. A reader following "(a)" expects subsection (a) to support the claim,
and nothing verified that. Finding the string "(a)" in the chunk is weak
evidence, since legal text is full of subdivision markers; it establishes the
citation is not a document-level invention, not that it is correct.

The number is reported strict. The breakdown is reported next to it, because
"the model invents law" and "the model is too precise about where it read
something" call for different fixes and only one of them is a reason to
fine-tune.

## 4. The two models fail in opposite directions

Both scored the same strict total. That tie hides the finding.

| | mistral:7b | qwen2.5:7b-instruct |
| --- | --- | --- |
| Fabricated a citation | 5 | 2 |
| Answered without citing | 1 | 8 |

Qwen declines on questions the corpus demonstrably covers: it answered
"the context provided does not contain specific information about the maximum
annual salary a player could receive in 2013" on a question where the `recall`
check passes against the same retrieved chunks. Mistral over-claims; qwen
over-refuses.

Neither is obviously better. A fabricated citation is more dangerous because it
is invisible, and CLAUDE.md sec.2.2 names it a fatal error. An answer that
refuses when the text is in front of it is safe and useless. The UI already
renders these as distinct states rather than collapsing both into "failed".

## 5. The comparison verdict

Paired over the same questions, McNemar exact two-sided on the discordant pairs:
**p = 0.34. No detectable difference.** The decision rule was fixed before the
results were read, and it says to conclude exactly that rather than crowning
whichever model scored higher.

Tie-breaks, also fixed in advance: both are Apache-2.0, so licence does not
separate them; mistral:7b is the smaller download.

## 6. The prompt fix has already been tried, and it does not work

Worth stating before anyone proposes prompt engineering as the answer. The
scholar prompt already contains this rule, verbatim:

> A citation contains nothing but an entry from the permitted list, copied
> whole. Do not append sub-paragraph detail of your own: if the list says
> "p. 57", cite "p. 57", never "p. 57 (a)".

Mistral then emitted `2023 NBA CBA, Article II, Section 6, p. 57 (a)`. That is
the prompt's own counterexample, reproduced character for character, in the
document the example was written about.

So this is not a gap in the instructions. It is a 7B at Q4_K_M failing to follow
an explicit, exemplified negative constraint. An earlier attempt to push harder
made things worse: a rule telling the model to cite what it claims cut validity
from 8/10 to 4/10 by producing finer invented pinpoints, not fewer.

## 7. Where that leaves the fine-tune

**Phase C is still not the next step, but the reasoning changes.**

The gate is whether off-the-shelf models can close the gap. For the failure that
CLAUDE.md sec.2.2 actually calls fatal, inventing a citation that was never
supplied, there is no real gap to close: one case per 26 questions, for both
models. For the over-precision habit, prompting is exhausted.

That leaves four options, in ascending cost:

1. **Accept and surface it.** The current behaviour. The citation is marked
   unverified and the UI shows it. Honest, and it ships.
2. **Classify it accurately rather than calling it fabrication.** The system
   holds the closed list, so it can tell "narrowed a permitted citation" from
   "invented a document" and report which. This converts one misleading label
   into two accurate ones without touching the model. Cheapest real improvement,
   and it is the one to try next.
3. **A larger or better instruction-following model**, measured the same way.
4. **QLoRA on citation discipline.** Expensive, and it targets a habit rather
   than a knowledge gap.

Do not silently rewrite the model's citations to make them verifiable. Stripping
"(a)" would leave the surrounding prose still claiming subsection (a), and would
hide from the reader what the model actually did. Classify, do not launder.


---

## 8. Part of the citation failure was retrieval, not generation

Found after the numbers above were taken, and it changes how to read them.

Both models refused `max-salary-2024`, and the eval scored both as citation
failures. Checking the context they were handed: five apron and worked-example
passages, none of which states the Maximum Annual Salary rule. **The models were
right.** They were asked a question their context could not answer and said so.

The `recall` check had passed anyway, on the term "Salary Cap", which appears in
49% of the expected document's chunks. Four questions were passing on terms like
that. Tightening them to discriminative terms exposed a real retrieval defect
(D18: the query's year was outranking the provision with dated examples of it),
and fixing that took the suite to 43/43 against the harder terms.

**What this means for the citation figures above.** They were measured before the
retrieval fix, so some fraction of the failures were the model correctly
declining to answer from inadequate context, and at least one was a model citing
a permitted-but-irrelevant passage and scoring as a success. The citation check
verifies **provenance, not relevance**: it asks whether a citation was in the
context, never whether the cited passage supports the claim.

Any generation figure taken before D18 is therefore a lower bound of uncertain
tightness, and the comparison between the two models is affected asymmetrically:
qwen's over-refusal was partly correct behaviour on questions where retrieval had
failed, and mistral's confidence on those same questions was partly unearned.
