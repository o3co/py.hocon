# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
