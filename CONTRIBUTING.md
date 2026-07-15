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
- Modules under `hocon._internal` are **not** part of the public API
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

## License

By contributing, you agree that your contributions will be licensed under the
[Apache License 2.0](LICENSE).
