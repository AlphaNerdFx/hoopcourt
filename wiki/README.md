# Wiki source

GitHub wikis live in a separate repository, `<repo>.wiki.git`, so these pages are
kept here under version control and pushed there.

```bash
git clone https://github.com/AlphaNerdFx/hoopcourt.wiki.git /tmp/wiki
cp wiki/*.md /tmp/wiki/
cd /tmp/wiki && git add -A && git commit -m "Update wiki" && git push
```

`Home.md` is the landing page. Links use bare page names, which is how GitHub
wikis resolve them.
