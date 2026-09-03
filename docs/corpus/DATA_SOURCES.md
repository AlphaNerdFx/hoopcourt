# Data Sources

This repository contains **no** NBA documents, no extracted text, and no compiled
index. Those are copyrighted works belonging to the NBA, the NBPA, and their
licensors. What ships here is the code that reads them, the manifest that
describes them, and the checksums that let you verify your own copy.

Run `python scripts/fetch_corpus.py` to see which documents you still need and
where each one comes from.

## Why it works this way

An earlier plan for this project (BUILD_SEQUENCE.md Step 8) proposed publishing a
pre-compiled `nba_legal.db` over IPFS with a BitTorrent magnet-link fallback. That
database would have contained the full text of every document in the corpus.
Distributing the text is the same act as distributing the PDFs, so moving it out
of the git repository and onto a peer-to-peer network relocated the problem
rather than solving it.

The approach here avoids it entirely: **you** obtain the documents from their
official or public-record sources, and **you** compile the index locally. The
project distributes instructions and SHA-256 checksums, neither of which is a
copy of anything.

## Where the documents come from

| Class | Source | Notes |
| --- | --- | --- |
| Current CBA, CBA 101, Uniform Player Contract, agent regulations | **NBPA**, <https://nbpa.com/cba> and <https://nbpa.com/agents> | The union publishes the operative agreement and its exhibits. |
| Rulebook, Officials Guide, Constitution, lottery materials | **NBA**, <https://official.nba.com/rule-book/> | Reissued each season; the manifest pins the season each edition governs. |
| Superseded CBAs (1995, 1999, 2005, 2011, 2017) | **CourtListener / RECAP**, <https://www.courtlistener.com/> | Historical agreements entered as public exhibits in antitrust and labour litigation. These are court records. |
| Pre-1980 guides and historical draft materials | **Internet Archive**, <https://web.archive.org/> | Use official Archive entries only. |

### Not acceptable as sources

Do not link to or download from personal cloud-storage mirrors, MEGA, Google
Drive, Dropbox, or similar. Beyond being unstable and unverifiable, pointing
users at an unauthorised copy invites a contributory-infringement claim against
this project. If a document is not available from an official or public-record
source, it does not go in the manifest.

## Adding a document

1. Add an entry to `corpus_manifest.yaml`. The `start_season` / `end_season`
   window is the temporal routing logic, a wrong window is a rule-bleeding bug
   no retrieval tuning can fix, so record the reasoning in a comment as the
   existing entries do.
2. Save the file at the `file:` path under `data/` (gitignored).
3. `python scripts/audit_corpus.py`, confirms the PDF has a usable text layer.
4. `python scripts/build_index.py`, rebuilds; re-running is idempotent per
   document.
5. `python scripts/fetch_corpus.py --record`, refresh `corpus_checksums.json`.
6. Add eval questions in `tests/eval/questions.yaml` covering the new era, and
   re-run `python tests/eval/run_eval.py`. New documents change which eras are
   covered, which changes what the refusal cases should refuse.

## Checking the sources still work

```bash
python scripts/fetch_corpus.py --check-urls
```

Fetches headers for every `source_url` and compares the remote size against your
local file. This catches two failures that reading the YAML cannot:

* **A URL that serves a different document.** The 2012 Constitution entry was
  once pasted from the 2019 entry; both looked plausible, and only the byte count
  gave it away.
* **A URL that returns HTML rather than a PDF**, a Scribd or Drive viewer page,
  where a reader gets a web page instead of the document.

`403` usually means the host refuses scripted requests, not that the link is
dead; check those in a browser. Where a source legitimately serves a different
printing of the same document, set `source_verified: true` on the manifest entry
after confirming the edition by hand, and record what you checked in a comment.

## Verifying a copy

```bash
python scripts/fetch_corpus.py --verify
```

A mismatch means your file differs from the one the checksums were recorded
against, usually a different edition or printing rather than corruption. Both
matter here: a different edition may carry different section numbering, which
changes every citation the system produces from it.
