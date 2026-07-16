"""S23 Java-properties conflict fixtures (properties-conflict/pc01–pc04).

Consumes the ``.properties``-driven fixture group that the main corpus runner
(``tests/conformance/test_conformance.py``) holds out — those fixtures have no
``.conf`` mapping, so this harness drives them the way rs.hocon's
``tests/conformance_properties_conflict.rs`` does: wrap each ``.properties``
file in a one-line HOCON document ``include file("<abs path>")`` and compare
the resolved tree against the ``-expected.json`` sidecar.

Pins:

- **S23.4** (HOCON.md L1485) — object always wins over string on a conflicting
  key, independent of input order (pc01/pc02 shallow, pc03/pc04 deep). Enforced
  in ``_internal/properties/properties.py`` via key-sorted insertion.
- **S23.1** (L1450, partial) — keys split on ``.`` into nested objects.
- **S23.3** (L1471, partial) — properties values stay strings (the expected
  JSON values are strings; ``_norm`` distinguishes str from num).

Normalization matches ``tests/conformance/test_conformance.py::_norm`` (key
order ignored, numbers by value, null-valued keys dropped).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import hocon

_TESTDATA = Path(__file__).parent / "conformance" / "testdata"
_EXPECTED = _TESTDATA / "expected" / "properties-conflict"
_PROPS = _TESTDATA / "hocon" / "properties-conflict"

# The four scenarios this group must at minimum carry (guard against a
# silently-thinned corpus; extra pc* fixtures are auto-consumed by discovery).
_KNOWN_STEMS = {"pc01-forward", "pc02-reverse", "pc03-deep-forward", "pc04-deep-reverse"}

pytestmark = pytest.mark.skipif(
    not _EXPECTED.is_dir() or not _PROPS.is_dir(),
    reason="properties-conflict corpus not synced — run `make testdata`",
)


def _norm(v: Any) -> Any:
    """Canonicalize a JSON value for comparison (local copy of the corpus
    runner's normalization: key order ignored, numbers by value, null keys
    dropped)."""
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if isinstance(v, bool):
        return ("bool", v)
    if isinstance(v, (int, float)):
        return ("num", float(v))
    if v is None:
        return ("null",)
    return ("str", v)


def _discover() -> list[tuple[str, Path, Any]]:
    """Map each ``<stem>-expected.json`` to its ``<stem>.properties`` fixture."""
    fixtures: list[tuple[str, Path, Any]] = []
    if not _EXPECTED.is_dir():
        return fixtures
    for exp_path in sorted(_EXPECTED.glob("*-expected.json")):
        stem = exp_path.name[: -len("-expected.json")]
        props = _PROPS / f"{stem}.properties"
        if not props.is_file():
            continue
        expected = json.loads(exp_path.read_text(encoding="utf-8"))
        fixtures.append((stem, props, expected))
    return fixtures


_FIXTURES = _discover()


@pytest.mark.parametrize(
    "stem,props,expected", _FIXTURES, ids=[stem for stem, _, _ in _FIXTURES]
)
def test_properties_conflict_fixture(stem: str, props: Path, expected: Any) -> None:
    """Drive a ``.properties`` fixture through the include loader (mirrors the
    rs.hocon wrapper strategy: ``include file("<abs>")``) and compare the full
    resolved tree against the Lightbend-shaped expected JSON."""
    wrapper = f'include file("{props.resolve().as_posix()}")'
    cfg = hocon.parse(wrapper, env={})
    got = json.loads(cfg._render_json_for_test())
    assert _norm(got) == _norm(expected), (
        f"properties-conflict/{stem}: output mismatch\n"
        f"  got:      {json.dumps(got, sort_keys=True)}\n"
        f"  expected: {json.dumps(expected, sort_keys=True)}"
    )


def test_group_complete() -> None:
    """Guard: the four canonical pc scenarios must all be discovered."""
    discovered = {stem for stem, _, _ in _FIXTURES}
    missing = _KNOWN_STEMS - discovered
    assert not missing, f"properties-conflict group is missing fixtures: {sorted(missing)}"
