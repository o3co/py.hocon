"""Success-side known gaps: corpus fixtures whose Lightbend ``-expected.json``
py.hocon does not produce yet.

Shared by the two harnesses that tree-compare the success corpus
(``test_conformance.py`` and ``test_hocon_json_adapter.py``) so a gap is
declared once. Each entry is a strict xfail: when the gap closes, the XPASS
fails the run and the entry must be removed. An entry whose fixture is not on
disk (an older corpus) has no effect. Must-error gaps live in
``test_error_fixtures.py`` (``_KNOWN_GAPS``).

``PENDING_STEP_B`` holds the resolution-model/ cases whose sidecar has
``kind: pending-step-b``: their expected JSON is the E23 final value, which
needs window step (b). The xx.hocon runner contract (docs/fixture-conventions.md
"resolution-model/" → Runner contract) has runners skip them until then,
rather than pin them as a gap, so both harnesses skip these.
"""

from __future__ import annotations

_XX123 = (
    "o3co/xx.hocon#123: py.hocon gives o = {} — an optional cycle through an "
    "object does not yet remove the enclosing substitution"
)
_XX123_WINDOW = (
    "o3co/xx.hocon#123 (moved into the #67 window): py.hocon gives "
    'db.url = "jdbc://" — ${db.host} in a concatenation inside the object is '
    "dropped instead of reading the kept prior (localhost)"
)
_XX123_WINDOW_SIBLINGS = (
    "o3co/xx.hocon#123 (moved into the #67 window): py.hocon gives "
    'url = "jdbc://:5432" and db = {port = 5432} — one undefined optional '
    "override per leaf drops db.host's default when db.port is merged in"
)
_XX125 = (
    "o3co/xx.hocon#125: a value stack of 3+ layers loses its bottom layer "
    "(single saved prior); needs the multi-level prior (with #123)"
)
_XX115 = (
    "o3co/xx.hocon#115: an included root-level value does not keep the "
    "including file's prior (undefined optional drops the key / no delayed merge)"
)
_XX139 = (
    "o3co/xx.hocon#139 resolution-model fixture: py.hocon does not produce the "
    "reference model's result yet — fixed by the resolution layer (o3co/xx.hocon#67 "
    "window); py: o3co/py.hocon#67"
)
_XX142_SELF_CONCAT = (
    "o3co/xx.hocon#142 resolution-model fixture (merged-leaf alias): py.hocon gives "
    'app.opts.name = "base-a-c" instead of "base-a-b-c" — the self-concatenation '
    "name = ${app.opts.name}-b in the second app object is skipped; removed by "
    "o3co/py.hocon#67 (resolution window)"
)
_XX142_SUBST_BASE = (
    "o3co/xx.hocon#142 resolution-model fixture (merged-leaf alias): py.hocon gives "
    "app.opts.flags = [a, b, c, d] instead of [z, a, b, c, d] — the += appends "
    "drop the [z] from the substituted base ${base}; removed by o3co/py.hocon#67 "
    "(resolution window)"
)
SUCCESS_KNOWN_GAPS: dict[str, str] = {
    **{
        f"include-optional-prior/{name}": _XX115
        for name in (
            "io01-fuzz-seed-25",
            "io02-prior-object-and-reference",
            "io03-prior-scalar",
            "io04-prior-array",
            "io05-both-optionals-undefined",
            "io06-object-concat-keeps-prior",
            "io07-nested-include",
            "io08-optional-path-reference",
            "io16-object-subst-merges-prior",
            "io18-scoped-prior-not-leaked",
            "io20-self-ref-folded-under-included-concat",
        )
    },
    "subst-removed-target/rq27-optional-ref-into-cycle-ok": _XX123,
    "subst-removed-target/rq30-two-overrides-then-reference-pending-125": _XX125,
    "subst-removed-target/rq31-two-optionals-then-reference-pending-125": _XX125,
    "subst-removed-target/rq32-forward-reference-two-optionals-pending-125": _XX125,
    "subst-removed-target/rq33-self-ref-chain-then-reference-pending-125": _XX125,
    "subst-removed-target/rq34-default-then-env-override-in-object-window": _XX123_WINDOW,
    "subst-removed-target/rq39-sibling-leaf-overrides-keep-defaults-window": (
        _XX123_WINDOW_SIBLINGS
    ),
    **{
        f"resolution-model/{name}": _XX139
        for name in (
            "rv005-br-db-url",
            "rv007-br-outer-use",
            "rv012-e23-p2-bfirst",
            "rv013-e23-p2",
            "rv014-e23-start",
            "rv015-e23-x1-bfirst",
            "rv016-e23-x1",
            "rv017-e23-x2",
            "rv018-e23-x3",
            "rv020-fo-e23-x3-swap",
            "rv022-pye-01",
            "rv024-pye-04",
            "rv031-pye-11",
            "rv036-pye-16",
            "rv049-pyp-p08",
            "rv050-pyp-p09",
            "rv053-pyp-p12",
            "rv054-pyp-p13",
            "rv057-pyp-p16",
            "rv058-pyp-p17",
            "rv064-pyp-p23",
            "rv072-rv-flag-include",
            "rv073-rv-flag-top-parse",
            "rv075-rv-fold-remainder",
            "rv078-rv-lookback-through-list-anc",
            "rv098-rv-y10",
            "rv105-tsc-c07",
            "rv106-tsc-c08",
            "rv109-tsk-k2",
            "rv110-tsk-k3",
            "rv113-e23-x3-swap",
            "rv114-fo-e23-p2-bfirst",
            "rv124-alias-presence-other-view",
            "rv126-pe013-nonempty-base",
            "rv129-substituted-object-drops-ignored-fallbacks",
            "rv131-view-reentry-through-resolve-time-merge",
        )
    },
    "resolution-model/rv135-merged-leaf-alias-self-concat": _XX142_SELF_CONCAT,
    "resolution-model/rv137-merged-leaf-alias-substituted-base": _XX142_SUBST_BASE,
}

PENDING_STEP_B: dict[str, str] = {
    "resolution-model/rv121-e23-x5-pending-step-b": (
        "pending E23 window step (b) — see xx.hocon docs/resolution-model.md §6.3; "
        "the interim result (an error) is what py.hocon gives today"
    ),
}
