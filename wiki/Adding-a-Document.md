# Adding a Document

1. Add an entry to `corpus_manifest.yaml`.
2. Save the file at the `file:` path under `data/`, which is gitignored.
3. `python scripts/audit_corpus.py` confirms a usable text layer and no fused words.
4. `python scripts/build_index.py` rebuilds, idempotently, per document.
5. `python scripts/fetch_corpus.py --record` refreshes the checksums.
6. Add evaluation questions covering the new era and run `make eval`.

## The season window is the routing logic

`start_season` and `end_season` decide which questions can reach the document. A
wrong window is not a crash, it is a confident wrong answer carrying a real
citation. Record your reasoning in a comment, as the existing entries do.

Two editions of the same document must never both govern a season.
`tests/test_manifest.py` enforces that for the CBA and Constitution lineages.

## What the tests catch

Five defects arrived in one round of hand-editing and none raised an error:

- a `.pdf` extension where the file on disk was `.PDF`, so the build skipped it
- an `end_season` overlapping the next edition
- a `source_url` pasted from a neighbouring entry, serving a different document
- a window extending past the agreement the document belongs to
- a rename, which stranded the previous rows in the index

Run `python scripts/fetch_corpus.py --check-urls` after changing any source. It
compares the remote size with your local file and catches both a URL serving the
wrong document and one returning a viewer page instead of a PDF.

## Timeline entries

Entries live in `historical_timeline.yaml`, which is committed because it is
authored content rather than corpus. Every entry needs a citation and a
confidence level. `high` means the cited opinion is in the index and a reader can
retrieve it; `medium` means the claim comes from the league's published history
and answers must say so.
