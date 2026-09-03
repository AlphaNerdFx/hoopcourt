# Troubleshooting

## "The NVIDIA driver on your system is too old"

Usually the GPU is fine and the PyTorch build is wrong.

```
torch.__version__      2.12.1+cu130     built for CUDA 13.0
driver                 576.52           supports CUDA up to 12.9
torch.cuda.is_available()  False
```

Pip installed a PyTorch built against CUDA 13, which needs a newer driver. In
WSL2 the CUDA driver comes from the Windows host, so no amount of `apt` inside
Linux changes it.

Either update the Windows NVIDIA driver to 580 or later, or install a build
matching your driver, which is faster and changes nothing else:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu126
```

Check with:

```bash
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

Nothing in the project requires a GPU. Indexing and the whole evaluation run on
CPU. A working GPU takes an index build from roughly 80 minutes to a few.

## Index builds are slow

Embedding dominates, at 2.5 to 3 seconds per page on CPU. Rebuild one document
with `--only "<doc name>"` rather than the whole corpus.

## A query returns no sources

Check the `coverage` block in the response. It distinguishes an era no source
covers from a query that simply matched nothing, and names the nearest covered
season.

## A source URL reports 403

Some hosts refuse scripted requests. `--check-urls` sends a browser user agent
and falls back from HEAD to a ranged GET, but a stubborn 403 usually still works
in a browser.

## A document is listed as missing but the file is there

Check the case of the extension. Linux is case-sensitive and `.PDF` is not
`.pdf`. `tests/test_manifest.py` reports this specifically.
