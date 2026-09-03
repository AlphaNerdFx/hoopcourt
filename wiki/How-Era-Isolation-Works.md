# How Era Isolation Works

Retrieval runs in four steps.

1. The router resolves the question to a season. An explicit year wins; then
   historical trigger terms; then decade slang; then the current season.
2. The season resolves to document ids through `documents.start_season` and
   `end_season`.
3. A KNN search runs with those ids as a pre-filter.
4. Results are re-sorted globally and capped.

## Why the pre-filter must be on a metadata column

`sqlite-vec` offers two ways to constrain a search, and only one is a real
pre-filter.

| Form | Behaviour |
| --- | --- |
| `chunk_id IN (subquery)`, the primary key | `k` applied first, filter after. A post-filter. |
| `doc_id IN (...)`, a declared metadata column | Candidates restricted before the search. |

Measured on sqlite-vec v0.1.9 with 200 chunks and a query sitting on the modern
cluster, asking for historical documents: the primary-key form returned 0 rows,
the metadata form returned the correct 5.

The original specification chose pre-filtering by name and then wrote
post-filtering's code. A characterisation test in `tests/test_vector_retrieval.py`
fails if upstream behaviour ever changes, so the deviation cannot outlive its
reason.

## Why the outer sort matters

With an IN-list of N documents, sqlite-vec returns `k` rows per document, grouped
by document and not globally sorted. Without `ORDER BY distance ASC LIMIT k` on
the outer query you get the wrong top-k, quietly, with no error.

## Ambiguous seasons

"2023" may mean 2022-23 or 2023-24, which in this corpus are governed by
different agreements. Every document boundary creates that ambiguity, not just
2023: the corpus yields 15 such years. The set is derived from the index rather
than hardcoded, so adding a document guards its own boundary. Those queries
return HTTP 409 with both options.
