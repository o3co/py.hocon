# py.hocon — HOCON Parser for Python

[![PyPI](https://img.shields.io/pypi/v/hocon-parser.svg)](https://pypi.org/project/hocon-parser/)
[![Python](https://img.shields.io/pypi/pyversions/hocon-parser.svg)](https://pypi.org/project/hocon-parser/)
[![CI](https://github.com/o3co/py.hocon/actions/workflows/test.yml/badge.svg)](https://github.com/o3co/py.hocon/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/o3co/py.hocon/branch/main/graph/badge.svg)](https://codecov.io/gh/o3co/py.hocon)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Spec conformance](https://img.shields.io/badge/spec%20corpus-100%25-brightgreen.svg)](docs/spec-compliance.md)

A [Lightbend HOCON specification](https://github.com/lightbend/config/blob/main/HOCON.md)
parser for Python. Hand-written lexer, recursive-descent parser, and a typed `Config`
API. Zero runtime dependencies (pure stdlib), Python 3.11+, fully typed (`py.typed`).
See [Spec Compliance](#spec-compliance) for the current conformance rate.

> **Implemented by [Claude](https://claude.ai/) (Anthropic)** — designed and built
> end-to-end with Claude Code, ported from the sibling
> [ts.hocon](https://github.com/o3co/ts.hocon) implementation.

**Docs:** [o3co.github.io/hocon](https://o3co.github.io/hocon/) — the cross-language hub for all four implementations, the hocon2 CLI and the shared conformance corpus.

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

# Config is a Mapping — dict-style access works throughout
cfg["server.host"]              # "localhost"
cfg["database"]                 # {"url": ..., "pool-size": 10}
cfg.get("server.timeout", 30)   # 30 (default for a missing path)
"server.port" in cfg            # True
dict(cfg)                       # plain nested dict of the whole config
```

Or decode straight into your own types:

```python
from dataclasses import dataclass

@dataclass
class Database:
    url: str
    pool_size: int   # ← matches `pool-size`

db = cfg.decode(Database, path="database")
db.pool_size                    # 10, statically typed
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

## Configuration that stays inside its module

In a large codebase, configuration tends to leak: one big file that every team edits, defaults copied into each service, and modules that read each other's keys. HOCON lets each module own its configuration the way it owns its code.

- **Each module owns a namespace and ships its own defaults.** The `auth` module keeps `auth { … }` next to its code, with every default filled in. The application never copies those defaults; it brings them in with one `include`.
- **The application overrides only what differs.** Later layers deep-merge over earlier ones, so the application states two keys, not the whole block.
- **Each module reads only its own subtree, through its own schema.** The module asks for `auth` and validates it against the schema it defines. The shape of that section is the module's contract; nothing else in the file is visible to it.
- **Wiring between modules lives in the application.** The module only declares the keys it reads (`auth.db`) and leaves them without a default when the application must supply them. The application connects them to shared values (`auth.db = ${shared.db}`). Modules never reference each other or the application's keys, so dependencies run one way.

```hocon
# auth/reference.conf: shipped inside the auth package, owned by the auth team
auth {
  session { lifetime = 30m, max-body = 64KiB }
  # db: no default; the application supplies auth.db
}
```

```hocon
# application.conf: owned by the application
include package("github.com/acme/auth", "reference.conf")

shared.db { host = db.internal, port = 5432 }
auth.db = ${shared.db}       # wiring lives in the application
auth.session.lifetime = 2h   # override what differs; the rest stays the module's default
```

```python
# inside the auth module
from dataclasses import dataclass
from typing import Annotated

import hocon


@dataclass
class Session:
    lifetime: Annotated[int, hocon.Duration("s")]  # "2h" → 7200
    max_body: Annotated[int, hocon.Bytes()]        # "64KiB" → 65536


@dataclass
class Db:
    host: str
    port: int


@dataclass
class Auth:
    session: Session
    db: Db  # no default: the application must supply auth.db


def load_auth(config: hocon.Config) -> Auth:
    return config.decode(Auth, "auth")  # reads only its own subtree
```

The dataclass fields match the kebab-case keys (`max_body` reads `max-body`), and the unit markers read `2h` and `64KiB` with the getters' rules. If the application does not supply `auth.db`, decoding fails with `ConfigError: missing required field at auth.db`.

`include package(...)` is not part of HOCON.md: it is a convention shared by the o3co implementations ([E11](https://github.com/o3co/xx.hocon/blob/main/docs/extra-spec-conventions.md#e11)), a non-JVM counterpart to `include classpath(...)`. It is how a module publishes its defaults without the application knowing where its files live. py.hocon finds a package by a filesystem convention, `<base>/<id>/<file>`, where `<base>` is the first that applies of `resolve_from` (one directory or a list), `base_dir`, the including file's directory, and the working directory; or it uses your own `package_resolver` (see [Parse functions](#parse-functions) and [Known Limitations](#known-limitations)). On the JVM, Lightbend's `reference.conf` convention plays the same role.

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
- `Config` is a `collections.abc.Mapping`: `cfg[path]`, `path in cfg`,
  `cfg.get(path, default)`, iteration, `len`, `dict(cfg)`, `**cfg`
- Typed decoding: `cfg.decode(MyDataclass)` — recursive dataclass
  construction (kebab-case/camelCase key matching, defaults, `Optional`,
  `list[T]` / `dict[str, T]`, `timedelta` durations, `Enum`, byte sizes and
  durations via `Annotated[int, hocon.Bytes()]` markers) and Pydantic v2
  delegation via `model_validate`
- HOCON emitter: `cfg.render_hocon()` renders a resolved config back to
  HOCON text with a round-trip guarantee (parsing the output reproduces the
  value tree)
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
| `get(path, default=None)` | value or `default` | unresolved (`NotResolvedError`) |
| `config[path]` | value | `KeyError` when missing, `NotResolvedError` when unresolved |
| `get_string(path)` | `str` | missing, wrong type, or unresolved |
| `get_number(path)` | `int \| float` | missing, not numeric, or unresolved |
| `get_int(path)` | `int` | missing, not numeric, or unresolved |
| `get_float(path)` | `float` | missing, not numeric, or unresolved |
| `get_boolean(path)` | `bool` | missing, wrong type, or unresolved |
| `get_duration(path, unit=None)` | `float` | missing, wrong type, invalid duration, or past the float range (E21) |
| `get_bytes(path, unit=None)` | `float` (`int` in bytes) | missing, wrong type, invalid or negative byte size, or 2^53 bytes or more |
| `get_period(path)` | `Period` | missing, wrong type, or invalid period |
| `get_config(path)` | `Config` | missing, not an object, or unresolved |
| `get_list(path)` | `list` | missing, not an array, or unresolved |
| `get_value(path)` | `HoconValue \| None` | subtree unresolved |
| `decode(cls, path=None)` | instance of `cls` | missing path/field, type mismatch, or unresolved |
| `has(path)` | `bool` | — |
| `keys()` | `list[str]` | — |
| `with_fallback(fallback)` | `Config` | — |
| `resolve(*, allow_unresolved=False, use_system_environment=True)` | `Config` | unresolvable substitution (unless `allow_unresolved`) |
| `resolve_with(source, *, ...)` | `Config` | source unresolved, or unresolvable substitution |
| `is_resolved()` | `bool` | — |
| `to_object()` | `dict / list / scalar` | any part unresolved |
| `render_hocon()` | `str` (HOCON text) | unresolved |

`get_boolean` also accepts `yes`/`no` and `on`/`off`. `get_number` returns an
`int` for integral lexemes and a `float` otherwise.

`Config` implements `collections.abc.Mapping` over its top-level keys:
iteration, `len(cfg)`, `dict(cfg)`, `**cfg`, `items()` / `values()` all work.
`cfg[path]` and `path in cfg` additionally accept dotted path expressions
(`cfg["server.host"]`); a literal top-level key containing a dot wins over
path traversal, so every key yielded by iteration can be indexed back.
Mapping semantics follow `dict`: equality is value-based (a `Config` compares
equal to an equivalent `dict`), an empty config is falsy, and `Config` is
unhashable. An explicit HOCON `null` is a *present* value — `cfg.get(path,
default)` returns `None` for it, and `path in cfg` is `True`.

On a config that is not fully resolved, the keys are all there and only the
values wait: iteration, `len` and `keys()` include unresolved keys and
`path in cfg` is `True` for them, while reading an unresolved value
(`cfg[path]`, `get`, `items()`, `dict(cfg)`, `==`, `to_object()`) raises
`NotResolvedError`. `has(path)` never raises: it is `True` for a path whose
value is unresolved (the cross-implementation rule; Lightbend's `hasPath`
throws instead). `in` raises for a path below an unresolved value, which
cannot be answered yet.

### Typed decoding

`cfg.decode(cls, path=None)` builds an instance of `cls` from the config (or
from the value at `path`), mirroring go.hocon's `Unmarshal` / `UnmarshalPath`:

- **Dataclasses** are constructed recursively from their type hints. A
  `field(metadata={"hocon": key})` alias, when present, is the *only* key
  consulted (like a go struct tag or serde `rename` — no fallback to the
  field name); otherwise the exact name, kebab-case (`pool_size` →
  `pool-size`), and camelCase (`poolSize`) are tried in order, first match
  wins. `metadata={"hocon": "-"}` skips a field (it must have a default).
  A field whose key is absent uses its dataclass default; without a default
  it is an error. Extra config keys are ignored.
- **Pydantic v2 models** (any class with `model_validate` — pydantic is never
  imported) receive the decoded plain object wholesale and validate it
  themselves.
- **Supported hints**: nested dataclasses, `list[T]` (S15 numeric-keyed
  objects included), `dict[str, T]`, `Optional[T]` / `T | None`, `Any`,
  `str` / `bool` / `int` / `float`, `Enum` (by value, then by name),
  `datetime.timedelta` (HOCON durations, e.g. `"10s"`), `Period`, and
  `Config` (keeps a subtree dynamic). `cls` itself may be any supported
  expression, e.g. `cfg.decode(list[Server], path="servers")`.
- **Coercions** follow the typed getters: `bool` accepts `yes`/`on`,
  `str` accepts any non-null scalar's raw text, and `int` accepts
  whole-number floats with wholeness derived from the decimal text
  (`3.0` → `3`, `2.5` → error). HOCON `null` only decodes into an
  optional field.

#### Unit values: `hocon.Bytes` / `hocon.Duration`

Annotate a field with a unit marker to read a HOCON byte size or duration with
the same rules as `get_bytes` / `get_duration` (units are case-sensitive, a
bare number is bytes / ms, byte sizes are non-negative). The marker owns only
the unit syntax; constraints stay in the type:

```python
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

import hocon
from pydantic import BaseModel, Field

@dataclass
class Server:
    max_body: Annotated[int, hocon.Bytes()]          # "64KiB" → 65536
    cache: Annotated[float, hocon.Bytes("MiB")]      # "512KiB" → 0.5
    timeout: Annotated[timedelta, hocon.Duration()]  # "30m" → 0:30:00
    retry_s: Annotated[float, hocon.Duration("s")]   # "1.5m" → 90.0

class Limits(BaseModel):  # the same markers work in Pydantic v2 models
    max_body: Annotated[int, hocon.Bytes(), Field(gt=1024)]
```

- `Bytes(unit="B")` annotates `int` or `float`; `Duration(unit="ms")`
  annotates `int`, `float`, or `timedelta`. `unit` is an output-unit token
  (`KB`, not `kB`; see [Durations, Periods, and Byte
  Sizes](#durations-periods-and-byte-sizes)). An `int` field rejects a
  fractional result (`"512B"` in `KiB`). `Optional`, `list[...]` and
  `dict[str, ...]` positions work.
- Errors carry the key path (`invalid byte size at server.max-body: '64KB'`);
  in a Pydantic model they are validation errors at the field's location.
- A marker acts only on the values `Config.decode` reads from a config (for
  Pydantic, through a validation context on decode's `model_validate` call).
  Constructing a model, a `default_factory`, `model_validate(model.model_dump())`
  and JSON round-trips see the field as its plain type, so values are not
  converted twice (`Limits(max_body=65536)` stays `65536`). With
  `validate_default=True` a default is validated as part of decode, so write it
  in HOCON form (`"1.5m"`). A model that overrides `__init__` does not
  receive the validation context (a Pydantic limitation), so markers inside it
  do not act — use a `model_validator` instead of overriding `__init__`.
- Key matching by kebab-case / camelCase is a dataclass feature. A Pydantic
  model receives the keys as written, so a HOCON key `max-body` needs a field
  alias (`Field(alias="max-body")`, or an `alias_generator` on the model), or a
  config key that already matches the field name (`max_body`); otherwise
  Pydantic reports the field as missing.
- Pydantic models receive plain values, so there a number is read through its
  value rather than its source text: a bare number in exponent form (`1e3`)
  reads as `1000`, while the getters and dataclass decoding reject it. Values
  written with a unit read the same either way.
- A plain `timedelta` field in a Pydantic model keeps Pydantic's own parsing
  (ISO 8601, bare numbers as seconds); use `Annotated[timedelta,
  hocon.Duration()]` for HOCON durations.

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

### Rendering HOCON

`render_hocon()` emits a resolved config back as HOCON text. The guarantee is
the round trip, not the byte format: parsing the output reproduces the value
tree exactly, so a scalar is quoted whenever leaving it bare would re-parse as
a different type (`{"port": "8080"}` renders as `port = "8080"`, keeping it a
string). Root fields are braceless, nested objects render as `key { … }`, and
an unresolved config raises `NotResolvedError`:

```python
from hocon import from_map

cfg = from_map({"server": {"host": "localhost", "port": 8080}})
print(cfg.render_hocon())
# server {
#   host = localhost
#   port = 8080
# }
```

Substitutions and comments are not represented — a resolved value tree does
not carry them. Same contract as go.hocon `RenderHOCON`, ts.hocon
`renderHocon()`, and rs.hocon `render_hocon()`.

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
lowercase (HOCON spec S19.8). Byte units follow Lightbend's case-sensitive table:
`B`/`b`, `kB` (powers of ten; `KB` and `kb` are errors), `KiB`/`Ki` (powers of
two), `MB`/`MiB`, `GB`/`GiB`, `TB`/`TiB` and up to `YB`/`YiB`, lowercase long
forms (`kilobytes`, `mebibytes`, …), and single-letter powers of two in both
cases (`K`/`k`, S21.4). Arithmetic is exact decimal (E20): `1.001s` is exactly
`1001` ms, and a fractional byte size truncates toward zero after the exact
product (`1.0009kB` is `1000` bytes). A duration past the float range is an
error (E21), never `inf`. A byte size must stay below 2^53 bytes (about 9 PB):
`8PB` reads, `10PB` and `1YB` raise `ConfigError`, so the largest units only
fit as fractions (`0.000000001YiB`).

**Output units are a separate, short set of tokens.** The `unit` argument of
`get_duration` / `get_bytes` and of the `hocon.Duration` / `hocon.Bytes`
markers names the unit of the *result*, and takes only these tokens:

| Result of | `unit` tokens | Default |
|---|---|---|
| `get_duration`, `hocon.Duration` | `ns`, `us`, `ms`, `s`, `m`, `h`, `d` | `ms` |
| `get_bytes`, `hocon.Bytes` | `B`, `KB`, `KiB`, `MB`, `MiB`, `GB`, `GiB`, `TB`, `TiB` | `B` |

They are not the config spellings: `KB` here means 1000 bytes, which config
text spells `kB` (where `KB` is an error), and long forms such as `seconds` are
not accepted. A marker rejects an unknown token when it is constructed
(`hocon.Bytes("kB")` raises `ValueError`); a getter reports it as an invalid
value (`get_bytes("v", "kB")` raises `invalid byte size at v`), so check the
token first when a value that looks right is rejected.

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

| Corpus (py.hocon's own harness, xx.hocon main as of 2026-10-16) | py.hocon |
|---|---:|
| Spec corpus | **154/154 (100.0%)** |
| Lightbend fixtures with expected output | **12/14** |

The 2 held-out Lightbend fixtures (`test01`, `test03`) reference JVM system
properties (`${?java.version}` / `${?user.home}`), which resolve only inside a
JVM, so every non-JVM parser holds these two out. Run `make testdata && make test` to
re-measure against the current corpus. The cross-library snapshot in
[xx.hocon `docs/ecosystem-conformance.md`](https://github.com/o3co/xx.hocon/blob/main/docs/ecosystem-conformance.md)
(measured 2026-07-15, with that day's corpus of 134 and its own count of the
Lightbend suite, 14/16) shows py.hocon at parity with go.hocon and rs.hocon.

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
- **Bulk-mounting a namespace**: `hocon.adapters.env` maps a whole prefix into a
  subtree (`APP_DB__HOST` → `db.host`); `__` is the only hierarchy boundary —
  see [Format adapters](#format-adapters)

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
server = cfg.decode(ServerConfig, path="server")
# fails fast on startup if a field is missing or the wrong type
```

## Format adapters

Config files that belong to *other* programs can be mounted as HOCON, so a
`${...}` in your document can reach into them:

```python
import hocon
from hocon.adapters import env

base = env.load(prefix="APP_")               # APP_DB__HOST -> db.host
cfg = hocon.parse(src, resolve_substitutions=False)
merged = cfg.with_fallback(base).resolve()
```

Deferring resolution matters: the plain `parse` resolves as it goes, so a
`${...}` aimed at the fallback would fail before the fallback is attached.

| Module | Extra needed | Notes |
| --- | --- | --- |
| `hocon.adapters.properties` | — | `java.util.Properties`, sharing the `include` syntax layer |
| `hocon.adapters.env` | — | Bulk-mounts a prefixed namespace; also reads `.env` |
| `hocon.adapters.jsonc` | — | JSON with comments and trailing commas |
| `hocon.adapters.json5` | — | JSON5 1.0.0, hand-rolled scanner |
| `hocon.adapters.toml` | — | via `tomllib`, which Python 3.11 ships |
| `hocon.adapters.yaml` | `pip install hocon-parser[yaml]` | via `ruamel.yaml` |

Only YAML needs a dependency; the base install stays pure standard library.
Plain JSON needs no adapter — HOCON is a JSON superset, so `hocon.parse`
accepts it as it stands.

Foreign data stays data: a `${a.b}` in a mounted value is literal text, never a
reference, because the file belongs to a program that never agreed to HOCON's
syntax.

### Mapping rules worth knowing

**env — `__` is the only hierarchy boundary.** A `.` inside a variable name is
key text, not a nesting level, so the two spellings are different paths:

```python
cfg = env.load("APP_", {"APP_FOO__BAR": "nested", "APP_FOO.BAR": "literal"})
cfg.get_string("foo.bar")      # "nested"  — from APP_FOO__BAR
cfg.get_string('"foo.bar"')    # "literal" — from APP_FOO.BAR, one quoted key
```

Because they are different paths they never collide. A genuine collision
(`APP_A__B` and `APP_a__b`, which lowercase onto the same path) is an error:
the environment has no order to break the tie with. A `.env` file does have a
definite order, so there the last line simply wins. Segments are lowercased
**ASCII-only** — `A`–`Z` and nothing else, so the mapping is identical in all
four implementations rather than each language's Unicode rules — and a single
`_` stays inside the segment (`APP_DB__MAX_CONN` → `db.max_conn`).

**env — an entry that is not valid UTF-8 never becomes a value.** Python
decodes the environment with `surrogateescape`, so undecodable bytes survive as
lone surrogates that raise only when something later encodes them. What happens
to such an entry depends on whether you asked for it: `${VAR}` and `${?VAR}`
treat it as **absent** (the optional form falls through to its default, the
required form raises the usual unresolved error), while `env.load(prefix=...)`
**errors** if the entry is inside the prefix you mounted — a mount that dropped
it silently would look complete while the operator's setting was missing.
Entries outside the prefix are never inspected, so an undecodable variable
elsewhere cannot break your mount.

**jsonc — comments separate tokens.** A comment is removed by replacing it with
whitespace, so `{"a": 1/*x*/2}` is a syntax error rather than `{"a": 12}`. A
`//` comment ends at LF or CR, matching the dialect VS Code reads.

**json5 — the reference implementation owns the dialect.** The grammar is JSON5
1.0.0 as the `json5` npm package reads it, so U+2028/U+2029 *end* a `//`
comment here (deliberately unlike jsonc, whose owner runs comments through
them). Where the mapping spec is stricter, the spec wins: `Infinity`/`NaN` in
any spelling are errors, hex and decimal integers must fit in int64, an
unpaired `\uXXXX` surrogate is an error, and duplicate keys follow HOCON
semantics — objects merge, otherwise last-wins.

**properties — every key is an ordinary key.** `__proto__`, `constructor` and
`prototype` are kept with their values like any other key; a Python `dict` has
no prototype to pollute, so nothing is filtered out.

**all formats — integers are int64, and a BOM is not key text.** An ingested
integer outside `[-2^63, 2^63-1]` is an error rather than a value the other
implementations could not hold, and a leading UTF-8 BOM is stripped by every
`parse_file` helper instead of ending up inside the first key.

For YAML, scalar resolution belongs to the library, not to this package.
`ruamel.yaml` reads YAML 1.2, so `no` stays the string `"no"`; PyYAML is YAML
1.1 and would resolve it to `False` — the Norway problem — which is why it is
not the default. A caller who wants a different library decodes the text
themselves and hands the tree over:

```python
import yaml as pyyaml
from hocon.adapters.yaml import from_value

cfg = from_value(pyyaml.safe_load(src), "their-file.yml")
```

## Known Limitations

- **`include url(...)`** is not supported. Fetching remote configuration is outside
  the scope of this parser — fetch the content with your HTTP client, then pass it
  to `parse()`.
- **`include classpath(...)`** is not supported. This is a JVM-specific include form
  with no equivalent outside Java runtimes.
- **`include package(...)`** resolves via a filesystem convention
  (`<base>/<id>/<file>`, where `<base>` is the first that applies of
  `resolve_from`, `base_dir`, the including file's directory, and the working
  directory), not a Python package-manager lookup. Supply a custom `package_resolver` for other schemes.
- **No watch/reload** — the library parses config at load time. For live-reloading,
  re-call `parse()` / `parse_file()` on change.
- **No streaming parser** — the entire input is loaded into memory. For untrusted
  input, validate size before parsing (see Security Considerations).

## Security Considerations

When parsing untrusted HOCON input, be aware of:

- **Path traversal in includes:** `include "../../../etc/passwd"` resolves relative
  to `base_dir`. Supply a custom `read_file` that validates paths if parsing
  untrusted input.
- **Input size:** the parser has no built-in input size limit. For untrusted input,
  validate size before calling `parse()`.
- **Include depth:** limited to 50 levels to prevent stack overflow from deep
  include chains.
- **Mapped path depth:** an environment variable's `__` segments and a
  Properties file's dotted key are limited to 64 segments. One name produces one
  arbitrarily deep chain, so without the cap 1.5 kB of variable name was enough
  to exhaust the interpreter's stack. rs.hocon caps the same mapping at 64.
- **Document nesting depth:** not capped. A document nested past what the
  interpreter's stack holds fails as `ParseError` or `AdapterError` — never as a
  bare `RecursionError` — but the depth at which that happens depends on how
  deep the calling code already is, so validate size before parsing untrusted
  input (see above) rather than relying on a fixed level.

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
