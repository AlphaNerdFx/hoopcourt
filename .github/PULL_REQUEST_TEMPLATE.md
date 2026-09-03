## What this changes

<!-- One or two sentences. What is different after this merges? -->

## Why

<!-- The problem being solved. Link an issue if there is one. -->

## Evidence

<!-- This project prefers measurements to assertions. If you changed retrieval,
     routing, extraction or the corpus, show the numbers before and after. -->

```
make check
```

- [ ] `make test` passes
- [ ] `make eval` passes and temporal isolation is still 100%

## Checklist

- [ ] No copyrighted document, extracted text, or built index is committed
- [ ] Season windows in `corpus_manifest.yaml` carry a comment explaining them
- [ ] New timeline entries carry a citation and a confidence level
- [ ] `CHANGELOG.md` updated under Unreleased
- [ ] Tests were written after the change was working, not before

## Anything reviewers should push back on

<!-- Assumptions you are unsure about. Naming them gets better review than
     hoping nobody asks. -->
