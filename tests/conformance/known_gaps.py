"""Success-side known gaps: corpus fixtures whose Lightbend ``-expected.json``
py.hocon does not produce yet.

Shared by the two harnesses that tree-compare the success corpus
(``test_conformance.py`` and ``test_hocon_json_adapter.py``) so a gap is
declared once. Each entry is a strict xfail: when the gap closes, the XPASS
fails the run and the entry must be removed. An entry whose fixture is not on
disk (an older corpus) has no effect. Must-error gaps live in
``test_error_fixtures.py`` (``_KNOWN_GAPS``). None are open: the #67 window's
resolution layer (xx.hocon docs/resolution-model.md) closed #115, #123, #125
and the resolution-model/ fixtures of #139.

``PENDING_STEP_B`` holds the resolution-model/ cases whose sidecar has
``kind: pending-step-b``: their expected JSON is the E23 final value, which
needs window step (b). The xx.hocon runner contract (docs/fixture-conventions.md
"resolution-model/" → Runner contract) has runners skip them until then,
rather than pin them as a gap, so both harnesses skip these. The interim value
py.hocon gives meanwhile is pinned in tests/test_resolution_model.py.
"""

from __future__ import annotations

SUCCESS_KNOWN_GAPS: dict[str, str] = {}

PENDING_STEP_B: dict[str, str] = {
    "resolution-model/rv121-e23-x5-pending-step-b": (
        "pending E23 window step (b) — see xx.hocon docs/resolution-model.md §6.3; "
        "the interim result (an error) is what py.hocon gives today"
    ),
}
