# Contributing

## Setup

```bash
make install
python scripts/fetch_corpus.py     # obtain the documents yourself
make audit build seed
make check                         # tests + evaluation
```

The corpus is not in this repository and must not be added to it, see
[DATA_SOURCES.md](docs/corpus/DATA_SOURCES.md). `.gitignore` excludes `data/`, `*.pdf` and
`*.db`; please do not weaken those rules.

## The one rule that is not negotiable

**Temporal isolation must stay at 100%.** `make eval` exits non-zero on any
cross-era leak. Rule bleeding is a correctness failure, not a quality metric,
an answer that applies 2023 rules to a 1997 question is wrong in the way that
makes the whole project pointless.

If a change drops it below 100%, the change is wrong, not the gate.

## Working on retrieval

Retrieval is constrained on the `doc_id` **metadata column** of `vec_chunks`,
never on the primary key. Filtering the primary key is a *post-filter* in
sqlite-vec and returns nothing when another era dominates the ranking. This is
covered by a characterisation test that will fail if upstream behaviour changes,
read [docs/architecture/DECISIONS.md](docs/architecture/DECISIONS.md) D2 before
touching `src/db/search.py`.

Also note that sqlite-vec returns `k` rows *per document* in an IN-list, grouped
and not globally sorted. The outer `ORDER BY distance ASC LIMIT k` is required.

## Adding documents

See [DATA_SOURCES.md](docs/corpus/DATA_SOURCES.md). The `start_season`/`end_season` window in
`corpus_manifest.yaml` *is* the routing logic, record your reasoning in a comment
as the existing entries do, and add eval questions covering the new era. New
documents change which eras are covered, which changes what the refusal cases
should refuse.

## Tests

* Unit tests are offline, deterministic, and must not download models. Use the
  stub embedder pattern in `tests/test_api.py`.
* A test for a bug should fail against the old behaviour. The chunker and router
  regressions in `tests/` are written that way on purpose.
* `tests/eval/questions.yaml` is the requirement; `run_eval.py` measures it. Use
  the `CURRENT` sentinel for questions with no year in them so expectations track
  the season rollover.

## Style

Match the surrounding code. Comments explain *why*, particularly where the
implementation departs from the specification documents, because those departures
are the parts a future reader will otherwise "fix" back into a bug.
