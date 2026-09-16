# Testing and staging

Every rule here corresponds to a defect that shipped in this project. None of
them are general good practice quoted from a book; they are scar tissue.

## Tiers, and what each may depend on

| Tier | Runs | May depend on | Gate |
| --- | --- | --- | --- |
| Unit and contract | every commit, in CI | nothing outside the repo | blocking |
| Data integrity | every commit, in CI | manifest and timeline YAML only | blocking |
| Retrieval eval | locally; on a public-domain index in CI at release | a built index | blocking, isolation 100% |
| Generation eval | locally only | a model and a GPU | manual gate, recorded in the release checklist |

### CI cannot test everything, and says so

CI has no corpus and no GPU, and never will. The corpus is copyrighted and
cannot legally be placed there (see `docs/corpus/DATA_SOURCES.md`), and the
runners have no accelerator.

This is a permanent structural limit, not a gap to close. Pretending otherwise
is how `scripts/audit_corpus.py` stayed broken for weeks: it crashed on every
court opinion added in Phase 7, it was named as the standing guard in four
documents, and CI could not run it because CI has no documents.

**Anything that can only be tested with the corpus needs a synthetic fixture in
the suite.** `tests/test_audit_corpus.py` now builds `.txt` and manifest fixtures
in a temporary directory and exercises the script without a single real
document. That is the pattern to copy.

## Rules

### 1. A test that cannot fail is a defect

Mutation-test anything that claims to verify a feature: remove the feature,
confirm the test goes red, put it back.

The alias eval questions score 0/2 with `concept_aliases.yaml` removed and 2/2
with it. Without that check they would be two questions that pass for reasons
nobody established.

### 2. Assert the observation, not just the verdict

```python
assert verify_citations("Defined in the [2023 NBA CBA].", CHUNKS).ok   # useless
```

`ok` is true when nothing was extracted at all. That assertion passed for a long
time while the citation was being silently discarded. Assert what was seen:

```python
report = verify_citations("Defined in the [2023 NBA CBA].", CHUNKS)
assert report.supported == ["2023 NBA CBA"]
assert report.total == 1
```

### 3. A disjunctive check is only as strong as its rarest accepted term

`expect_terms_any` passes if **any** listed term appears. Four evaluation
questions accepted a term appearing in 49% to 95% of the expected document, so
they could not fail, and they concealed a real retrieval defect (D18).

Before accepting a term, measure it:

```sql
SELECT count(*) FROM document_chunks dc JOIN documents d ON d.id = dc.doc_id
WHERE d.doc_name = 'CBA 2011' AND lower(dc.text_content) LIKE '%your term%';
```

Anything matching more than a quarter of a large document's chunks is not
evidence.

### 4. Measure every shipped variant

Casual Fan mode scored zero citations on every question for the life of the
project, and nobody knew, because `run_eval.py` only ever ran
`style="scholar"`. Both styles ship, so both get measured:
`run_eval.py --with-generation --style casual`.

Generalised: what is not exercised is not measured, and a green suite says
nothing whatever about it.

### 5. A generation figure is a range, and carries its style

Generation is not reproducible on this stack even at temperature 0. The same
five-question batch, same model, same order, scored 4/5 then 3/5: llama.cpp's
GPU forward pass is not bitwise stable, and there is no sampling to seed.

Three runs minimum. Report the range. Name the style. A figure quoted without
its style is incomplete.

### 6. Measurement runs get the machine to themselves

A single-question run started while a measurement was in flight put two requests
through the backend at once and corrupted the result, which was then discarded
rather than reported. Concurrent load also triggered an OOM kill of the model
server.

On WSL2 the guest gets roughly half the Windows total, so the 16 GB profile in
`CLAUDE.md` sec.3.1 is about 7.4 GB in practice. Run nothing else during a
generation measurement.

### 7. Check exit codes directly

```bash
pytest tests/ -q | tail -2          # returns tail's status; a failure looks green
pytest tests/ -q > /tmp/f.log 2>&1; rc=$?   # correct
```

This has already produced one commit containing a failing test.

### 8. Read the output a user would read

The two worst defects found in this project's UI were invisible to every test:
citation counts under-reported by a filter, and an entire answer mode reporting
"cites nothing" for correctly cited answers. Both were found by reading a real
answer. Tests verify the behaviour you thought to express.

## Staging

There is no deployed environment, and inventing one for a tool people install
locally would be theatre. Staging here means a release candidate.

1. Tag `vX.Y.Z-rc.N`. `release.yml` marks it a prerelease.
2. Run the manual gate below.
3. Record the numbers in the CHANGELOG section for the final version.
4. Promote by tagging `vX.Y.Z` on the same commit.

### The manual gate

Automated checks cannot cover these. Work through them by hand.

- [ ] Fresh virtualenv created **without** `--system-site-packages`,
      `pip install -r requirements.txt`, and every Makefile target runs from it.
- [ ] `make audit` passes against the real corpus.
- [ ] `make eval` passes against the real index, isolation at 100%.
- [ ] Generation eval, both styles, three runs each. Range recorded.
- [ ] Every response shape exercised in the browser: a normal answer, a 409
      ambiguous year, an uncovered era, a refusal, and the generation backend
      switched off mid-session (which must degrade to sources, not 500).

## Code review

Every change is reviewed on two axes, which are kept separate so one cannot mask
the other: **Standards** (does it follow this repo's documented conventions) and
**Spec** (does it do what was asked). Code can pass either and fail the other.

See [CODE_REVIEW.md](CODE_REVIEW.md).
