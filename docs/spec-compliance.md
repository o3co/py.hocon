# Spec Compliance — py.hocon

Per-item compliance status against the canonical 209-item checklist in
[xx.hocon `docs/spec-checklist.md`](https://github.com/o3co/xx.hocon/blob/main/docs/spec-checklist.md).

> **Not started.** Rows are added as implementation lands, mirroring the
> canonical S-rows only — this file must not introduce items that do not exist
> in the canonical checklist. Cross-impl behavior outside HOCON.md belongs in
> xx.hocon `docs/extra-spec-conventions.md` (E-prefix namespace).

Expected per-impl out-of-scope (➖) beyond the 17 globally out-of-scope items:

- **S1.1** — Python `str` is pre-decoded Unicode at the I/O boundary; byte-level
  UTF-8 handling happens outside the parser (same rationale as ts.hocon).

Status legend follows the shared convention: ✅ test passes / ⚠️ partial /
❌ fails or known violation / 🤷 unverified claim / ➖ out of scope (rationale
required).
