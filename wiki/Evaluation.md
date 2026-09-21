# Evaluation

```bash
python tests/eval/run_eval.py --db nba_legal.db
```

45 labelled questions across four categories. Every assertion is checkable
without an LLM, so the suite runs offline, free, and on CPU.

| Category | Asserts |
| --- | --- |
| `temporal_isolation` | the same question in different eras reaches different rulesets, with zero cross-era chunks |
| `grounded_citation` | retrieval reaches the right document and a real provision |
| `refusal` | an uncovered era or an anachronism returns nothing |
| `trigger_routing` | historical terms route correctly, and modern uses of the same words do not |

## The gate

Temporal isolation must be 100%. Rule bleeding is a correctness failure, not a
quality metric, so `run_eval.py` exits non-zero on any leak.

## What it does not catch

The eval measures which documents retrieval reaches and whether an expected term
appears in the top-5. It does not measure ranking quality within a document.

A real defect once fused 35% of one document's chunks into unsearchable noise and
the suite still reported full marks: the era-correct document was still reached,
and enough intact chunks carried the expected terms.

So a green run means routing is right and nothing bled across eras. It does not
mean the best passage was retrieved. Run `scripts/audit_corpus.py` after changing
any document, because a green eval will not tell you the text went bad.

A second instance of the same blind spot, found later and worth repeating
because it is easy to reintroduce: the recall check accepts **any one** of
several terms, so it is only as strong as its rarest accepted term. Four
questions were accepting a term that appears in 49% to 95% of the expected
document, which cannot fail. They passed on that term while the passage that
actually answered the question was never retrieved.

If you add a question, check the corpus frequency of every term you accept:

```sql
SELECT count(*) FROM document_chunks dc JOIN documents d ON d.id = dc.doc_id
WHERE d.doc_name = 'CBA 2011' AND lower(dc.text_content) LIKE '%your term%';
```

Anything matching more than a quarter of the document's chunks is not evidence.

## Generation

```bash
python tests/eval/run_eval.py --db nba_legal.db --with-generation
```

Slower, needs a backend, and measures one extra thing: whether the answer cited
only what it was handed.

**The number is a range, not a number.** Generation is not reproducible on this
stack even at temperature 0: sampling is greedy, but llama.cpp's GPU forward
pass is not bitwise stable. Three identical full runs scored 17, 19 and 18 out
of 26. Repeat before concluding anything, and do not compare a single run
against a single run.

`--id QUESTION_ID` runs named questions. Useful for repairing what a backend
restart cost, but an isolated re-run does not reproduce that question's
full-run result, for the same reason.
