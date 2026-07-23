# py.hocon — HOCON Parser for Python

[![PyPI](https://img.shields.io/pypi/v/hocon-parser.svg)](https://pypi.org/project/hocon-parser/)
[![Python](https://img.shields.io/pypi/pyversions/hocon-parser.svg)](https://pypi.org/project/hocon-parser/)
[![CI](https://github.com/o3co/py.hocon/actions/workflows/test.yml/badge.svg)](https://github.com/o3co/py.hocon/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/o3co/py.hocon/branch/main/graph/badge.svg)](https://codecov.io/gh/o3co/py.hocon)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Spec conformance](https://img.shields.io/badge/spec%20corpus-134%2F134-brightgreen.svg)](docs/spec-compliance.md)

A [Lightbend HOCON specification](https://github.com/lightbend/config/blob/main/HOCON.md)
parser for Python. Hand-written lexer, recursive-descent parser, and a typed `Config`
API. Zero runtime dependencies (pure stdlib), Python 3.11+, fully typed (`py.typed`).
See [Spec Compliance](#spec-compliance) for the current conformance rate.

> **Implemented by [Claude](https://claude.ai/) (Anthropic)** — designed and built
> end-to-end with Claude Code, ported from the sibling
> [ts.hocon](https://github.com/o3co/ts.hocon) implementation.

[日本語](README.ja.md)

> **Library stance** — py.hocon is a HOCON config loader. Its purpose is reading
> `.conf` config files and providing typed access via the `Config` API
> (`get_string`, `get_number`, `get_boolean`, `get_duration`, `get_bytes`,
> `get_period`, `to_object`). It is not a low-level parser API — internal types under
> `hocon._internal` may change between minor versions.
>
> **Cross-language conformance** — This implementation is tested against shared
> expected-JSON fixtures from [o3co/xx.hocon](https://github.com/o3co/xx.hocon)
> alongside [ts.hocon](https://github.com/o3co/ts.hocon),
> [go.hocon](https://github.com/o3co/go.hocon), and
> [rs.hocon](https://github.com/o3co/rs.hocon), ensuring all four implementations
> meet the same Lightbend HOCON specification.

---

## Quick Start

### 1. Install

```sh
pip install hocon-parser
```

The import name is `hocon`:

```python
import hocon
```

### 2. Use

```python
import hocon

cfg = hocon.parse("""
    server {
        host = "localhost"
        port = 8080
    }
    database {
        url = "jdbc:postgresql://localhost/mydb"
        pool-size = 10
    }
""")

cfg.get_string("server.host")   # "localhost"
cfg.get_int("server.port")      # 8080
cfg.has("server.host")          # True
```

## Why HOCON?

| | `.env` | JSON | YAML | HOCON |
|---|---|---|---|---|
| Comments | No | No | Yes | Yes |
| Nesting | No | Yes | Yes | Yes |
| References / Substitution | No | No | No | Yes (`${var}`) |
| File inclusion | No | No | No | Yes (`include`) |
| Object merging | No | No | Anchors (fragile) | Yes (deep merge) |
| Optional values | No | No | No | Yes (`${?var}`) |
| Trailing commas | N/A | No | N/A | Yes |
| Unquoted strings | Yes | No | Yes | Yes |

HOCON isn't just a serialization format — it's a **config-injection language**.
JSON, YAML, and TOML describe data structures and leave file layering, environment
variables, and reference resolution to your code (Pydantic, attrs, etc.). HOCON
bakes those into the spec itself: by the time your program reads the config,
fallback files are merged and `${VAR}` references resolved into a single composed
object. Conditional branching from "is this value present in this layer?"
disappears at the format boundary.

On top of that, HOCON combines the readability of YAML with the structure of JSON —
making it a strong fit for anything beyond flat key-value config.

## Features

- Full HOCON parsing: objects, arrays, scalars, substitutions (`${path}`, `${?path}`)
- Self-referential substitutions (`path = ${path}:/extra`) with cycle detection
- Deep-merge for duplicate keys (last definition wins)
- `+=` append operator
- `include` directives: `include "file.conf"`, `include file("...")`,
  `include package("id", "file")`, and `include required(...)` wrappers
- Triple-quoted strings (`"""..."""`)
- Duration, period, and byte-size parsing (`get_duration()`, `get_period()`,
  `get_bytes()`)
- Environment-variable substitution (`${HOME}`) and env-var list expansion
  (`${NAME[]}` → `NAME_0`, `NAME_1`, …)
- Numerically-keyed object → array conversion
- `.properties` includes
- Deferred resolution lifecycle: `parse(..., resolve_substitutions=False)` →
  `with_fallback` → `resolve()` (Lightbend `parseString` / `withFallback` /
  `resolve()` API)
- Zero runtime dependencies (pure stdlib), fully typed (`py.typed`)

## API Reference

### Parse functions

```python
import hocon

hocon.parse(text, *, base_dir=None, env=None, read_file=None,
            resolve_substitutions=True, origin_description=None,
            resolve_from=None, package_resolver=None) -> hocon.Config
hocon.parse_string(text, **opts)   # alias of parse()
hocon.parse_file(path, **opts)     # resolves includes relative to the file's dir
```

Parse options (keyword-only):

| Option | Type | Description |
|--------|------|-------------|
| `base_dir` | `str` | Base directory for `include` resolution |
| `env` | `dict[str, str]` | Environment variables for substitution (default: `os.environ`) |
| `read_file` | `(str) -> str` | Custom file reader |
| `resolve_substitutions` | `bool` | Resolve substitutions during parse (default `True`); `False` returns a deferred `Config` |
| `origin_description` | `str` | Source name surfaced in error messages |
| `resolve_from` / `package_resolver` | — | Control `include package(...)` resolution |

### Config methods

All typed getters raise on failure; paths use dot notation, with quoted
segments for keys that contain dots (`config.get_string('"a.b".c')`).

| Method | Returns | Raises if |
|--------|---------|-----------|
| `get(path)` | value or `None` | — |
| `get_string(path)` | `str` | missing, wrong type, or unresolved |
| `get_number(path)` | `int \| float` | missing, not numeric, or unresolved |
| `get_int(path)` | `int` | missing, not numeric, or unresolved |
| `get_float(path)` | `float` | missing, not numeric, or unresolved |
| `get_boolean(path)` | `bool` | missing, wrong type, or unresolved |
| `get_duration(path, unit=None)` | `float` | missing, wrong type, or invalid duration |
| `get_bytes(path, unit=None)` | `float` | missing, wrong type, or invalid byte size |
| `get_period(path)` | `Period` | missing, wrong type, or invalid period |
| `get_config(path)` | `Config` | missing, not an object, or unresolved |
| `get_list(path)` | `list` | missing, not an array, or unresolved |
| `get_value(path)` | `HoconValue \| None` | subtree unresolved |
| `has(path)` | `bool` | — |
| `keys()` | `list[str]` | — |
| `with_fallback(fallback)` | `Config` | — |
| `resolve(*, allow_unresolved=False, use_system_environment=True)` | `Config` | unresolvable substitution (unless `allow_unresolved`) |
| `resolve_with(source, *, ...)` | `Config` | source unresolved, or unresolvable substitution |
| `is_resolved()` | `bool` | — |
| `to_object()` | `dict / list / scalar` | — |

`get_boolean` also accepts `yes`/`no` and `on`/`off`. `get_number` returns an
`int` for integral lexemes and a `float` otherwise.

### Value factories

```python
from hocon import from_map, empty

cfg = from_map({"server": {"host": "localhost", "port": 8080}})
cfg.get_int("server.port")   # 8080

empty()                      # a resolved Config with no keys
```

Keys in `from_map` are treated as plain keys, **not** path expressions —
`{"a.b": 1}` produces a top-level key literally named `a.b`.

### Structural access

Beyond the decoded `to_object()` / `get()`, `get_value()` exposes the raw value
tree for introspection via standalone accessors:

```python
from hocon import as_string, as_object, is_scalar, is_null

node = cfg.get_value("server")      # HoconValue
as_object(node)                     # dict[str, HoconValue] | None
is_scalar(cfg.get_value("server.port"))   # True
```

### Deferred resolution

Separate parse, fallback-layering, and resolve for runtime config injection:

```python
import hocon
from hocon import from_map

# 1. Parse without resolving — substitutions deferred
cfg = hocon.parse(
    'version = ${shortversion}-${CI_RUN_NUMBER}\n'
    'variables { shortversion = "1.2.3" }',
    resolve_substitutions=False,
)
cfg.is_resolved()   # False — ${CI_RUN_NUMBER} still pending

# 2. Layer runtime fallbacks
runtime = from_map({"CI_RUN_NUMBER": "42"})
variables = cfg.get_config("variables")
merged = cfg.with_fallback(runtime).with_fallback(variables)

# 3. Resolve the full fallback stack
resolved = merged.resolve(use_system_environment=False)
resolved.get_string("version")   # "1.2.3-42"
```

`resolve_with` resolves the receiver using a source for lookup **without** merging
the source's keys into the result:

```python
receiver = hocon.parse("r = ${key}", resolve_substitutions=False)
source = from_map({"key": "val"})
result = receiver.resolve_with(source)
result.has("key")        # False — source keys excluded
result.get_string("r")   # "val"
```

## Error Types

```python
from hocon import (
    ParseError,          # lexing/parsing failure: .line, .col, .file
    ResolveError,        # substitution/include failure: .path, .line, .col, .file
    PackageLookupError,  # include package(...) not found (subclass of ResolveError)
    ConfigError,         # wrong type or missing path: .path
    NotResolvedError,    # getter on an unresolved path (subclass of ConfigError)
)
```

| Type | When |
|------|------|
| `ParseError` | Syntax errors during lexing/parsing (includes line and column) |
| `ResolveError` | Substitution failures, cyclic references, missing required includes |
| `PackageLookupError` | `include package(...)` could not be located |
| `ConfigError` | Missing keys or type mismatches during value access; also raised by `parse`/`parse_file` for an array-root document (S3.5) |
| `NotResolvedError` | Getter called on a path still holding an unresolved substitution |

## HOCON Examples

```hocon
# Comments with # or //
database {
  host = "db.example.com"
  port = 5432
  url  = "jdbc:"${database.host}":"${database.port}
}

# Duplicate keys deep-merge (last wins for scalars)
server { host = localhost }
server { port = 8080 }      // result: { host: "localhost", port: 8080 }

# Self-referential append
path = "/usr/bin"
path = ${path}":/usr/local/bin"

# += shorthand
items = [1]
items += 2
items += 3   // [1, 2, 3]

# Include
include "defaults.conf"
include file("overrides.conf")

# Triple-quoted multiline strings
description = """
  This is a
  multiline string.
"""

# Unquoted strings
path = /usr/local/bin
```

### Durations, Periods, and Byte Sizes

```python
from hocon import Period

c = hocon.parse("""
    timeout   = "30s"
    cache-ttl = "5m"
    retention = "2w"
    max-size  = "512MiB"
""")

c.get_duration("timeout")         # 30000.0 (ms)
c.get_duration("timeout", "s")    # 30.0
c.get_duration("cache-ttl", "m")  # 5.0

c.get_period("retention")         # Period(years=0, months=0, days=14)

c.get_bytes("max-size")           # 536870912 (bytes)
c.get_bytes("max-size", "MiB")    # 512.0
```

Supported duration units: `ns`, `us`, `ms`, `s`, `m`, `h`, `d` (and long forms
like `seconds`, `minutes`). Duration unit names are **case-sensitive** and must be
lowercase (HOCON spec S19.8). Byte units are more case-tolerant: the canonical
forms plus lowercase aliases (`kb`, `kib`, …), any-case long forms (`megabytes`),
and single-letter powers-of-two in both cases (`K`/`k`, per Lightbend, S21.4).
Supported byte units: `B`, `KB`/`KiB`, `MB`/`MiB`, `GB`/`GiB`, `TB`/`TiB`.

`get_period` (spec S20.1–S20.4) returns a `Period(years, months, days)` value —
a frozen dataclass mirroring rs.hocon's `Period` struct. Supported units:
`d`/`day`/`days` (default for bare numbers), `w`/`week`/`weeks` (folded into
days), `m`/`mo`/`month`/`months`, `y`/`year`/`years` — lowercase only, like
durations. Periods are **integer-only** (Lightbend `Integer.parseInt`):
fractional values such as `"7.5"` raise `ConfigError`, unlike `get_duration` /
`get_bytes` which accept them. Negative periods are permitted.

## Performance

Indicative timings from `benchmarks/bench.py` (each iteration parses and does a
`get_string` lookup). Run `make bench` to reproduce on your machine.

| Scenario | ops/sec | Time per op |
|---|---|---|
| Small config (10 keys) | ~5,700 | ~175 µs |
| Medium config (100 keys) | ~600 | ~1.7 ms |
| Large config (1,000 keys) | ~57 | ~17.7 ms |
| 10 substitutions | ~3,700 | ~270 µs |
| 50 substitutions | ~800 | ~1.2 ms |
| 100 substitutions | ~400 | ~2.5 ms |
| Depth 5 nesting | ~8,500 | ~117 µs |
| Depth 10 nesting | ~4,600 | ~220 µs |
| Depth 20 nesting | ~2,000 | ~500 µs |

As a pure-Python parser, py.hocon is roughly 30–40× slower than the compiled /
V8-backed siblings (go.hocon, rs.hocon, ts.hocon). For typical application configs
(loaded once at startup), the cost is negligible — even a 1,000-key config parses
in under 20 ms. If you parse very large configs on a hot path, cache the resulting
`Config`.

## Spec Compliance

Conformance against the [Lightbend HOCON specification](https://github.com/lightbend/config/blob/main/HOCON.md)
is tracked at item granularity in [`docs/spec-compliance.md`](docs/spec-compliance.md);
see [`xx.hocon/docs/compliance-matrix.md`](https://github.com/o3co/xx.hocon/blob/main/docs/compliance-matrix.md)
for live cross-impl values.

| Corpus | py.hocon | go.hocon / rs.hocon (reference) |
|---|---:|---:|
| Spec corpus (134) | **134 (100.0%)** | 134 (100.0%) |
| Lightbend suite (16) | **14/16** | 14/16 |

At parity with the reference sibling implementations. The 2 held-out Lightbend
fixtures reference JVM system properties (`${?java.version}` / `${?user.home}`),
which resolve only inside a JVM — every non-JVM parser caps at 14/16.

## Related Projects

| Project | Language | Registry | Description |
|---------|----------|----------|-------------|
| [ts.hocon](https://github.com/o3co/ts.hocon) | TypeScript | [npm](https://www.npmjs.com/package/@o3co/ts.hocon) | HOCON parser for TypeScript/Node.js |
| [go.hocon](https://github.com/o3co/go.hocon) | Go | [pkg.go.dev](https://pkg.go.dev/github.com/o3co/go.hocon) | HOCON parser for Go |
| [rs.hocon](https://github.com/o3co/rs.hocon) | Rust | [crates.io](https://crates.io/crates/hocon-parser) | HOCON parser for Rust |
| [hocon2](https://github.com/o3co/hocon2) | Go | [pkg.go.dev](https://pkg.go.dev/github.com/o3co/hocon2) | HOCON → JSON/YAML/TOML/Properties CLI |

All four parser implementations are tracked against the same Lightbend HOCON spec —
see the [cross-impl roll-up](https://github.com/o3co/xx.hocon/blob/main/docs/compliance-matrix.md)
for per-impl conformance rates.

## Best Practices

### Config Structure

- **Split by domain**: separate configuration into logical units (`database.conf`,
  `server.conf`, `logging.conf`)
- **Use `include` for composition**: compose a full config from domain-specific files
- **Avoid logic in config**: HOCON is for declarative data, not conditionals or computation

### Environment Variables

- **Minimize `${ENV}` usage**: prefer `${?ENV}` (optional) with sensible defaults
  defined in the config itself
- **Never require env vars for local development**: defaults should work out of the box
- **Document required env vars**: list them in your project's README or a `.env.example`

### Dev / Prod Separation

```text
config/
├── application.conf    # shared defaults
├── dev.conf            # include "application.conf" + dev overrides
└── prod.conf           # include "application.conf" + prod overrides
```

### Validation

Validate config at application startup, not at point-of-use. Load into a typed
structure (dataclass, `attrs`, or Pydantic) so errors surface early:

```python
from dataclasses import dataclass
import hocon

@dataclass
class ServerConfig:
    host: str
    port: int

cfg = hocon.parse_file("application.conf")
server = ServerConfig(
    host=cfg.get_string("server.host"),
    port=cfg.get_int("server.port"),
)   # fails fast on startup if a field is missing or the wrong type
```

## Known Limitations

- **`include url(...)`** is not supported. Fetching remote configuration is outside
  the scope of this parser — fetch the content with your HTTP client, then pass it
  to `parse()`.
- **`include classpath(...)`** is not supported. This is a JVM-specific include form
  with no equivalent outside Java runtimes.
- **`include package(...)`** resolves via a filesystem convention (search
  `resolve_from` / `base_dir` / CWD for `<base>/<id>/<file>`), not a Python
  package-manager lookup. Supply a custom `package_resolver` for other schemes.
- **No watch/reload** — the library parses config at load time. For live-reloading,
  re-call `parse()` / `parse_file()` on change.
- **No streaming parser** — the entire input is loaded into memory. For untrusted
  input, validate size before parsing (see Security Considerations).
- **`.properties` include** — supports basic `key=value` / `key:value` syntax. Does
  not support multiline values (backslash continuation), Unicode escapes, or key
  escaping from the full Java `.properties` specification.

## Security Considerations

When parsing untrusted HOCON input, be aware of:

- **Path traversal in includes:** `include "../../../etc/passwd"` resolves relative
  to `base_dir`. Supply a custom `read_file` that validates paths if parsing
  untrusted input.
- **Input size:** the parser has no built-in input size limit. For untrusted input,
  validate size before calling `parse()`.
- **Include depth:** limited to 50 levels to prevent stack overflow from deep
  include chains.

## Development

```sh
make setup      # create .venv and install dev dependencies (needs python3.11+)
make check      # ruff + mypy --strict + pytest
make bench      # run the micro-benchmarks
make testdata   # sync the conformance corpus from o3co/xx.hocon
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow.

## License

Apache License 2.0 — see [LICENSE](LICENSE).

Copyright 2026 1o1 Co. Ltd.

## Attribution

Designed and built end-to-end with [Claude Code](https://claude.ai/claude-code),
ported from [ts.hocon](https://github.com/o3co/ts.hocon).
