# Contributing to py.hocon

Thank you for your interest in contributing!

## Reporting Bugs

Please open a [GitHub Issue](https://github.com/o3co/py.hocon/issues) and include:

- Python version (`python --version`)
- py.hocon version
- A minimal reproducing HOCON snippet
- Expected vs. actual behavior

## Proposing Features

Open an issue first to discuss the proposal before sending a PR. This avoids
wasted effort if the direction doesn't fit the project scope.

## Development Setup

Requires Python 3.11+.

```bash
git clone https://github.com/o3co/py.hocon.git
cd py.hocon
make setup     # creates .venv and installs the package + dev tools (editable)
make check     # ruff + mypy --strict + pytest
```

`make setup` uses `python3.11` by default; override with `make setup PYTHON=python3.12`.

## Running Tests

```bash
# All tests (unit + conformance)
make test

# Lint / type-check / tests together
make check

# Sync the shared conformance corpus from o3co/xx.hocon, then run it
make testdata
make test

# Micro-benchmarks
make bench
```

The conformance suite (`tests/conformance/`) drives every fixture from
[o3co/xx.hocon](https://github.com/o3co/xx.hocon) through the parser and compares
the resolved output against Lightbend-generated expected JSON. Run `make testdata`
once to fetch the corpus (git-ignored); the suite skips gracefully if it is absent.

## Code Style

- `mypy --strict` throughout — no untyped defs, no implicit `Any`
- `ruff` for lint + import ordering (`make lint`)
- Keep the public API consistent with ts.hocon / rs.hocon (throwing typed getters,
  snake_case accessor names)
- New features must include tests; spec-relevant changes should add or update a
  conformance fixture in xx.hocon, not just a local test
- Modules under `hocon._internal`, and `hocon.coerce`, are **not** part of the
  public API
- Preserve cross-language parity: this parser mirrors
  [ts.hocon](https://github.com/o3co/ts.hocon)'s 3-stage pipeline
  (Lexer → Parser → Resolver). A spec-behavior change here should be reconciled
  with the sibling implementations.

## Submitting a Pull Request

1. Fork the repository and create a branch from `main`
2. Write tests for your change
3. Ensure `make check` passes (ruff + mypy --strict + pytest)
4. Update `CHANGELOG.md` under `[Unreleased]` for any user-facing change
5. Open a PR against `main` with a clear description of what and why

## Releasing

**The tag is the version.** `pyproject.toml` stays at `version = "0.0.0"` on
`main`; the release workflow (`.github/workflows/release.yml`) writes the real
version from the tag before it builds. Do not bump `pyproject.toml` in a PR
(the workflow skips the rewrite when the two already agree, but the manifest
is not where a version is decided).

1. **Release-prep PR** against `main`, with a commit `chore(release): X.Y.Z`
   that renames the content of `## [Unreleased]` in `CHANGELOG.md` to
   `## [X.Y.Z] - YYYY-MM-DD`, leaving an empty `## [Unreleased]` above it.
   `make check` must pass, including `tests/test_docs.py` (the doc gate:
   README facts recomputed from `pyproject.toml` and
   `docs/spec-compliance.md`).
2. **Tag** the merged commit on `main` with `vX.Y.Z` and push the tag.
3. **CI** (`release.yml`) then:
   1. sets the version from the tag;
   2. fetches the conformance corpus and runs mypy and the tests;
   3. builds the sdist and wheel;
   4. extracts the `## [X.Y.Z]` section of `CHANGELOG.md` as the release
      notes — a missing section fails the run before anything is published;
   5. creates the GitHub Release, then publishes `hocon-parser` to PyPI via
      Trusted Publishing.

> **Do not** upload to PyPI by hand. PyPI never accepts the same version
> twice, so a release has to go through the gated workflow.

## License

By contributing, you agree that your contributions will be licensed under the
[Apache License 2.0](LICENSE).
