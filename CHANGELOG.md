# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `Config` now implements `collections.abc.Mapping` over its top-level keys:
  `cfg[path]` (`KeyError` when missing), `path in cfg`, iteration, `len(cfg)`,
  `dict(cfg)`, `**cfg`, and the `items()` / `values()` views. `cfg[path]` and
  `path in cfg` accept dotted path expressions in addition to literal top-level
  keys; a literal key containing a dot wins over path traversal so iteration →
  indexing always round-trips.
- `Config.get(path, default=None)` — the `default` is returned when the path is
  absent. An explicit HOCON `null` is a present value and decodes to `None`
  (it does not fall back to the default), matching `dict.get`.
- `Config.decode(cls, path=None)` — typed decoding into user-defined types,
  mirroring go.hocon `Unmarshal` / `UnmarshalPath`. Dataclasses are built
  recursively from type hints with per-field key matching (an exclusive
  `field(metadata={"hocon": key})` alias, otherwise exact → kebab-case →
  camelCase; `"-"` skips), dataclass defaults for absent keys, an error for an absent
  key without a default, and extra keys ignored. Classes exposing
  `model_validate` (Pydantic v2) receive the decoded plain object wholesale.
  Supported hints: nested dataclasses, `list[T]` (S15 numeric-keyed objects
  included), `dict[str, T]`, `Optional[T]`, `Any`, `str` / `bool` / `int` /
  `float`, `Enum`, `datetime.timedelta` (HOCON durations), `Period`, and
  `Config`. `int` fields accept whole-number floats with wholeness derived
  from the decimal text (xx.hocon#56); HOCON `null` only decodes into
  optional fields (S17.6). Decoding an unresolved subtree raises
  `NotResolvedError`.

### Changed

- As a consequence of the `Mapping` base, `Config` equality is now value-based
  (two configs with equal decoded content compare equal, as does an equivalent
  plain `dict`) instead of identity-based, an empty config is now falsy, and
  `Config` is now unhashable — all matching `dict` semantics.
- `Config.has(path)` (and the new membership/indexing operations) now check the
  literal top-level key before path traversal. This changes behaviour for
  documents with a quoted top-level key containing a dot: given `"a.b" = 1`,
  `has("a.b")` was previously `False` (the argument was interpreted purely as
  a path) and is now `True`; when both the literal key and the equivalent
  nested path are defined, the literal key wins.

## [1.12.0] - 2026-07-31

Cross-impl release, coordinated to land at v1.12.0 across go.hocon / ts.hocon /
rs.hocon / py.hocon so the ecosystem stays on one version line.

**Minor, not patch, and the `.env` changes are BREAKING in both directions**:
the prefix filter now runs before validation (a file that used to fail may now
load), a variable name containing whitespace or `#` is refused (a file that used
to load may now fail), and "whitespace" is now the Unicode `White_Space`
property rather than `str.isspace()` — so a name containing one of
U+001C–U+001F is accepted where it used to raise.

The rest: a lone surrogate in JSONC is refused at parse time instead of failing
later at encode time, deeply nested input raises this library's own error rather
than `RecursionError`, coinciding sibling keys in YAML are an error rather than
last-wins, and `load()` no longer trusts caller-supplied value types.

The F-item spec these errors cite is now public at
[`xx.hocon/docs/format-ingestion-mapping.md`](https://github.com/o3co/xx.hocon/blob/main/docs/format-ingestion-mapping.md);
it previously lived in a private working scope.

The published version comes from the tag; `pyproject.toml` stays at `0.0.0`.

### Changed — `.env`: the prefix filter runs first, and names are validated (F1.7)

**BREAKING both ways**: a line the prefix discards is no longer validated (so a
`.env` that used to fail may now load), and a name containing whitespace or `#`
is now refused (so one that used to load may now fail).

Three things, all pinned by an amended spec F1.7 after cross-checking found all
four implementations behaving identically by accident
([xx.hocon#78](https://github.com/o3co/xx.hocon/issues/78)):

- **The prefix filter moves ahead of validation.** The value was parsed before
  the filter and the path mapped after it, so one check landed on each side —
  `BAD=x # y` failed even when the caller only wanted `APP_*`, while
  `OTHER__=x` was never checked at all. `load`'s contract already said which
  way this goes ("entries outside the prefix are never inspected", the F1.1
  principle); the two functions disagreeing was the actual inconsistency.
- **`export` may be followed by spaces or tabs.** Matching the literal
  `export ` missed a tab, so `export<TAB>FOO=bar` became the variable
  `export<TAB>foo` — a key nothing would ever look up, produced silently. Space
  and tab specifically, matching what this dialect already trims on the value
  side; anything else leaves `export` part of the name, where the rule below
  refuses it. A name that merely begins with `export` is still a name.
- **A name containing whitespace or `#` is an error.** F1.7's rule for values —
  an error naming the fix rather than a guess about the author's intent —
  applies to names too; both characters mean the line was mis-parsed.
  `FOO BAR=baz` and `FOO#x=1` used to become the keys `foo bar` and `foo#x`.
  Deliberately narrower than a POSIX name grammar, which would reject
  `APP_FOO.BAR` — a name F1.2 documents as valid.

### Fixed — `adapters.jsonc`: an unpaired surrogate loaded, then failed later

**BREAKING** (input previously accepted is now refused).

`jsonc.parse(r'{"a":"\\ud800"}')` returned a config holding a lone surrogate. A
Python `str` can hold one, which is why the stdlib decoder handed it back
without complaint — but it cannot be encoded as UTF-8, so the failure arrived
only when something wrote the value out, arbitrarily far from the parse that
admitted it ([xx.hocon#75](https://github.com/o3co/xx.hocon/issues/75)).

Now an `AdapterError` citing spec F3.5, which mirrors F2.8 — the rule the
`.properties` parser has enforced for exactly this reason since S23.6. Valid
surrogate **pairs** still combine into the astral codepoint, and keys are checked
as well as values: a key no lookup can match is worse than a value, not better.

The check runs on the decoded tree rather than on the source escapes, because a
surrogate arrives as a code point whatever spelled it, so one pass catches every
route in.

For the record on the other three: rs.hocon already refused, go.hocon was
silently substituting U+FFFD and now refuses, and **ts.hocon deliberately
accepts** — a JavaScript string is UTF-16 like Java's, the same S1.2.6-class
divergence F2.8 records.

### Changed — `adapters.env`: two small corrections to how a path is rendered in an error

Rendering is pinned as spec F0.10 so go.hocon, rs.hocon and py.hocon produce the
same text for the same key — the cross-language fixtures compare it
([xx.hocon#76](https://github.com/o3co/xx.hocon/issues/76)). This module was
already closest to the pinned rule, `json.dumps(..., ensure_ascii=False)` being
JSON string syntax; two things changed:

- **U+2028 / U+2029 are escaped.** JSON permits them raw and `json.dumps` left
  them raw, but they are line separators to enough log viewers and editors that
  a variable name holding one could break the very message reporting it — which
  is the reason the other control characters are escaped.
- **The bare-segment rule admits `A`–`Z`.** HOCON's own grammar accepts an
  uppercase key unquoted, and the same renderer serves adapters that do not
  case-fold, so quoting `A` was noise. Environment segments are folded before
  they reach here, so nothing changes for `env.load` itself.

The docstring's paste-into-a-getter framing is corrected too: measured, no
implementation's path parser decodes escapes inside a quoted segment, so
`"a\nb"` never addressed the key `a<LF>b`. The guarantee that matters for a
collision message — two different paths never render alike — is now pinned by a
test.

### Fixed — `adapters.yaml`: coinciding sibling keys were last-wins, not an error

**BREAKING** (input previously accepted is now refused; rename one of the two
keys — quoting only helps where it changes the key text, as `0x10` → `'0x10'`
does and `1` → `'1'` does not).

`yaml.parse("1: a\n'1': b\n")` returned `{'1': 'b'}`. The integer key and the
string key are distinct in the decoded dict but `_key_string` maps both to
`'1'`, so writing the second dropped the first's value with nothing to show for
it — the silent loss F5.3 exists to prevent. The same held for `1.0`/`'1.0'`,
`~`/`'null'` and `0x10`/`'16'`, at any nesting depth
([#24](https://github.com/o3co/py.hocon/issues/24)).

The collision is now an `AdapterError` naming both source keys and the path.
The check lives in the converter the nested formats share, but only YAML can
reach it: JSON and TOML keys are strings by construction. Merge keys are
unaffected — `<<: *defaults` bringing in a key the mapping then overrides is
resolved by ruamel before the adapter sees the tree.

Which forms coincide follows from ruamel's scalar resolution and is not aligned
across implementations (F5.1) — `1.0` gives `'1.0'` here and in rs.hocon, `"1"`
in go.hocon and ts.hocon. What is common is that a coincidence errors.

### Fixed — deeply nested input raised `RecursionError`, outside the documented error contract

**BREAKING** for one of the two halves (a mapped path over 64 segments is now
refused; nothing else changes about what is accepted).

`RecursionError` is not a type this library documents, so a caller writing
`except ConfigError` or `except AdapterError` did not catch it and the failure
escaped as an interpreter-level error from the middle of a parse
([#18](https://github.com/o3co/py.hocon/issues/18)). Four entry points reached
it, the cheapest from a **1493-byte variable name**.

Two mechanisms, because two different things can be too deep:

- **A name that maps to a path is capped at 64 segments** — an environment
  variable's `__` segments, a Properties file's dotted key. One name produces
  one arbitrarily deep chain, which is what made the input so small. rs.hocon
  caps the same mapping at the same number, so a name that mounts in one
  implementation mounts in the other. Over the limit is now an `AdapterError`
  (env) or `ParseError` (Properties) naming the depth and the limit.
- **A deeply nested document is not capped** — refusing a 65-level JSON file
  would be a claim about the format rather than about a mapping we invented.
  Instead `RecursionError` is turned into the error type the entry point's
  contract names: `AdapterError` from the adapters (including the `from_value`
  tree entry points, which skip the decoder), `ConfigError` from `from_map`, and
  `ParseError` from `parse`. That matters beyond tidiness, because the depth at
  which CPython gives out depends on how deep the *caller* already is: the same
  document could load from one call site and fail from another. The same guard
  covers a *cyclic* input structure — a dict that contains itself, handed to
  `from_map` — which from inside the handler is indistinguishable from depth, so
  the message names both shapes rather than asserting one.

### Fixed — `adapters.env`: `load()` trusted caller-supplied value types

`env.load("APP_", {"APP_N": 5})` reached the UTF-8 check with an `int` and left
as a bare `TypeError: 'int' object is not iterable`. `os.environ` cannot hold a
non-string, but the `env=` seam is public, and a value that got through would
give the config a type no real mount can produce — passing here and failing
against the real environment. Now an `AdapterError` citing F1.4.
([#19](https://github.com/o3co/py.hocon/issues/19), part 3.)

The other two parts of that issue are unchanged: cross-checking found go.hocon,
ts.hocon and rs.hocon behave identically, so they are a four-way question about
F1.7 rather than a defect here — see the issue for the measurements.

### Fixed — the F-item spec citations pointed at a document readers cannot open

The `hocon.adapters` package doc cited
`docs/specs/format-ingestion-mapping.md`, which is not in this repository — it
lived in a private working scope. The adapters raise errors that name items from
it (`(spec F0.5)`, `(spec F1.6)`), so anyone following a citation reached
nothing. The spec is now published at
[`xx.hocon/docs/format-ingestion-mapping.md`](https://github.com/o3co/xx.hocon/blob/main/docs/format-ingestion-mapping.md) and every citation points
there ([xx.hocon#81](https://github.com/o3co/xx.hocon/issues/81)). Error text is
unchanged; only the pointers move.

### Fixed — `.env`: "whitespace" in a name is the Unicode `White_Space` property (F1.7)

`_check_name` used `str.isspace()`, which is **not** the `White_Space`
property: enumerated over the whole codepoint space, it is `White_Space` plus
U+001C–U+001F (the C0 file / group / record / unit separators). A name
containing one of those four raised here and was an ordinary name elsewhere —
Go's `unicode.IsSpace` and Rust's `char::is_whitespace` are the property
exactly.

Whether a name is refused must not depend on which stdlib helper an
implementation reached for; this is the same argument F1.3 makes for ASCII-only
case folding. The spec now pins the property
([xx.hocon#81](https://github.com/o3co/xx.hocon/issues/81)) and this refuses
strictly less than before: `FOO<US>BAR=baz` now yields the key `foo<US>bar`
instead of raising. Everything `White_Space` covers — including U+0085 (NEL),
where JavaScript is the outlier in the other direction — is unchanged.

The behaviour being corrected has not been released; the name rule itself
arrived in this same unreleased window.

## [1.11.0] - 2026-07-26

### Fixed

- **Environment entries that are not valid UTF-8 leaked into config values
  (F1.9).** Python decodes `os.environ` with `surrogateescape` instead of
  failing, so undecodable bytes survived as lone surrogates: `${?VAR}` returned
  text like `'\udcff\udcfe'` rather than falling through to its default, and
  `env.load(prefix=...)` mounted such entries — undecodable *names* included,
  producing keys no lookup could match. Encoding any of it raises
  `UnicodeEncodeError`, always far from the parse that admitted it. Now, per
  F1.9: a substitution lookup treats an undecodable entry as **absent**
  (`${?VAR}` takes its default, `${VAR}` raises the ordinary unresolved error),
  and a **bulk mount errors** when the entry falls under the mounted prefix.
  The check runs after the prefix filter, so an undecodable variable elsewhere
  in the environment can never break an unrelated mount, and an entry the
  config never mentions is still never fatal. An explicitly supplied `env=`
  mapping is the caller's own data and is passed through untouched.
- **Integers outside the int64 range were accepted (F0.5).** HOCON integers are
  int64, but Python's `int` is unbounded and both `json` and `tomllib` decode
  arbitrary precision, so `jsonc.parse('{"a":9223372036854775808}')` and
  `hocon.from_map({"a": 2**63})` produced a config no sibling implementation
  can hold. `from_map` and the shared adapter leaf rule now raise
  (`ConfigError` / `AdapterError`) outside `[-2^63, 2^63-1]`. The bound itself
  is internal, as it is in ts.hocon — no new public API. **HOCON source text is
  deliberately different and stays as it is**: `a = 9223372036854775808` in a
  `.conf` file remains a double, following Lightbend's `Long`-then-`Double`
  fallback. A foreign format declares its integer type, so a value that cannot
  survive as an int64 is a defect in the mapping; HOCON text carries no such
  declaration (F0.5).
- **A leading UTF-8 BOM became part of the first key (F0.9).** A file saved by
  a Windows editor starts with U+FEFF, and `properties.parse_file` /
  `env.parse_dotenv_file` admitted it into the key: `a = 1` produced `"﻿a"`, so
  `get_string("a")` missed and the value was silently unreachable — plausible
  but wrong output, which this spec ranks as the worst failure mode. New F0.9
  requires the BOM stripped at every file-reading entry point, so all of
  `hocon.parse_file`, `include`'s default reader and the five adapter
  `parse_file` helpers now read as `utf-8-sig`. (The core parser already
  ignored U+FEFF mid-document, and `jsonc.parse_file` used to raise.)
  **The text entry points needed the same treatment**, which the first fix
  missed: `utf-8-sig` only covers reading a file, so a caller who decoded the
  bytes themselves still handed the BOM to `properties.parse` /
  `env.parse_dotenv` and got the unreachable key back. All five adapters now
  route their `parse` through one `strip_bom`, matching go.hocon, ts.hocon and
  rs.hocon; only a *leading* BOM is removed, and U+FEFF elsewhere stays data.
  Caught by the new cross-implementation fixtures
  ([xx.hocon#77](https://github.com/o3co/xx.hocon/pull/77)), where py.hocon was
  the only one of four failing `fi17-bom` and `fi51-bom`.
- **A literal `.` in an environment variable name became a path boundary
  (F1.2).** The env adapter joined the `__`-split segments with `.` and
  re-split on `.` while nesting, so `APP_FOO.BAR=v` produced
  `{"foo": {"bar": "v"}}` — the same shape as `APP_FOO__BAR` — and the pair was
  even reported as an F1.6 collision. Amended F1.2 pins the rule: only `__`
  creates hierarchy, so the mapped path is carried as a segment list end-to-end
  (collision detection keys on the segments themselves). `APP_FOO.BAR` now
  yields the single top-level key `"foo.bar"`, quoted-path addressable and
  coexisting with `APP_FOO__BAR`; genuine collisions such as `APP_A__B` vs
  `APP_a__b` still error, and their message now spells the path as HOCON would
  (`both map to "foo.bar"` vs `both map to a.b`) so the two cases are
  distinguishable. The same path serves `parse_dotenv`.
- **Environment variable names were case-folded with full Unicode rules
  (F1.3).** `str.lower()` maps `İ` (U+0130) to `i` + U+0307, while Go's simple
  mapping yields plain `i` — so `APP_İ` alongside `APP_I` was an F1.6 collision
  error in go.hocon and two coexisting keys here, for the same environment.
  New F1.3 pins ASCII-only folding (`A`–`Z` only, every other codepoint left
  alone), which all four implementations now share. Variable names are ASCII in
  every practical setting, so nothing else changes.
- **`.properties` silently dropped `__proto__`, `constructor` and `prototype`
  keys (F2.9).** A denylist ported verbatim from ts.hocon's first commit made
  `_set_nested` return without inserting, so `x.__proto__ = f` produced a
  phantom empty `x` object and the value was lost. A Python dict has no
  prototype, so the list protected nothing while causing data loss; new F2.9
  pins that these are ordinary keys everywhere. The denylist is removed — the
  keys are preserved with their values, at top level and nested, for both
  `adapters.properties` and `include "x.properties"` (the shared syntax
  layer). The env adapter nests through its own path and never dropped them.
- **JSONC comment stripping could fuse the tokens around a block comment
  (F3.2).** `strip_comments` replaced a `/* */` comment with the empty string
  (plus any contained newlines), so `{"a":1/*x*/2}` decoded as `{"a": 12}` and
  `{"b": tr/*x*/ue}` as `{"b": true}` instead of erroring. A comment is now
  replaced by whitespace — at least one space, with the contained newlines still
  preserved for line numbers — so the surrounding tokens stay separate and the
  malformed document fails the JSON decode as `AdapterError`.
- **A JSONC `//` comment terminated by CR silently deleted the following key
  (F3.2).** The scan looked for `\n` only, so a lone CR — a CRLF file whose
  line endings were split, or a classic-Mac ending — was comment body and the
  next line was swallowed. With the now-dangling comma stripped behind it the
  document stayed valid JSON, so `{"port": 8080, // c\r "tlsRequired": true}`
  loaded as `{"port": 8080}` with no diagnostic at all: the same silent-loss
  failure F3.2 exists to prevent, and a divergence from the dialect this
  adapter implements, where CR ends a comment. A `//` comment now ends at LF
  or CR. U+2028/U+2029 deliberately do **not** end one: `node-jsonc-parser`
  does not treat them as line breaks either, so a document reads the same here
  as in the editor that owns the format.

**Migrating from 1.10.0**: input that used to be accepted can now change shape
or raise. A variable name with a literal `.` that was relied on for nesting
(`APP_FOO.BAR` → `foo.bar`) must be respelled with the separator
(`APP_FOO__BAR`), or read through a quoted path (`cfg.get_string('"foo.bar"')`);
and a JSONC document where a block comment sat between two tokens
(`{"a": 1/*x*/2}`) now raises instead of silently decoding as `12`. An ingested
document carrying an integer beyond int64 (`{"a": 9223372036854775808}`) now
raises as well — decode it as a string or a float if the value is genuinely
that large. In the other direction, documents that used to lose data now load
fully: a key after a CR-terminated JSONC comment, and the first key of a
BOM-prefixed file, both reappear.

## [1.10.0] - 2026-07-25

### Added — format adapters for config owned by other programs

- **Properties, env, JSONC, TOML and YAML can now be mounted under a HOCON
  document**, so a `${...}` can reach into a file another program maintains
  (`hocon.adapters.{properties,env,jsonc,toml,yaml}`). The base install stays
  pure standard library: **TOML uses `tomllib`, which Python 3.11 ships**, so the
  only adapter needing a dependency is YAML, behind the `[yaml]` extra
  (`pip install hocon-parser[yaml]`). Plain JSON needs no adapter, HOCON being a
  JSON superset.
- Ingestion is AST-level — a document is decoded and built into a value tree via
  `from_map`, never rendered to HOCON text. A `${a.b}` in a mounted value stays
  literal. Parse the host document with `resolve_substitutions=False` before
  attaching the fallback.
- **YAML scalar resolution is the library's answer, not a guarantee here**, so
  `yaml.from_value` takes an already-decoded tree for a caller who needs a
  different library. `ruamel.yaml` is the default rather than the more widely
  installed PyYAML, which implements YAML 1.1 and resolves `no` to `False` — the
  Norway problem — along with `010` to 8.

### Fixed — `.properties` now accepts the whole java.util.Properties syntax (S23.5, S23.6)

- **Backslash continuations, escapes, and whitespace separators in a
  `.properties` file were mishandled**, and a continued line was dropped
  silently. `parse_properties` had implemented roughly the
  `key=value`-with-comments subset; `b\:c = 2` produced the key `b\` with value
  `c = 2`, and `a = one\` continued by `two` lost the second line. S23.5/S23.6
  were out-of-scope until [xx.hocon#73](https://github.com/o3co/xx.hocon/pull/73)
  brought them in.
- **Behavior change**: a value keeps its trailing whitespace, because Java skips
  whitespace before a value and never after it. A malformed escape raises
  `ParseError`. An unpaired surrogate is rejected: a Python `str` can hold one,
  but encoding it to UTF-8 raises, so accepting it would only defer the failure
  to serialization. The syntax layer is shared with `adapters.properties`.

### Fixed

- **Empty path segments rejected in key position (S11.7,
  [xx.hocon#68](https://github.com/o3co/xx.hocon/issues/68)).** `hocon.parse("a..b: 3")`
  now raises `ParseError` instead of silently collapsing to `{"a": {"b": 3}}`;
  likewise `.a: 3` (was `{"a": 3}`), `a...c: 4` (was `{"a": {"c": 4}}`),
  `a...c."": 4` and the nested form `o { a..b: 3 }`. HOCON.md L515-519 is
  explicit: an empty path element must always be quoted — `a."".b` is a valid
  three-element path, but `a..b`, or a path starting/ending with `.`, "is
  invalid and should generate an error". The **substitution** path lexer already
  enforced this (`${a..b}` / `${.a}` / `${a.}` all raised "empty segment in
  path"); only the **key** path parser diverged, because it dropped empty
  segments while splitting an unquoted token on `.`. It now rejects two adjacent
  periods inside one token (nothing can intervene without splitting the token,
  so the empty element is never fillable) and a leading period that is not
  serving as a separator for an already-open segment. Trailing dots were already
  rejected, and the E13 path-whitespace forms (`a .b`, `a . b`, `a. .b`,
  `a b. c`) are unaffected — the whitespace there *is* the segment content, so
  nothing is empty. `a."".b` (S11.6) remains legal. Pinned by
  `tests/test_issue68_path_empty_segment.py`; the error-fixture harness
  auto-discovers the xx.hocon `path-empty-segment/pe01–pe08` sidecars (pe07 is
  the `a."".b` must-succeed case) once synced.

- **Backtick rejected in unquoted strings (S8.1,
  [xx.hocon#68](https://github.com/o3co/xx.hocon/issues/68)).** `` a = `t` ``
  now raises `ParseError` instead of parsing as the string ``` `t` ```, as does
  a backtick in key position (`` `k` = 1 ``) or mid-token (``a = x`y``).
  HOCON.md L245-247 lists ``$ " { } [ ] : = , + # ` ^ ? ! @ * & \`` as forbidden
  outside quotes; every member was already rejected except the backtick, which
  was missing from the lexer's unquoted start/continue sets (the substitution
  path scanner had it all along). A backtick **inside** a quoted, triple-quoted
  or comment context stays ordinary content, and `(` / `)` remain deliberately
  unreserved (xx.hocon#34) — paren handling is untouched. Pinned by
  `tests/test_issue68_path_empty_segment.py` and the xx.hocon
  `unquoted-forbidden/uf01–uf04` fixtures (uf04 is the backtick-in-quotes
  must-succeed case).

## [1.9.0] - 2026-07-23

Cross-impl release coordinated to land at v1.9.0 across ts.hocon / go.hocon /
rs.hocon / py.hocon. Covers the two same-day spec corrections from
[xx.hocon#62](https://github.com/o3co/xx.hocon/pull/62) (S3.1 — empty document
parses to `{}`) and [xx.hocon#64](https://github.com/o3co/xx.hocon/pull/64)
(S3.5 — array-root document rejected with a type error), and ships the
`__version__` metadata fix and README badge additions from the previous cycle.
MINOR (not PATCH): sibling impls add public API surface in the same
coordinated cycle (rs `HoconError::Config`, go `ResolveError.Cause`/`Unwrap`)
and the error-taxonomy / empty-document behavior changes are
consumer-observable. The package version is tag-injected at build time (source
tree stays at the snapshot default).

### Fixed

- **Array-root document rejected with a type error (S3.5,
  [xx.hocon#64](https://github.com/o3co/xx.hocon/pull/64)).** `hocon.parse("[1,2]")`
  now raises `ConfigError` ("document has type array rather than object at file
  root", HOCON.md L989-991, with origin + bracket position) instead of `ParseError`
  "expected key, got lbracket". An array-root document is syntactically valid HOCON;
  the reference implementation parses it and rejects at the Config boundary
  (`Parseable.forceParsedToObject`, `ConfigException.WrongType`). The parser now
  parses the root array (malformed arrays and trailing content remain
  `ParseError`s); `parse_file` names the file in the array-root diagnostic via
  an internal S3.5-only origin fallback (deliberately NOT a global
  `origin_description` default, which would mis-attribute resolver errors
  originating inside included files to the top-level file). Include
  paths (file + package) raise `ResolveError` "included file has array at file
  root … (HOCON.md L993-994)" naming the **innermost** included source (the AST is
  checked at each parse site, so nested chains cannot accuse an intermediate
  file) — this also pins S14b.1 (previously 🤷). Net behavior is unchanged
  (array-root documents still error) — only the error class, layer, and message
  change. Pinned by `tests/test_spec_s3_5_array_root.py`; the error-fixture
  harness auto-discovers the xx.hocon `array-root/ar01–ar03` `.error` sidecars
  once synced.

- **Empty document parses to `{}` (S3.1 corrected,
  [xx.hocon#62](https://github.com/o3co/xx.hocon/pull/62)).** `hocon.parse("")`
  (and whitespace-only / comment-only / BOM-only input) returns an empty
  `Config` instead of raising `ParseError`. The S3.1 checklist item "Empty file
  is invalid (HOCON.md L130)" misread the L130-132 *JSON baseline* as
  HOCON-normative; the L134-136 brace-omission relaxation parses any document
  not beginning with `[` or `{` as if enclosed in `{}` — an empty document is
  therefore the empty object. Confirmed by the reference implementation
  (Lightbend's `"Empty document"` error is `ConfigSyntax.JSON`-only;
  `ConfigFactory.parseString("")` is a valid empty config in its own test
  suite). The ported `assert_non_empty_document` guard is removed
  (`_internal/parser/empty_check.py` deleted), along with the package-include
  zero-byte special-case and the #105 file-include carve-out — the rule is
  uniform on every path. The empty-file fixture group (ef01–ef06) joins the
  conformance and adapter corpora with its `{}` sidecars as normative. Pure
  loosening — no previously-valid input changes meaning; previously-rejected
  empty documents now succeed.

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
