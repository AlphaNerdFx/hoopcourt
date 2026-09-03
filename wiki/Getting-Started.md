# Getting Started

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

python scripts/fetch_corpus.py       # what to download, and from where
python scripts/fetch_opinions.py     # public-domain court opinions
python scripts/audit_corpus.py       # confirm every file has usable text
python scripts/build_index.py        # compile the local index
python scripts/seed_concepts.py      # historical analogies for casual mode

make check                           # tests plus evaluation
uvicorn src.api.main:app --reload    # http://127.0.0.1:8000/docs
```

## The corpus is not in the repository

You download the documents yourself from official and public-record sources. The
project ships instructions and SHA-256 checksums, never content. See
`docs/corpus/DATA_SOURCES.md`.

Court opinions are the exception to the effort: they are public domain and
`fetch_opinions.py` retrieves them automatically.

## Build time

Indexing is CPU bound on embedding, roughly 2.5 to 3 seconds per page, so the
full 3,412-page corpus takes a couple of hours. It is a one-time cost, and
`--only "<doc name>"` rebuilds a single document.

If you have an NVIDIA GPU and it is not being used, see
[Troubleshooting](Troubleshooting).
