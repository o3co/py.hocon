PYTHON ?= python3.11
VENV   := .venv

TESTDATA_REPO := o3co/xx.hocon
TESTDATA_REF  := main
TESTDATA_DIR  := tests/conformance/testdata

.PHONY: setup test lint typecheck check bench testdata clean

# Bootstrap the dev venv (idempotent).
setup:
	test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --quiet --upgrade pip
	$(VENV)/bin/pip install --quiet -e . --group dev

test:
	$(VENV)/bin/python -m pytest

lint:
	$(VENV)/bin/ruff check src tests benchmarks

typecheck:
	$(VENV)/bin/mypy

check: lint typecheck test

bench:
	$(VENV)/bin/python benchmarks/bench.py

# Sync the conformance corpus (fixtures + Lightbend-generated expected JSON)
# from o3co/xx.hocon. Skips the download when the pinned sha is current.
testdata:
	@if [ -f .xx-hocon-version ] && [ -d "$(TESTDATA_DIR)/hocon" ] && [ -d "$(TESTDATA_DIR)/expected" ]; then \
	  remote_sha=$$(curl -sf "https://api.github.com/repos/$(TESTDATA_REPO)/commits/$(TESTDATA_REF)" | grep '"sha"' | head -1 | cut -d'"' -f4) && \
	  local_sha=$$(cat .xx-hocon-version) && \
	  if [ "$$remote_sha" = "$$local_sha" ]; then \
	    echo "Conformance corpus up to date ($$local_sha)"; exit 0; \
	  fi; \
	fi; \
	tmpdir="$$(mktemp -d)" && \
	trap 'rm -rf "$$tmpdir"' EXIT INT TERM && \
	curl -sfL "https://github.com/$(TESTDATA_REPO)/archive/$(TESTDATA_REF).tar.gz" -o "$$tmpdir/archive.tar.gz" && \
	tar xzf "$$tmpdir/archive.tar.gz" -C "$$tmpdir" --strip-components=1 && \
	rm -rf "$(TESTDATA_DIR)/hocon" "$(TESTDATA_DIR)/expected" && \
	mkdir -p "$(TESTDATA_DIR)" && \
	cp -R "$$tmpdir/testdata/hocon" "$(TESTDATA_DIR)/hocon" && \
	cp -R "$$tmpdir/expected/hocon" "$(TESTDATA_DIR)/expected" && \
	curl -sf "https://api.github.com/repos/$(TESTDATA_REPO)/commits/$(TESTDATA_REF)" | grep '"sha"' | head -1 | cut -d'"' -f4 > .xx-hocon-version && \
	echo "Done. Fetched $$(cat .xx-hocon-version)"

clean:
	rm -rf $(VENV) dist build .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
