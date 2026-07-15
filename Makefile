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
# The sha is resolved via `git ls-remote` (not api.github.com) so CI runners
# sharing an egress IP don't trip the unauthenticated API rate limit, and the
# tarball is fetched by that sha so the recorded pin is exactly what landed
# (same convention as rs.hocon).
testdata:
	@set -e; \
	sha="$$(git ls-remote "https://github.com/$(TESTDATA_REPO).git" "$(TESTDATA_REF)" | head -1 | cut -f1)"; \
	if [ -z "$$sha" ]; then \
	  echo "error: could not resolve $(TESTDATA_REPO)@$(TESTDATA_REF) SHA via git ls-remote" >&2; \
	  exit 1; \
	fi; \
	if [ -f .xx-hocon-version ] && [ -d "$(TESTDATA_DIR)/hocon" ] && [ -d "$(TESTDATA_DIR)/expected" ] && \
	   [ "$$sha" = "$$(cat .xx-hocon-version)" ]; then \
	  echo "Conformance corpus up to date ($$sha)"; \
	  exit 0; \
	fi; \
	tmpdir="$$(mktemp -d)"; \
	trap 'rm -rf "$$tmpdir"' EXIT INT TERM; \
	curl -sfL "https://github.com/$(TESTDATA_REPO)/archive/$$sha.tar.gz" -o "$$tmpdir/archive.tar.gz"; \
	tar xzf "$$tmpdir/archive.tar.gz" -C "$$tmpdir" --strip-components=1; \
	rm -rf "$(TESTDATA_DIR)/hocon" "$(TESTDATA_DIR)/expected"; \
	mkdir -p "$(TESTDATA_DIR)"; \
	cp -R "$$tmpdir/testdata/hocon" "$(TESTDATA_DIR)/hocon"; \
	cp -R "$$tmpdir/expected/hocon" "$(TESTDATA_DIR)/expected"; \
	printf '%s\n' "$$sha" > .xx-hocon-version; \
	echo "Done. Fetched $$sha"

clean:
	rm -rf $(VENV) dist build .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
