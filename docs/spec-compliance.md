# Spec Compliance — py.hocon

Per-item compliance status against the canonical 209-item checklist in
[xx.hocon `docs/spec-checklist.md`](https://github.com/o3co/xx.hocon/blob/main/docs/spec-checklist.md).

## Conformance summary

Measured against the shared o3co/xx.hocon corpus (Lightbend-generated expected
output), via `tests/conformance/`:

| Corpus | py.hocon | go.hocon / rs.hocon (reference) |
|---|---:|---:|
| Spec corpus (134) | **134 (100.0%)** | 134 (100.0%) |
| Lightbend suite (16) | **14/16** | 14/16 |

At parity with the reference sibling implementations. The 2 held-out Lightbend
fixtures (`test01`, `test03`) reference JVM system properties
`${?java.version}` / `${?user.home}`, which resolve only inside a JVM — every
non-JVM parser caps at 14/16.

## Per-impl notes

- **S1.1 ➖** — beyond the 17 globally out-of-scope items: Python `str` is
  pre-decoded Unicode at the I/O boundary; byte-level UTF-8 handling happens
  outside the parser (same rationale as ts.hocon).
- **S20.1–S20.4 ✅** — `get_period` / `Period(years, months, days)` implemented
  to rs.hocon's behaviour (integer-only per Lightbend `Integer.parseInt`, bare
  numbers default to days, lowercase-only units, negative permitted). ts / go
  remain ➖ here; rs.hocon is the reference. Tests: `tests/test_period.py`
  (mirrors rs `parse_period` unit tests + units-default up01–up05 scenarios).
- **S23.5, S23.6, S14a.2 (URL / classpath includes) ➖** — inside the 17
  globally out-of-scope items (see xx.hocon `docs/compliance-matrix.md`
  §Globally out-of-scope); listed here only because users ask about them:
  `.properties` multi-line + Unicode escapes are a documented simplification,
  and URL / classpath includes are unsupported by design across all siblings.

> Item-level S-rows are added as the compliance matrix is reconciled. This file
> mirrors the canonical S-rows only — it must not introduce items that do not
> exist in the canonical checklist. Cross-impl behavior outside HOCON.md belongs
> in xx.hocon `docs/extra-spec-conventions.md` (E-prefix namespace).

Status legend follows the shared convention: ✅ test passes / ⚠️ partial /
❌ fails or known violation / 🤷 unverified claim / ➖ out of scope.

## Item-level matrix

Snapshot: 2026-07-16 (post conformance-expansion — error-fixture,
units-default, deferred-resolution, properties-conflict and include-package
harnesses landed; suite: 306 passed / 1 skipped / 4 xfailed). 🤷 rows are
behavior ported from ts.hocon (with rs-gap fixes) not yet pinned by a py-side
test or consumed fixture; they burn down as further expansion waves land.

In this matrix ⚠️ means **coverage-partial** — a named py test/fixture pins a
strict subset of the item's surface, with the remainder pending — not a known
behavioral violation. py.hocon currently has zero known behavioral violations
(❌ 0); this differs from sibling docs where ⚠️ can denote a behavior gap.

Citation shorthand used on `tests:` lines:

- `corpus: <group>/<ids>` — fixtures under `tests/conformance/testdata/hocon/`
  executed by `tests/conformance/test_conformance.py::test_fixture` (parse +
  resolve + full-tree compare against Lightbend expected JSON). The corpus
  runner consumes non-error fixtures with `-expected.json` sidecars; the groups
  it holds out are consumed by the dedicated harnesses below (`error:`,
  `units:`, `dr:`, `pc:`, `ipk:`). Still unconsumed: equiv-only fixtures
  without shared expected sidecars (e.g. equiv01/unquoted.conf,
  equiv05/triple-quotes.conf) and items siblings pin only via per-impl unit
  tests.
- `error: <group>/<ids>` — must-error fixtures (`.error` /
  `-expected-error.json` sidecars plus the E5/E9 per-impl overrides ce05,
  ir03, ir04) executed by `tests/conformance/test_error_fixtures.py`
  (38 fixtures asserted to raise; error class pinned per family —
  `ResolveError` for concat-errors / env-var-list / self-ref-lookback,
  `ParseError` for include-reservation, any `ConfigError` subclass elsewhere).
- `units: <ids>` — units-default fixtures (ud01–ud08 / ub01–ub06 / un01–un03)
  driven through `get_duration` / `get_bytes` by `tests/test_units_default.py`
  (port of rs.hocon `tests/units_default_test.rs`; the up01–up05 period
  scenarios live in `tests/test_period.py`).
- `dr: <ids>` — E12 deferred-resolution scenario YAMLs (dr01–dr30, 31
  scenarios + corpus guard + 2 programmatic companions) run by
  `tests/test_deferred_resolution_fixtures.py` (parse → `with_fallback` →
  `resolve` lifecycle).
- `pc: <ids>` / `ipk: <ids>` — properties-conflict `.properties` fixtures
  driven through the include loader by
  `tests/test_properties_conflict_fixtures.py`, and E11 include-package
  fixtures driven with an in-memory registry resolver by
  `tests/test_include_package_fixtures.py` (ipk03 is skipped as per-impl N/A —
  py.hocon has no registration API to collide on; E11 decision 3, same
  exemption as ts.hocon).
- `smoke: <name>` / `period: <name>` — named tests in `tests/test_smoke.py` /
  `tests/test_period.py`.
- `(incidental)` — the fixture was not authored for this item, but a violation
  would necessarily flip its expected output; kept ✅ with that caveat.

### S1. Unchanged from JSON

- **S1.1** Files must be valid UTF-8 — §Unchanged from JSON (L117)
  out-of-scope: per-impl (same rationale as ts.hocon) — Python `str` is pre-decoded Unicode at the I/O boundary; `parse_file` reads via `encoding="utf-8"`, and the parser layer cannot observe raw bytes. See Per-impl notes above.
  tests: —
  status: ➖
- **S1.2.1** Quoted strings accept valid JSON escape sequences (`\" \\ \/ \b \f \n \r \t`) — §Unchanged from JSON (L118)
  tests: corpus: subst-tokenize/st10–st14, st19, st20
  status: ✅
- **S1.2.2** Unknown / invalid escape sequence (e.g. `\q`, `\x`) is rejected — §Unchanged from JSON (L118)
  tests: error: subst-tokenize/st-err01 (`\x`), st-err02 (`\q`)
  status: ✅
- **S1.2.3** Malformed `\uXXXX` (short / non-hex) is rejected — §Unchanged from JSON (L118)
  tests: error: subst-tokenize/st-err03 (short), st-err04 (non-hex)
  status: ✅
- **S1.2.4** Unescaped control char / raw newline in quoted string is rejected — §Unchanged from JSON (L118)
  tests: error: subst-tokenize/st-err07 (raw newline in quoted string)
  status: ✅
- **S1.2.5** Unterminated quoted string is rejected — §Unchanged from JSON (L118)
  tests: error: subst-tokenize/st-err06
  status: ✅
- **S1.2.6** Unpaired UTF-16 surrogate codepoint in `\uXXXX` escape — §Unchanged from JSON (L118)
  out-of-scope: intentional language-natural divergence. Java (Lightbend reference) silently accepts unpaired surrogates because Java strings are 16-bit code-unit sequences; Rust `char` and Go `rune` cannot represent them and reject. xx.hocon conformance fixtures cannot cover this case. Each implementation follows its language's string-type constraints.
  tests: —
  status: ➖
- **S1.3** Value types: string, number, object, array, boolean, null — §Unchanged from JSON (L119)
  tests: smoke: test_parse_scalars_and_nesting; corpus: test04 (incidental — all six value types)
  status: ✅
- **S1.4** Number formats match JSON (no NaN, no Infinity) — §Unchanged from JSON (L120)
  tests: corpus: leading-zero-value/lzv01, unquoted-starts/us10, us11 (number-grammar greedy-backtrack boundaries)
  status: ✅

### S2. Comments

- **S2.1** `//` line comment — §Comments (L125)
  tests: corpus: unquoted-starts/us05 (`123// rest of line`); test09–test12 (incidental — `//` header comments)
  status: ✅
- **S2.2** `#` line comment — §Comments (L125)
  tests: corpus: test04, test05 (incidental — `#` comments incl. trailing same-line comments after values)
  status: ✅
- **S2.3** Comment markers inside quoted strings are literal — §Comments (L126)
  tests: corpus: test04 (incidental — quoted `"mongodb://localhost/akka.mailbox"` URI value keeps `//` literal)
  status: ✅

### S3. Omit root braces

- **S3.1** Empty document (empty / whitespace-only / comment-only / BOM-only file) parses to the empty object `{}` — §Omit root braces (L130-136)
  tests: tests/conformance/test_conformance.py::test_empty_file_parses_to_empty (empty-file/ef01–ef06, `{}` sidecars normative; group also in the main corpus); smoke: test_empty_input_parses_to_empty; tests/test_include_package_fixtures.py::test_package_empty_variant_content_contributes_empty; adapter: test_cli_empty_file_emits_empty_object
  status: ✅ — Corrected 2026-07-23 (xx.hocon E10). The item previously read "Empty file is invalid" — a misreading of the L130-132 JSON baseline as HOCON-normative; the L134 brace-omission relaxation makes an empty document the empty object. The ported `assert_non_empty_document` guard is removed (`_internal/parser/empty_check.py` deleted); empty documents parse to `{}` uniformly at top level and on every include path.
- **S3.2** Root non-object/non-array is invalid (when explicitly enclosed) — §Omit root braces (L131)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); pinned in siblings by per-impl unit tests only
- **S3.3** Implicit `{}` when file does not start with `[` or `{` — §Omit root braces (L134)
  tests: corpus: virtually every group fixture is a brace-less root (incidental; e.g. subst-tokenize/st01, numeric-obj-array/na01, key-hyphen-position/kh01)
  status: ✅
- **S3.4** Unbalanced trailing `}` without opening `{` is invalid — §Omit root braces (L138)
  tests: — (empirical rs-parity check only; no py pin test yet)
  status: ✅ — mirrors rs.hocon (rs status ✅ via its braced-root stray-brace test; the unbraced-root + stray `}` case ts documents as ❌ [ts#55] behaves identically to rs in py, verified empirically). Dedicated pin test pending (conformance expansion).
- **S3.5** Array-root document is valid syntax; object-rooted parse API rejects with a type error — §Include semantics: merging (L989-991)
  tests: tests/test_spec_s3_5_array_root.py (type-error class + position + origin naming + deferred + malformed guards + include / nested-include / package variants); tests/conformance/test_error_fixtures.py auto-discovers ar01–ar03 `.error` sidecars once synced
  status: ✅ — Added 2026-07-23. `_Parser.parse` parses the root array (re-anchored at the
  opening `[`; malformed arrays / trailing content stay `ParseError`s);
  `_build_resolve_context` rejects with `ConfigError` ("document has type array rather
  than object at file root", origin + bracket position), matching Lightbend's
  `Parseable.forceParsedToObject` (`WrongType`). `parse_file` defaults the origin to the
  file path. Include paths check the AST at each parse site, so nested chains name the
  innermost source. Previously `ParseError` "expected key, got lbracket".

### S4. Key-value separator

- **S4.1** `=` is interchangeable with `:` — §Key-value separator (L143)
  tests: corpus: group fixtures use `=` throughout; test02 / test06 use `:` (incidental)
  status: ✅
- **S4.2** `:` / `=` may be omitted before `{` — §Key-value separator (L146)
  tests: corpus: test04 (`akka { … }`, `actor { … }`), test10 (`foo { … }`), include-env-fallback/iev01 inner (`registry { … }`) (incidental)
  status: ✅

### S5. Commas

- **S5.1** Newline acts as element/field separator — §Commas (L152)
  tests: corpus: every multi-line fixture (incidental; e.g. test04, test05 — comma-less newline-separated fields)
  status: ✅
- **S5.2** Single trailing comma is allowed and ignored — §Commas (L155)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); no consumed fixture contains a trailing comma (siblings pin via unit tests)
- **S5.3** Two trailing commas (`[1,2,3,,]`) is invalid — §Commas (L160)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); error case, siblings pin via unit tests
- **S5.4** Leading comma (`[,1,2,3]`) is invalid — §Commas (L161)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); error case, siblings pin via unit tests
- **S5.5** Two consecutive commas (`[1,,2,3]`) is invalid — §Commas (L162)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); error case, siblings pin via unit tests
- **S5.6** Same comma rules apply to object fields — §Commas (L163)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); siblings pin via unit tests

### S6. Whitespace

- **S6.1** Unicode Zs/Zl/Zp category characters are whitespace — §Whitespace (L170)
  tests: —
  status: 🤷 — ported (ts `isHoconWhitespace` predicate, Phase 6 #1 parity), pending dedicated test (conformance expansion)
- **S6.2** Non-breaking spaces (0x00A0, 0x2007, 0x202F) are whitespace — §Whitespace (L171)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion)
- **S6.3** BOM (0xFEFF) treated as whitespace — §Whitespace (L173)
  tests: corpus: bom (root fixture)
  status: ✅ — start-of-input BOM pinned by fixture; mid-stream BOM-as-whitespace ported but unpinned
- **S6.4** ASCII control whitespace (tab, vtab, FF, CR, FS, GS, RS, US) — §Whitespace (L174)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion)
- **S6.5** "newline" means specifically 0x000A (LF) — §Whitespace (L183)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); no CR/CRLF fixture in the consumed corpus

### S7. Duplicate keys and object merging

- **S7.1** Later non-object key overrides earlier — §Duplicate keys (L189)
  tests: corpus: test06 (`x=${a}` then `x=${b}` → 2), test09 (`b=${x}` then `b=${y}` → 5)
  status: ✅
- **S7.2** Two object values are merged recursively — §Duplicate keys (L191)
  tests: smoke: test_object_merge_and_arrays; corpus: test09 (`a=${x}` then `a={c:3}` → `{q:10,c:3}`)
  status: ✅
- **S7.3** Merge: fields in only one object are kept — §Duplicate keys (L199)
  tests: smoke: test_object_merge_and_arrays; corpus: test09
  status: ✅
- **S7.4** Merge: non-object field in both → second wins — §Duplicate keys (L201)
  tests: corpus: test06 (`y=${d}` merged with `{hello:world, foo:10}` → `foo=10`)
  status: ✅
- **S7.5** Merge: object field in both → recursive merge — §Duplicate keys (L203)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); no consumed fixture has an object-typed field present in both duplicates one level down
- **S7.6** Intermediate non-object value breaks merge with later object — §Duplicate keys (L207)
  tests: corpus: test09 (`a.q.r.s=${b}` object broken by intermediate `a=${y}`=5; final `a.q` = 10, not an object)
  status: ✅

### S8. Unquoted strings

- **S8.1** Forbidden characters rejected (``$ " { } [ ] : = , + # ` ^ ? ! @ * & \``) and whitespace — §Unquoted strings (L245). **Parens `(` / `)` are NOT in this set** and appear as ordinary unquoted content (e.g. `a = hello (world)` → `{"a":"hello (world)"}`). They are contextual tokens only inside include resource syntax — see S14a. Cross-impl pins: `testdata/hocon/unquoted-parens/up01-up06`.
  tests: corpus: unquoted-parens/up01–up06 (parens-not-forbidden clarification)
  status: ✅ — mirrors rs.hocon. Empirically verified rs-parity incl. backtick handling (py accepts `` ` `` in unquoted strings exactly like rs; ts documents the same behavior as ⚠️ on its side); a py-side forbidden-set sweep test is pending (conformance expansion).
- **S8.2** `//` inside an unquoted string starts a comment — §Unquoted strings (L248)
  tests: corpus: unquoted-starts/us05 (`a = 123// rest of line` → `123`)
  status: ✅
- **S8.3** Initial token `true`/`false`/`null` parsed as keyword — §Unquoted strings (L250)
  tests: smoke: test_parse_scalars_and_nesting (`true` / `null`); corpus: test04 (incidental — `write-skew = true`, `blocking-allowed = false`)
  status: ✅
- **S8.4** Initial number characters parse as number — §Unquoted strings (L250)
  tests: smoke: test_parse_scalars_and_nesting; corpus: unquoted-starts/us13 (`01` → 1, E8 value-layer coercion), leading-zero-value/lzv01
  status: ✅
- **S8.5** Embedded `true`/`false`/`null`/number become string content — §Unquoted strings (L266)
  tests: corpus: unquoted-starts/us06 (`foo123`), us07; test11 (`foo-bar = bar-baz`)
  status: ✅
- **S8.6** Unquoted string cannot begin with `0-9` or `-` — §Unquoted strings (L270)
  tests: corpus: unquoted-starts/us01–us14, us16–us30 (29 consumed fixtures — E8 Lightbend-aligned value-position reading); key-hyphen-position/kh01–kh08 (E13 — S8.6 not enforced on key path segments)
  status: ✅ — post-E8 amendment, mirroring rs: value-start `-foo` accepted as unquoted, digit-leading runs coerced at the value layer. Known cross-impl gap us15 (`1e+x`, Lightbend value-parser error): the `+`-reservation mid-unquoted-run is enforced by NO sibling — py consumes the fixture as a strict-xfail tripwire (error: unquoted-starts/us15, `xfail(strict=True)`), mirroring ts.hocon#73 `it.fails` and rs.hocon's `#[should_panic]`; an XPASS fails the run the moment the gap closes.
- **S8.7** No escape sequences in unquoted strings — §Unquoted strings (L253)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); siblings pin via lexer unit tests
- **S8.8** Unquoted strings allow characters outside the forbidden set — §Unquoted strings (L280)
  tests: corpus: unquoted-parens/up01–up06; key-hyphen-position/kh05, kh07 (hyphen-start segments)
  status: ✅

### S9. Multi-line strings

- **S9.1** `"""..."""` triple-quoted string — §Multi-line strings (L291)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); pinned in siblings by equiv05/triple-quotes.conf, which the py corpus does not consume (no shared expected sidecar)
- **S9.2** Newlines and whitespace preserved literally — §Multi-line strings (L293)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion)
- **S9.3** Unicode escapes NOT interpreted inside triple-quoted — §Multi-line strings (L294)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion)
- **S9.4** Scala-style trailing extra quotes are part of string — §Multi-line strings (L300)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion)
- **S9.5** Unterminated `"""` raises an error — §Multi-line strings (L291-293, by analogy with quoted strings)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); error case

### S10. Value concatenation

- **S10.1** Simple values + non-newline whitespace → string concat — §Value concatenation (L310)
  tests: smoke: test_substitution (`${a}px` → `"1px"`); corpus: unquoted-parens/up01, up03
  status: ✅
- **S10.2** All arrays → array concatenation — §Value concatenation (L312)
  tests: corpus: env-var-list/ev06 (`["x","y"] ${?LIST[]}`), ev07; self-ref-lookback/sr08
  status: ✅
- **S10.3** All objects → object merge (concatenation) — §Value concatenation (L314)
  tests: corpus: numeric-obj-array/na03c (`${obj1} ${obj2}` → merged object, no array conversion)
  status: ✅
- **S10.4** Mixing arrays + objects in concat is an error — §Array and object concatenation (L385)
  tests: error: concat-errors/ce01, ce02, ce07, ce08, ce10, ce11, ce14 (`ResolveError` pinned); corpus: concat-errors/ce09, ce15 (success boundary)
  status: ✅
- **S10.5** Inner whitespace between simple values preserved — §String value concatenation (L332)
  tests: corpus: unquoted-parens/up01 (`hello (world)`), up03
  status: ✅
- **S10.6** Leading/trailing whitespace around concat discarded — §String value concatenation (L346)
  tests: corpus: unquoted-parens/up01, up03 (expected strings carry no outer whitespace)
  status: ✅
- **S10.7** Concatenation does not span a newline — §String value concatenation (L335)
  tests: corpus: every multi-line fixture (incidental; adjacent value lines never merge — e.g. test04)
  status: ✅
- **S10.8** String concat allowed in field keys — §Value concatenation (L317)
  tests: corpus: key-hyphen-position/kh01–kh03, kh08 (`foo -bar = 1` → key `"foo -bar"`); path-expr-whitespace/pw04 (`a b.c d = 1`)
  status: ✅
- **S10.9** `true`/`false` stringify to `"true"`/`"false"` in concat — §String value concatenation (L363)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); pinned in siblings by equiv01/unquoted.conf (not consumed by py)
- **S10.10** `null` stringifies to `"null"` in concat — §String value concatenation (L364)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); same missing-fixture gap as S10.9
- **S10.11** Numbers stringify as written in the source file — §String value concatenation (L366)
  tests: smoke: test_substitution (`${a}px` with `a = 1` → `"1px"`); corpus: unquoted-starts/us10, us11 (digit-leading runs keep source form)
  status: ✅
- **S10.12** A single non-string value is NOT stringified (type preserved) — §String value concatenation (L376)
  tests: smoke: test_parse_scalars_and_nesting; corpus: subst-tokenize/st01 (`a=${v}` stays a number)
  status: ✅
- **S10.13** Array/object appearing in string concat is an error — §String value concatenation (L373)
  tests: error: concat-errors/ce03, ce04, ce06, ce12, ce13, ce05 (E5 per-impl override — Lightbend silently accepts `a = { b: 1 } x`, o3co strict-spec posture rejects) — `ResolveError` pinned
  status: ✅
- **S10.14** Whitespace around obj/array substitutions is ignored — §Concatenation with whitespace (L440)
  tests: corpus: self-ref-lookback/sr07, sr08; env-var-list/ev06–ev08; numeric-obj-array/na03a–na03c
  status: ✅
- **S10.15** Quoted whitespace between obj/array substitutions is an error — §Concatenation with whitespace (L442)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); error case, siblings pin via unit tests
- **S10.16** Non-newline whitespace in arrays is concat, not separator — §Arrays without commas or newlines (L447)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); pinned in siblings by equiv01/no-commas.conf (not consumed by py)
- **S10.17** Substitution resolving to an array participates in array concat (`${arr} [x]`) — §Array and object concatenation (L387)
  tests: corpus: env-var-list/ev06, ev07; self-ref-lookback/sr08; numeric-obj-array/na03b
  status: ✅
- **S10.18** Substitution resolving to an object participates in object merge (`${obj} {x:1}`) — §Array and object concatenation (L388)
  tests: corpus: numeric-obj-array/na03c (`${obj1} ${obj2}` → object merge)
  status: ✅
- **S10.19** Mixing a substitution-resolved object with a literal array (or vice versa) is an error — §Array and object concatenation (L385-389)
  tests: error: concat-errors/ce07 (`${obj}` + array), ce08 (`${arr}` + object), ce12, ce13 (resolved array/object in string concat) — `ResolveError` pinned
  status: ✅

### S11. Path expressions

- **S11.1** `.` outside quoted is a path separator — §Path expressions (L483)
  tests: corpus: path-expr-whitespace/pw01–pw05, pw07; subst-tokenize/st05; key-hyphen-position/kh02, kh07
  status: ✅
- **S11.2** `.` inside quoted is literal — §Path expressions (L484)
  tests: corpus: subst-tokenize/st03, st04, st06, st18; test02 (`${"a.b.c"}` → 103)
  status: ✅
- **S11.3** Numbers retain original string representation in paths — §Path expressions (L489)
  tests: corpus: test11 (quoted numeric keys, `"10"`/`"-10"`), test12 (very long numeric keys)
  status: ✅
- **S11.4** `10.0foo` → path `[10, 0foo]` — §Path expressions (L496)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); siblings pin via unit tests
- **S11.5** `foo10.0` → path `[foo10, 0]` — §Path expressions (L498)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); siblings pin via unit tests
- **S11.6** Empty path element must be quoted (`a."".b` ok) — §Path expressions (L515)
  tests: corpus: test02 (`"" : { "" : { "" : 42 } }` + `${""."".""}`); subst-tokenize/st09
  status: ✅
- **S11.7** `a..b` and paths starting/ending with `.` are errors — §Path expressions (L517)
  tests: error: subst-tokenize/st-err08 (`${}` empty path), st-err09 (`${.foo}`), st-err10 (`${foo.}`), st-err11 (`${foo..bar}`); error: path-expr-whitespace/pw06 (trailing dot in key path, `a b. = 1`)
  status: ✅
- **S11.8** Path expression always stringifies (single `true` → `"true"`) — §Path expressions (L504)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); siblings pin via unit tests
- **S11.9** Substitutions not allowed inside path expressions — §Path expressions (L479)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); error case, siblings pin via unit tests
- **S11.10** Quoted path segments respected in getter API (e.g. `config.get("foo.\"bar.baz\"")`) — §Path expressions (L485)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); test02 pins the parse side of quoted segments, but this item is about the getter API, which the corpus tree-compare does not exercise

### S12. Paths as keys

- **S12.1** `foo.bar : 42` expands to `foo { bar : 42 }` — §Paths as keys (L530)
  tests: corpus: subst-tokenize/st05; key-hyphen-position/kh02; test05 (`application.name=…` etc.)
  status: ✅
- **S12.2** Multi-element keys expand to nested objects — §Paths as keys (L538)
  tests: corpus: subst-tokenize/st05 (`a.b.c=1`), st18; test05
  status: ✅
- **S12.3** Path keys merge per duplicate-key rules — §Paths as keys (L544)
  tests: corpus: test05 (multiple `application.*` / `module.*` keys merge into one object)
  status: ✅
- **S12.4** Whitespace in keys: `a b c : 42` = `"a b c" : 42` — §Paths as keys (L553)
  tests: corpus: path-expr-whitespace/pw04 (`a b.c d = 1`); key-hyphen-position/kh01, kh05
  status: ✅
- **S12.5** `include` may NOT begin a path expression in a key — §Paths as keys (L570)
  tests: corpus: include-reservation/ir05–ir09, ir11, ir14 (success-boundary side: quoted `"include"` key, non-initial `include`, value-position `include`, substitution path `${include}`); error: include-reservation/ir01, ir02, ir10, ir12, ir13 + ir03/ir04 (E9 per-impl overrides — Lightbend silently accepts `include.foo = 1`, o3co rejects) — `ParseError` pinned
  status: ✅

### S13. Substitutions

- **S13.1** `${path}` is a required substitution — §Substitutions (L579)
  tests: smoke: test_substitution; corpus: subst-tokenize/st01–st08; test02
  status: ✅
- **S13.2** `${?path}` is an optional substitution — §Substitutions (L579)
  tests: corpus: subst-tokenize/st15–st17; test05 (`${?play.path}`)
  status: ✅
- **S13.3** `${?` is exactly 3 chars (no whitespace before `?`) — §Substitutions (L584)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); siblings pin via unit tests
- **S13.4** Resolver MAY consult external sources (env vars, system properties) for unresolved substitutions — §Substitutions (L588) (concrete env behavior → S26)
  tests: corpus: env-var-list/ev01 (env consulted via `.env` sidecar); include-env-fallback/iev01
  status: ✅
- **S13.5** Substitutions are NOT parsed inside quoted strings — §Substitutions (L593)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); no consumed fixture carries `${` inside a quoted string
- **S13.6** Substitution paths are absolute (rooted at config root) — §Substitutions (L603)
  tests: corpus: test02 (`${a.b.c}`, `${""."".""}`); subst-tokenize/st05, st18
  status: ✅
- **S13.7** Substitution resolution is last step (can look forward) — §Substitutions (L607)
  tests: corpus: test13-reference-with-substitutions (`a = ${b}` before `b = "b"`); self-ref-lookback/sr11 (forward refs)
  status: ✅
- **S13.8** Substitution sees the latest-assigned (merged) value — §Substitutions (L612)
  tests: corpus: test06 (`x=${a}` / `x=${b}` delayed merge); self-ref-lookback/sr11 (`foo.d = 4` override seen by `bar.a`)
  status: ✅
- **S13.9** `null` in config blocks env var lookup — §Substitutions (L618)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); siblings pin via unit tests + the Lightbend `ProbeS13_9` canon (tree keeps explicit null)
- **S13.10** Required substitution undefined → error — §Substitutions (L627)
  tests: error: test13-reference-bad-substitutions (root fixture)
  status: ✅
- **S13.11** Optional undefined in field value → field not created — §Substitutions (L632)
  tests: corpus: subst-tokenize/st15 (`x=${?missing}` → `{}`); include-env-fallback/iev01 (unset env optional leaves prior default intact)
  status: ✅
- **S13.12** Optional undefined in array element → element not added — §Substitutions (L635)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); no consumed fixture has `[${?missing}]` in element position (env-variables.conf covers it but has no expected sidecar)
- **S13.13** Optional undefined in string concat → empty string — §Substitutions (L636)
  tests: corpus: test05 (`module.crud = ${?play.path}/modules/crud` → `"/modules/crud"`); self-ref-lookback/sr01–sr03
  status: ✅
- **S13.14** Optional undefined in obj/array concat → empty obj/array — §Substitutions (L637)
  tests: corpus: concat-errors/ce15 (`[1] ${?missing}` → `[1]`); self-ref-lookback/sr07
  status: ✅
- **S13.15** `foo : ${?bar}${?baz}` skipped only when BOTH undefined — §Substitutions (L640)
  tests: dr: dr28 (`a = ${?x}${?y}`, both undefined → field omitted, expected tree `{}`)
  status: ✅
- **S13.16** Substitutions only in field values / array elements — §Substitutions (L644)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); error case, siblings pin via unit tests
- **S13.17** Single-substitution value preserves type — §Substitutions (L648)
  tests: smoke: test_substitution (`get_int("b") == 1` through `${a}`); corpus: subst-tokenize/st01
  status: ✅
- **S13.18** Substitution in multi-value concat becomes string — §Substitutions (L650)
  tests: smoke: test_substitution (`${a}px` → `"1px"`)
  status: ✅
- **S13.19** Unterminated `${...}` (missing closing `}`) is rejected — §Substitutions syntax requires closing `}` (L579)
  tests: error: subst-tokenize/st-err05
  status: ✅

#### S13a. Self-referential substitutions

- **S13a.1** `path : ${path}` resolves to prior `path` value — §Self-Referential (L666)
  tests: corpus: self-ref-lookback/sr06 (`a = "x"` then `a = ${a}foo` → `"xfoo"`)
  status: ✅
- **S13a.2** Self-ref to overridden field works in merge — §Self-Referential (L748)
  tests: dr: dr04 (`a = ${?a} extra` + fallback `a = base` → `"base extra"`), dr05 (required form `a = ${a} extra` + fallback prior → succeeds)
  status: ✅ — the API-level `with_fallback` merge the corpus tree-compare could not perform is now driven by the E12 scenario harness
- **S13a.3** Self-ref before any prior value → undefined → error — §Self-Referential (L767)
  tests: error: self-ref-lookback/sr05 (`a = ${a}foo`, no prior — `ResolveError` pinned); dr: dr06 (required self-ref, no fallback prior — Lightbend-faithful `CycleError` category, mapped to `ResolveError` per the fixture's per-impl allowance)
  status: ✅ — mirrors rs.hocon: same error class as rs (`ResolveError`); the message-classification detail (undefined-vs-cycle wording, the point ts documents as ⚠️) remains a cross-impl presentation difference, not a behavior gap
- **S13a.4** Optional self-ref `${?foo}` disappears silently — §Self-Referential (L776)
  tests: corpus: self-ref-lookback/sr01, sr07 (`${?a}` with no prior vanishes from concat / array concat)
  status: ✅
- **S13a.5** Substitution hidden by later non-object → no error — §Self-Referential (L780)
  tests: dr: dr22 (same-source: `foo = ${nonexist}` overridden by `foo = 42` → no error), dr23 (across layers: receiver `foo = 42` hides fallback `foo = ${nonexist}`)
  status: ✅
- **S13a.6** Cycle inside object `a : { b : ${a} }` → error — §Self-Referential (L688)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); the root `cycle` error fixture is now consumed by the error harness but exercises a circular *include* (`include "cycle.conf"`), not the in-object substitution cycle, so it does not pin this row
- **S13a.7** Cycle inside array `a : [${a}]` → error — §Self-Referential (L689)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); error case
- **S13a.8** Two-step cycle `bar : ${foo}; foo : ${bar}` → error — §Self-Referential (L857)
  tests: smoke: test_circular_substitution_raises
  status: ✅
- **S13a.9** Multi-step cycle `a→b→c→a` → error — §Self-Referential (L862)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); error case
- **S13a.10** Substitution memoized by instance, not by path — §Self-Referential (L885)
  tests: —
  status: 🤷 — ported (ts resolver architecture), pending decision + test: ts/go mark this ➖ (not externally observable through their APIs) while rs pins the observable equal-values constraint with a dedicated test; py has adopted neither posture yet
- **S13a.11** Object can refer to its own descendant (`bar : { foo : 42, baz : ${bar.foo} }`) — §Self-Referential (L806)
  tests: corpus: test09 (`c = ${x}` then `c = { d: 600, e: ${a}, f: ${b} }` delayed-merge), test10
  status: ✅
- **S13a.12** Self-ref in path expression `${foo.a}` resolves to "below" — §Self-Referential (L791)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); siblings cite Lightbend test06 here, but that association is indirect (test06 exercises delayed merge, not the L791 `foo : ${foo.a}` shape) — a direct py pin test is preferred over inheriting it
- **S13a.13** `a = ${?a}foo` resolves to `"foo"` (look-back undefined) — §Self-Referential (L841)
  tests: corpus: self-ref-lookback/sr01–sr04, sr06–sr16 (15 consumed fixtures; the required-form error fixture sr05 is consumed by the error harness — see S13a.3)
  status: ✅
- **S13a.14** Mutually-referring object fields (`bar.a = ${foo.d}; foo.c = ${bar.b}`) resolve lazily without false cycle — §Self-Referential (L825-834)
  tests: corpus: self-ref-lookback/sr11 (mutual object refs + later override, no false cycle)
  status: ✅

#### S13b. `+=` field separator

- **S13b.1** `a += b` expands to `a = ${?a} [b]` — §`+=` field separator (L725)
  tests: smoke: test_self_append (`a = [1]; a += 2; a += 3` → `[1, 2, 3]`)
  status: ✅
- **S13b.2** `+=` on non-array prior value → error — §`+=` field separator (L732)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); error case, siblings pin via unit tests
- **S13b.3** `+=` works on first mention of key (no prior `=`) — §`+=` field separator (L734)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); siblings pin via unit tests

#### S13c. List values from environment variables

- **S13c.1** `${X[]}` looks up `X_0`, `X_1`, ... env vars — §List values from env (L900)
  tests: corpus: env-var-list/ev01, ev06–ev08, ev11
  status: ✅
- **S13c.2** Stops at first missing index — §List values from env (L905)
  tests: corpus: env-var-list/ev02 (gap stops the scan), ev10 (empty string ≠ absent)
  status: ✅
- **S13c.3** `${X[]}` no elements → required error — §List values from env (L910)
  tests: error: env-var-list/ev03 (required `${X[]}` with zero indexed env vars — `ResolveError` pinned)
  status: ✅
- **S13c.4** `${?X[]}` no elements → undefined / removed — §List values from env (L912)
  tests: corpus: env-var-list/ev04, ev13
  status: ✅
- **S13c.5** `[]` suffix supported only for env vars (not config / sys props) — §List values from env (L902)
  tests: corpus: env-var-list/ev12b (optional form does NOT fall back to the bare scalar env var), ev05 + ev12c (config-defined wins, E6); error: env-var-list/ev12a (required form: `[]` suffix suppresses the scalar env-var fallback → `ResolveError` pinned)
  status: ✅

### S14. Includes

#### S14a. Include syntax

- **S14a.1** `include "filename"` (heuristic) — §Include syntax (L925)
  tests: corpus: file-include (root fixture); include-reservation/ir05, ir09; include-env-fallback/iev01; test10
  status: ✅
- **S14a.2** `include url("...")` — §Include syntax (L927)
  out-of-scope: URL fetching is unsupported by design; declared as a Known Limitation in each implementation's README. HOCON.md L1175-1177 permits this: "Implementations need not support files, Java resources, or URLs."
  tests: —
  status: ➖
- **S14a.3** `include file("...")` — §Include syntax (L927)
  tests: corpus: file-include (`include file("subdir/baz.conf")` — form parsed and dispatched; target unresolved from cwd, silently ignored per S14d.1)
  status: ⚠️ — the `file()` syntax is parsed and routed through the loader, but no consumed fixture performs a *successful* `file()` load (the fixture's targets intentionally miss under corpus cwd); a positive-load py test is pending
- **S14a.4** `include classpath("...")` — §Include syntax (L927)
  out-of-scope: classpath resources are a JVM-only concept; non-JVM implementations have no equivalent loader.
  tests: —
  status: ➖
- **S14a.5** `include required(...)` — §Include syntax (L930)
  tests: ipk: ipk05 (`include required(package(...))` registry miss → `PackageLookupError`, E11 decision 7)
  status: ⚠️ — the `required(package(...))` miss path is pinned; `required(file(...))` and the heuristic `required("...")` forms (the S14d.2 side) remain unpinned
- **S14a.6** Unquoted `include` at non-start-of-key is literal — §Include syntax (L962)
  tests: corpus: include-reservation/ir07 (`foo.include = 1`), ir08 (`a = include` value position)
  status: ✅
- **S14a.7** Whitespace allowed between `include` and resource name (incl. newlines) — §Include syntax (L952)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); siblings pin via unit tests
- **S14a.8** No value concatenation on include argument — §Include syntax (L957)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); error case
- **S14a.9** No substitutions in include argument — §Include syntax (L959)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); error case
- **S14a.10** Include argument must be quoted string — §Include syntax (L958)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); error case
- **S14a.11** `"include"` (quoted) is just a normal key — §Include syntax (L977)
  tests: corpus: include-reservation/ir06, ir11, ir14 (`"include" = "v"` + `${include}` lookup)
  status: ✅

#### S14b. Include semantics: merging

- **S14b.1** Included root must be an object (array → error) — §Include semantics: merging (L993)
  tests: tests/test_spec_s3_5_array_root.py (include + nested-include + package variants)
  status: ✅ — Pinned with S3.5 (2026-07-23): the include loader raises `ResolveError`
  "included file has array at file root … (HOCON.md L993-994)" naming the innermost
  included source with the bracket position.
- **S14b.2** Included keys merge per duplicate-key rules — §Include semantics: merging (L997)
  tests: corpus: file-include (`base` + included `foo` + nested-included `bar` merge into one root); include-env-fallback/iev01
  status: ✅
- **S14b.3** Earlier-in-including value + included → merged/overridden — §Include semantics: merging (L1000)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); no consumed fixture has a same-key conflict between including and included files
- **S14b.4** Later-in-including value overrides included — §Include semantics: merging (L1004)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); same missing-conflict-fixture gap as S14b.3

#### S14c. Include semantics: substitution

- **S14c.1** Substitutions in included file are relativized to including scope — §Include semantics: substitution (L1019)
  tests: corpus: test10 (test09.conf included under `foo { }` and `bar.nested { }` — its `${x}`/`${y}`/`${a}`/`${b}` references resolve in the nested scopes)
  status: ✅
- **S14c.2** Original (non-relativized) path also tried as fallback — §Include semantics: substitution (L1048)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); the sibling pin (Lightbend test03) is held out of the py corpus as a JVM-system-property xfail

#### S14d. Include semantics: missing / required

- **S14d.1** Missing optional include silently ignored — §Include semantics: missing files (L1053)
  tests: corpus: file-include (`file("subdir/baz.conf")` and nested `file("bar-file.conf")` unresolved from cwd → silently ignored; expected tree has no `baz`/`bar-file` keys)
  status: ✅
- **S14d.2** Missing `required(...)` include → error — §Include semantics: missing files (L1057)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); error case
- **S14d.3** Non-missing IO errors NOT swallowed — §Include semantics: missing files (L1069)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); error case

#### S14e. Include semantics: file formats & extensions

- **S14e.1** Extensionless basename probes multiple extensions — §Include semantics: file formats (L1080)
  tests: —
  status: 🤷 — ported (loader probes `.properties`/`.json`/`.conf`), pending dedicated test (conformance expansion)
- **S14e.2** Multiple matching extensions all loaded — §Include semantics: file formats (L1088)
  tests: —
  status: 🤷 — ported (loader deep-merges all found extensions), pending dedicated test (conformance expansion)
- **S14e.3** Load order: `.properties` → `.json` → `.conf` — §Include semantics: file formats (L1091)
  tests: —
  status: 🤷 — ported (loader iterates in exactly this order, last wins), pending dedicated test (conformance expansion)
- **S14e.4** URL include: no extension probing (exact URL only) — §Include semantics: file formats (L1103)
  out-of-scope: URL include unsupported; see S14a.2.
  tests: —
  status: ➖
- **S14e.5** URL include: format from Content-Type or URL path extension — §Include semantics: file formats (L1104)
  out-of-scope: URL include unsupported; see S14a.2.
  tests: —
  status: ➖

#### S14f. Include semantics: locating resources

- **S14f.1** Quoted-string heuristic: URL if valid protocol — §Include semantics: locating (L1115)
  out-of-scope: URL include unsupported; see S14a.2. The heuristic that distinguishes URL strings from filenames is moot when no URL form is supported.
  tests: —
  status: ➖
- **S14f.2** Otherwise treated as file/resource adjacent to including — §Include semantics: locating (L1117)
  tests: corpus: include-reservation/ir05 (sibling `ir05-inner.conf` in the group dir); file-include (`subdir/foo.conf`); test10
  status: ✅
- **S14f.3** Filesystem: relative path = relative to including dir (NOT cwd) — §Include semantics: locating (L1154)
  tests: corpus: file-include (nested chain — `subdir/foo.conf`'s `include "bar.conf"` resolves inside `subdir/`, while pytest cwd is the repo root)
  status: ✅
- **S14f.4** Filesystem: absolute path preserved — §Include semantics: locating (L1152)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); the shared corpus cannot carry absolute paths
- **S14f.5** Filesystem: fall back to classpath on not-found — §Include semantics: locating (L1158)
  out-of-scope: classpath is JVM-only; see S14a.4.
  tests: —
  status: ➖
- **S14f.6** URL: "adjacent to" computed from URL path component — §Include semantics: locating (L1169)
  out-of-scope: URL include unsupported; see S14a.2.
  tests: —
  status: ➖
- **S14f.7** `url()`/`file()`/`classpath()` arguments NOT relativized — §Include semantics: locating (L1179)
  tests: corpus: file-include (`file("subdir/baz.conf")` + nested `file("bar-file.conf")` are cwd-resolved, NOT relativized to the including file — their keys are absent from the expected tree; note this pin assumes the runner cwd is not the fixture dir, which holds for standard `pytest` runs from the repo root)
  status: ✅
- **S14f.8** `file:` URLs follow plain-filename filesystem semantics — §Include semantics: locating (L1171-1172)
  out-of-scope: URL include unsupported; see S14a.2. `file:` URLs are reachable only via `include url()`, which is not implemented.
  tests: —
  status: ➖

### S15. Numerically-indexed objects to arrays

- **S15.1** `{"0":"a","1":"b"}` → `["a","b"]` when array context — §Conversion (L1191)
  tests: —
  status: 🤷 — ported (`numeric_array.py` wired into `get_list`), pending dedicated test (conformance expansion); the consumed na01 fixture pins only the unconverted tree — the accessor-side conversion assertion lives in sibling per-impl tests
- **S15.2** Conversion is lazy (only on type-required access) — §Conversion (L1204)
  tests: corpus: numeric-obj-array/na01, na02 (resolved tree keeps the numeric-keyed object — no eager conversion)
  status: ⚠️ — the "no eager conversion" half is pinned by the tree-compare; the "converts on `get_list` access" half is pending a py accessor test
- **S15.3** Conversion in concatenation when list expected — §Conversion (L1210)
  tests: corpus: numeric-obj-array/na03a–na03e; concat-errors/ce09
  status: ✅
- **S15.4** Empty object NOT converted — §Conversion (L1212)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); accessor-level (na04 pins only the tree side)
- **S15.5** Non-integer keys ignored during conversion — §Conversion (L1214)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); accessor-level (na05 pins only the tree side)
- **S15.6** Missing indices compacted in resulting array — §Conversion (L1216)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); accessor-level (na06 pins only the tree side)
- **S15.7** Sorted by integer key value — §Conversion (L1216)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); accessor-level (na07 pins only the tree side)

### S16. MIME Type

- **S16.1** Content-Type for HOCON resources is `application/hocon` — §MIME Type (L1223)
  out-of-scope: these implementations are parsers, not HTTP servers — they do not produce or advertise a Content-Type. The header is set by whoever serves a `.conf` file over HTTP.
  tests: —
  status: ➖

### S17. Automatic type conversions

- **S17.1** number → string (JSON-valid form) — §Automatic type conversions (L1235)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); accessor-level coercion untested in py
- **S17.2** boolean → string ("true" / "false") — §Automatic type conversions (L1237)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion)
- **S17.3** string → number (JSON rules) — §Automatic type conversions (L1238)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion)
- **S17.4** string → bool: `true`/`yes`/`on`/`false`/`no`/`off` — §Automatic type conversions (L1239)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion)
- **S17.5** `"null"` → null when null requested — §Automatic type conversions (L1244)
  out-of-scope: none of the sibling implementations (nor py.hocon) has a `get_null()`-equivalent typed accessor; spec L1244 is structurally inapplicable to their API models.
  tests: —
  status: ➖
- **S17.6** null → other type: error — §Automatic type conversions (L1252)
  tests: period: test_period_null_rejected
  status: ⚠️ — only `get_period` is pinned; the null-rejection sweep across the other typed accessors (`get_string`, `get_int`, `get_boolean`, …) is pending
- **S17.7** object → other type: error — §Automatic type conversions (L1254)
  tests: period: test_period_non_scalar_rejected
  status: ⚠️ — only `get_period` is pinned; the object-rejection sweep across the other typed accessors is pending
- **S17.8** array → other (except numeric-indexed): error — §Automatic type conversions (L1255)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion)

### S18. Units format

- **S18.1** Number value taken as default unit — §Units format (L1279)
  tests: period: test_period_bare_number_scalar (`p = 7` → 7 days)
  status: ⚠️ — pinned for the period family only (number-typed scalar). The units-default group is now consumed, but its duration/bytes fixtures (units: ud01, ub01) carry quoted strings — those pin the string-no-unit path under S18.4; the *number-typed* duration/bytes value path (`t = 500` unquoted) remains unpinned because the fixture group has no such case
- **S18.2** String parsed as: optional ws + number + ws + unit + ws — §Units format (L1281-1294)
  tests: period: test_period_leading_trailing_ws, test_period_units (spaced forms); units: ud02–ud04 (leading / trailing / both outer ws), ud08 (ws between number and unit), ub02 (ws-padded bytes); smoke: test_duration_and_bytes (`5s`, `1K` no-space forms)
  status: ✅ — grammar pinned across the period, duration and bytes families in both spaced and no-space forms
- **S18.3** Unit name letters-only (Unicode L* / `isLetter`) — §Units format (L1287)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); siblings pin via s18_3-style unit tests
- **S18.4** String with no unit → interpreted with default unit — §Units format (L1290)
  tests: period: test_period_bare_integer_string (up01 scenario), test_period_leading_trailing_ws (up02 scenario); units: ud01–ud06 (duration: bare / ws / fractional / negative no-unit strings → ms default), ub01–ub04 (bytes: bare / ws / fractional-truncated / negative no-unit strings → byte default)
  status: ✅ — ud06 caveat: py returns signed −500 ms for `"-500"` (Lightbend `java.time.Duration` / go.hocon-faithful); rs pins `Err` only because `std::time::Duration` is unsigned (rs-side constraint, documented in rs's CHANGELOG) — the literal rs expectation is kept as a strict-xfail tripwire in `tests/test_units_default.py`, not a py violation

### S19. Duration format

- **S19.1** `ns` / `nano` / `nanos` / `nanosecond` / `nanoseconds` — §Duration format (L1307)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion)
- **S19.2** `us` / `micro` / `micros` / `microsecond` / `microseconds` — §Duration format (L1308)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion)
- **S19.3** `ms` / `milli` / `millis` / `millisecond` / `milliseconds` — §Duration format (L1309)
  tests: units: ud07 (`500ms`, no-space), ud08 (`500 ms`, spaced)
  status: ✅ — pinned via the `ms` short form in both grammar positions, the same representative pin rs.hocon cites for its ✅ (`"500 ms"`); the `milli`/`millis`/`millisecond`/`milliseconds` long forms are not separately exercised
- **S19.4** `s` / `second` / `seconds` — §Duration format (L1310)
  tests: smoke: test_duration_and_bytes (`5s` → 5000.0 ms)
  status: ⚠️ — only the `s` short form is pinned; `second`/`seconds` long forms pending
- **S19.5** `m` / `minute` / `minutes` — §Duration format (L1311)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion)
- **S19.6** `h` / `hour` / `hours` — §Duration format (L1312)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion)
- **S19.7** `d` / `day` / `days` — §Duration format (L1313)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion)
- **S19.8** Duration unit names are case sensitive (lowercase only) — §Duration format (L1304)
  tests: period: test_period_uppercase_unit_rejected (`7D`, `7 Days`, `1Y`, `3 Months` rejected); units: ud07, ud08 (positive guard: lowercase `ms` keeps parsing)
  status: ⚠️ — the L1304 lowercase-only rule is pinned on the period accessor, and the lowercase-accepted side of the duration path is now guarded by ud07/ud08; the duration-side uppercase *rejection* (`"5 MS"`, `"100 Seconds"`) is still unpinned

### S20. Period format

py.hocon exposes `get_period` returning `Period(years, months, days)`,
implemented to rs.hocon parity (see Per-impl notes). ts and go remain ➖
per-impl here (no period accessor); rs is the reference sibling.

- **S20.1** `d` / `day` / `days` — §Period Format (L1327)
  tests: period: test_period_units (`7d`, `7 days`), test_period_bare_integer_string, test_period_bare_number_scalar, test_period_negative, test_period_fractional_rejected, test_period_i32_overflow_rejected
  status: ✅ — rs-parity (ts / go: ➖)
- **S20.2** `w` / `week` / `weeks` — §Period Format (L1328)
  tests: period: test_period_weeks_to_days (`7w` → 49 days), test_period_units (`2 week`)
  status: ✅ — rs-parity (ts / go: ➖)
- **S20.3** `m` / `mo` / `month` / `months` — §Period Format (L1329)
  tests: period: test_period_units (`3m`, `3mo`, `3 months`)
  status: ✅ — rs-parity (ts / go: ➖)
- **S20.4** `y` / `year` / `years` — §Period Format (L1333)
  tests: period: test_period_units (`1y`, `10 years`)
  status: ✅ — rs-parity (ts / go: ➖)

### S21. Size in bytes format

- **S21.1** `B` / `b` / `byte` / `bytes` — §Size in bytes format (L1361)
  tests: units: ub01–ub03 (bare / ws-padded / fractional no-unit strings → byte counts via the default unit), ub04 (accessor invariant: negative byte size rejected at `get_bytes`, positive-only per Lightbend)
  status: ⚠️ — the bytes-as-base-unit interpretation and the positive-only accessor invariant are pinned; the literal `B`/`b`/`byte`/`bytes` unit spellings are not exercised by any consumed fixture (rs pins them via its `"100 B"` per-impl unit test)
- **S21.2** Powers of 10 (kB, MB, GB, TB, PB, EB, ZB, YB + long forms) — §Size in bytes format (L1365)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion)
- **S21.3** Powers of 2 (K/Ki/KiB, M/Mi/MiB, ...) — §Size in bytes format (L1376)
  tests: smoke: test_duration_and_bytes (`1K` → 1024)
  status: ⚠️ — only the `K` entry of the powers-of-2 table is pinned; `Ki`/`KiB` and the higher prefixes are pending
- **S21.4** Single-letter abbreviations → powers of 2 (java -Xmx convention) — §Size in bytes format (L1385)
  tests: smoke: test_duration_and_bytes (`1K` → 1024, binary not decimal); units: ub05 (`1024K` → 1_048_576 — Lightbend binary ground truth, NOT SI-decimal 1_024_000)
  status: ⚠️ — the binary rule is pinned for `K` only (now at accessor level via ub05 in addition to smoke); M/G/T/P/E and fractional single-letter cases pend a bsl-style accessor test (the consumed byte-single-letter/bsl01–bsl09 fixtures pin the parse side only — their expected JSON carries the raw strings, `get_bytes` conversion is accessor-level)
- **S21.5** Fractional values supported (`0.5M`) — §Units format (L1281-1294) + §Size in bytes (L1335-1342)
  tests: units: ub03 (`"1024.5"` → 1024 — fractional accepted, truncated toward zero per Lightbend `BigDecimal.toBigInteger`, NOT rounded), ud05 (duration side: `"500.5"` → 500.5 ms / 500_500_000 ns)
  status: ⚠️ — fractional acceptance and the truncation rule are pinned at accessor level; the fractional-times-multiplier form (`0.5M`/`0.5K` → 512·…) remains accessor-unpinned (bsl09 `0.5K` is consumed parse-side only; rs pins it via its fractional-binary unit tests)

### S22. Config object merging API

- **S22.1** `merge(A, B)` semantics = duplicate-key behavior — §Config object merging (L1402)
  tests: dr: dr01–dr03 (`with_fallback` layering incl. the go.hocon#99 lifecycle: parse → fallback layers → resolve), dr21 (transitive `a→b→c` substitution across three layers), dr29 (+ programmatic companion `test_dr29_empty_config_edges_programmatic`: empty-config edges)
  status: ✅
- **S22.2** Intermediate non-object hides earlier object across files — §Config object merging (L1406)
  tests: dr: dr10 (scalar in fallback1 blocks fallback2's object from merging into the receiver object), dr30 (receiver scalar blocks fallback object — barrier in the receiver itself)
  status: ✅
- **S22.3** Setting key to null clears earlier object value — §Config object merging (L1436)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); the consumed E12 deferred-resolution corpus (dr01–dr30) carries no null-over-object scenario, so this row stays unpinned

### S23. Java properties mapping

- **S23.1** Split key on `.` preserving empty strings — §Java properties (L1450)
  tests: pc: pc01, pc02 (shallow `a.b` split), pc03, pc04 (deep `a.b.c` split into nested objects)
  status: ⚠️ — dotted-key splitting into nested objects is pinned via the properties-conflict fixtures; the empty-segment edge (`a..b` → preserved empty-string element) is not exercised by any consumed fixture
- **S23.2** Empty path elements (leading/trailing) preserved — §Java properties (L1456)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion)
- **S23.3** Properties values are always strings — §Java properties (L1471)
  tests: pc: pc01–pc04 (all four expected trees carry string-typed leaves end-to-end; the harness `_norm` distinguishes str from num)
  status: ⚠️ — pinned only for the plain-word values the pc fixtures carry; the discriminating case (a numeric-looking value like `port=8080` staying the string `"8080"`) is pending a dedicated fixture
- **S23.4** Object wins over string on conflicting key — §Java properties (L1485)
  tests: pc: pc01–pc04 (object wins over string on the conflicting key in both input orders, shallow `a`/`a.b` and deep `a.b`/`a.b.c`)
  status: ✅
- **S23.5** Multi-line values (backslash continuation) — §Note on Java properties similarity (L1587)
  out-of-scope: declared in each implementation's README — the `.properties` reader supports only basic `key=value` syntax to avoid pulling a full Java properties parser into a non-JVM library.
  tests: —
  status: ➖
- **S23.6** Unicode escapes in `.properties` — §Note on Java properties similarity (L1587)
  out-of-scope: same rationale as S23.5.
  tests: —
  status: ➖

### S24. Conventional config files (JVM)

- **S24.1** `reference.conf` classpath merge — §Conventional configuration files (L1502)
  out-of-scope: relies on classpath resource resolution (see S14a.4).
  tests: —
  status: ➖
- **S24.2** `application.{conf,json,properties}` default load — §Conventional configuration files (L1506)
  out-of-scope: relies on classpath resource resolution (see S14a.4).
  tests: —
  status: ➖

### S25. System property override

- **S25.1** System properties override config file values — §Conventional override (L1530)
  out-of-scope: JVM system properties are a JVM-only mechanism; non-JVM runtimes use environment variables or library-specific overrides.
  tests: —
  status: ➖

### S26. Substitution fallback to environment variables

- **S26.1** Env var lookup when substitution not in config tree — §Substitution fallback (L1536)
  tests: corpus: env-var-list/ev01 etc. (env consulted, list form); include-env-fallback/iev01 (unset-env miss branch)
  status: ⚠️ — the env-fallback machinery is exercised via the S13c list form and the unset-miss branch; the plain positive scalar case (`${VAR}` resolved from env) is pending a dedicated fixture/test (test01/test03, which cover it, are the JVM xfail holdouts)
- **S26.2** Empty env var preserved as empty string (not undefined) — §Substitution fallback (L1558)
  tests: corpus: env-var-list/ev10 (empty-string list element preserved)
  status: ⚠️ — pinned in the list-element form only; the scalar `${VAR}` empty-string case is pending
- **S26.3** Env var SecurityException → treated as not present — §Substitution fallback (L1560)
  out-of-scope: `SecurityException` is a JVM-specific exception type; non-JVM runtimes have no equivalent guard at this layer.
  tests: —
  status: ➖
- **S26.4** Env vars always become strings (with auto type conversion) — §Substitution fallback (L1563)
  tests: —
  status: 🤷 — ported, pending dedicated test (conformance expansion); consumed `.env` sidecars carry only non-numeric values, so string-typing is not distinguishable in the expected trees

---

Status tally (210 items): ✅ 105 · ⚠️ 16 · ❌ 0 · 🤷 71 · ➖ 18.
Rates per the shared convention — spec-total `(✅ + ⚠️·0.5) / 210` = **53.8%**;
in-scope `(✅ + ⚠️·0.5) / (210 − 18)` = **58.9%**. The 🤷 mass (ported but
unpinned) is the burn-down list for the conformance-fixture expansion; it
contributes 0 by policy until pinned. The first expansion wave (error-fixture,
units-default, deferred-resolution, properties-conflict and include-package
harnesses) burned 🤷 from 95 to 72; the remainder is dominated by items
siblings pin via per-impl unit tests and by equiv-only fixtures the shared
corpus does not sidecar.
