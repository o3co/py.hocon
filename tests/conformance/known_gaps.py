"""Success-side known gaps: corpus fixtures whose Lightbend ``-expected.json``
py.hocon does not produce yet.

Shared by the two harnesses that tree-compare the success corpus
(``test_conformance.py`` and ``test_hocon_json_adapter.py``) so a gap is
declared once. Each entry is a strict xfail: when the gap closes, the XPASS
fails the run and the entry must be removed. An entry whose fixture is not on
disk (an older corpus) has no effect. Must-error gaps live in
``test_error_fixtures.py`` (``_KNOWN_GAPS``).
"""

from __future__ import annotations

_XX123 = (
    "o3co/xx.hocon#123: py.hocon gives o = {} — an optional cycle through an "
    "object does not yet remove the enclosing substitution"
)
_XX125 = (
    "o3co/xx.hocon#125: a value stack of 3+ layers loses its bottom layer "
    "(single saved prior); needs the multi-level prior (with #123)"
)
_XX115 = (
    "o3co/xx.hocon#115: an included root-level value does not keep the "
    "including file's prior (undefined optional drops the key / no delayed merge)"
)
_XX128 = (
    "o3co/xx.hocon#128: an optional cycle written twice is a ParseError in "
    "py.hocon instead of resolving to nonexistent"
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
        )
    },
    "optional-cycle-repeat/oc01-optional-cycle-twice": _XX128,
    "optional-cycle-repeat/oc03-optional-cycle-twice-in-concat": _XX128,
    "subst-removed-target/rq27-optional-ref-into-cycle-ok": _XX123,
    "subst-removed-target/rq30-two-overrides-then-reference-pending-125": _XX125,
    "subst-removed-target/rq31-two-optionals-then-reference-pending-125": _XX125,
    "subst-removed-target/rq32-forward-reference-two-optionals-pending-125": _XX125,
    "subst-removed-target/rq33-self-ref-chain-then-reference-pending-125": _XX125,
}
