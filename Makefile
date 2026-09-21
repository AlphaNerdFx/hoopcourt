# Hoopcourt
VENV   ?= venv
PY     := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip
DB     ?= nba_legal.db

.PHONY: help venv install install-dev corpus opinions audit build seed test eval \
        lint serve check urls clean

help:
	@echo "make install   create venv and install core dependencies"
	@echo "make install-dev  add lint and coverage tooling"
	@echo "make corpus    report which documents are missing and where to get them"
	@echo "make opinions  fetch the public-domain court opinions"
	@echo "make urls      check every source URL still serves its document"
	@echo "make audit     confirm every source carries usable text"
	@echo "make build     compile the local index (slow: ~2.5-3s/page, CPU-bound)"
	@echo "make seed      load historical concept analogies"
	@echo "make lint      ruff"
	@echo "make test      unit tests"
	@echo "make eval      routing + anti-bleed evaluation (the gate)"
	@echo "make check     test + eval"
	@echo "make serve     run the API on :8000"

venv:
	python3 -m venv $(VENV)

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

install-dev: venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt

corpus:
	$(PY) scripts/fetch_corpus.py

opinions:
	$(PY) scripts/fetch_opinions.py

urls:
	$(PY) scripts/fetch_corpus.py --check-urls

audit:
	$(PY) scripts/audit_corpus.py

build:
	$(PY) -u scripts/build_index.py --db $(DB)

seed:
	$(PY) scripts/seed_concepts.py --db $(DB)

lint:
	$(PY) -m ruff check src scripts tests

test:
	# No -q here: pyproject already sets it in addopts, and a second one
	# makes -qq, which suppresses the pass/fail summary entirely. `make test`
	# printed dots and nothing else, on a project whose own rule is to check
	# the result rather than trust the absence of noise.
	$(PY) -m pytest tests/

eval:
	$(PY) tests/eval/run_eval.py --db $(DB)

check: lint test eval

serve:
	# python -m, not $(VENV)/bin/uvicorn: the console script only exists if
	# uvicorn was installed into this venv, and a venv created with
	# --system-site-packages can import it while having no script for it.
	$(PY) -m uvicorn src.api.main:app --reload

clean:
	rm -rf .pytest_cache **/__pycache__ build_full.log
