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

## Per-impl out-of-scope (➖)

Expected beyond the 17 globally out-of-scope items:

- **S1.1** — Python `str` is pre-decoded Unicode at the I/O boundary; byte-level
  UTF-8 handling happens outside the parser (same rationale as ts.hocon).
- **S23.5, S23.6** — `.properties` multi-line + Unicode escapes (documented
  simplification, shared with the siblings).
- URL / classpath includes (S14a.2 etc.) — unsupported by design across all
  siblings.

> Item-level S-rows are added as the compliance matrix is reconciled. This file
> mirrors the canonical S-rows only — it must not introduce items that do not
> exist in the canonical checklist. Cross-impl behavior outside HOCON.md belongs
> in xx.hocon `docs/extra-spec-conventions.md` (E-prefix namespace).

Status legend follows the shared convention: ✅ test passes / ⚠️ partial /
❌ fails or known violation / 🤷 unverified claim / ➖ out of scope.
