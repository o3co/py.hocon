# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `hocon.__version__` is now derived from the installed distribution metadata
  (`importlib.metadata.version("hocon-parser")`) instead of a hardcoded
  `"0.0.0"`, so it tracks the tag-injected release version. Falls back to
  `"0.0.0"` only when run from an uninstalled source tree.

### Changed

- README badges: added PyPI version / Python versions / CI / Codecov badges
  (matching the sibling implementations); the Python badge is now driven by the
  package's `requires-python`.

## [1.8.0] - 2026-07-16

Initial published release. The version is aligned to the sibling o3co
implementations (go.hocon / rs.hocon / ts.hocon, all at 1.8.0), which move in
lockstep — py.hocon enters that lockstep at parity rather than starting a
separate 0.x line. Distributed on PyPI as `hocon-parser` (imported as `hocon`).

### Added

- `tools/hocon_json.py` — differential-harness adapter registering py.hocon in
  xx.hocon's cross-impl driver (`generate/DifferentialDriver.java`). Parses +
  resolves a `.conf` and emits canonical JSON to stdout (via the oracle-aligned
  `_render_json_for_test` renderer, mirroring ts.hocon), or a single-line
  `{"__error__":{type,message}}` record + exit 3 on failure. `tests/test_hocon_json_adapter.py`
  runs it over the whole spec-corpus and asserts equality with the
  Lightbend-generated expected JSON (an in-repo oracle differential), plus
  CLI-contract and process-env-resolution checks. `ruff` now also lints `tools`.
- Conformance-corpus expansion — five new fixture harnesses closing the gap to
  the sibling test surface (full suite: 306 passed / 1 skipped / 4 xfailed):
  - `tests/conformance/test_error_fixtures.py` — 38 error fixtures
    (`-expected-error.json` + `.error` sidecars: subst-tokenize st-err,
    concat-errors, include-reservation, env-var-list, self-ref-lookback sr05,
    path-expr-whitespace pw06, …) with ts-parity error-class pinning; us15 is
    a strict-xfail tripwire for the `+`-reservation gap shared by all siblings
    (ts#73 / rs `#[should_panic]`).
  - `tests/test_units_default.py` — units-default ud/ub/un accessor fixtures
    at rs parity. Known cross-impl note: negative durations stay signed
    (Lightbend/go-faithful; rs rejects only because `std::time::Duration` is
    unsigned) — pinned both ways (passing signed test + strict-xfail rs
    tripwire on ud06).
  - `tests/test_deferred_resolution_fixtures.py` — all 31 E12 scenario-YAML
    fixtures (dr01–dr30 incl. dr11a/b) via a dependency-free purpose-built
    scenario loader, plus dr19/dr29 programmatic companions; consumes dr12 and
    dr17, which the sibling YAML runners skip.
  - `tests/test_properties_conflict_fixtures.py` — pc01–pc04 (S23.4
    object-wins, input-order independent).
  - `tests/test_include_package_fixtures.py` — ipk01–ipk14 E11 scenarios via
    the `package_resolver` kwarg (ipk03 N/A per E11 decision 3, as in ts).
- `Config.get_period` + `Period(years, months, days)` frozen dataclass —
  S20.1–S20.4 period accessor at rs.hocon parity (ts / go remain ➖ here):
  integer-only per Lightbend `Integer.parseInt` (fractional rejected, up03),
  bare numbers default to days (HOCON.md L1321), lowercase-only units
  (`d`/`day`/`days`, `w`/`week`/`weeks` folded into days, `m`/`mo`/`month`/
  `months`, `y`/`year`/`years`), negative periods permitted, i32-bounded.
- Initial parser implementation, ported from `@o3co/ts.hocon` with the same
  3-stage pipeline (Lexer → Parser → Resolver):
  - **Lexer** — full HOCON whitespace set, quoted / triple-quoted / unquoted
    strings, `${...}` / `${?...}` substitutions with the `[]` list suffix (S13c),
    path-expression whitespace tracking (E13).
  - **Parser** — objects, arrays, value concatenation, path expressions with
    space-concat (S10.8), `+=` append, `include` (bare / `file(...)` /
    `package(...)` / `required(...)`), `include` key-path reservation (S12.5).
  - **Resolver** — two-phase build/resolve, substitution resolution with
    self-reference lookback and chained-self-append folding (S13a, #118/#120),
    delayed object merge, env-var and env-var-list fallback (S13c), numeric
    object → array conversion (S15), `.properties` includes (S23).
  - **Config accessors** (rs.hocon-style snake_case): `get` / `get_string` /
    `get_number` / `get_int` / `get_float` / `get_boolean` / `get_duration` /
    `get_bytes` / `get_config` / `get_list` / `get_value` / `has` / `keys` /
    `to_object`, plus deferred resolution (`resolve` / `resolve_with` /
    `with_fallback`, E12) and `from_map` / `empty` value factories.
  - Duration / byte-size coercion with case-sensitive duration units (S19.8) and
    power-of-two single-letter byte abbreviations (S21.4).
- Conformance harness against the shared o3co/xx.hocon corpus: **134/134 spec
  corpus** and **14/16 Lightbend suite** (the 2 held-out fixtures reference JVM
  system properties `${?java.version}` / `${?user.home}` — every non-JVM parser
  caps at 14/16). At parity with go.hocon and rs.hocon.
- Project scaffold: package layout mirroring the sibling implementations, error
  type hierarchy (`ParseError`, `ResolveError`, `PackageLookupError`,
  `ConfigError`, `NotResolvedError`), and tooling (hatchling, pytest, mypy
  strict, ruff) with the `make testdata` corpus-sync target.
