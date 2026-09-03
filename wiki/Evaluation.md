# Evaluation

```bash
python tests/eval/run_eval.py --db nba_legal.db
```

43 labelled questions across four categories. Every assertion is checkable
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
