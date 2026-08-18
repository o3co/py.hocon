"""E18 — the shared emitter round-trip corpus (xx.hocon
``testdata/emitter-roundtrip/``, synced into
``tests/conformance/testdata/emitter-roundtrip/`` by ``make testdata``).

Each fixture is a JSON value tree; the contract is
``parse(render(tree)) == tree``, compared as canonical trees, never as text.
Ports go.hocon ``e18_emitter_roundtrip_test.go``. See xx.hocon
docs/extra-spec-conventions.md §E18.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import hocon
from hocon import from_map

_FIXTURES = Path(__file__).parent / "conformance" / "testdata" / "emitter-roundtrip"

pytestmark = pytest.mark.skipif(
    not _FIXTURES.is_dir(),
    reason="emitter-roundtrip corpus not synced — run `make testdata`",
)

_CASES = sorted(p.stem for p in _FIXTURES.glob("*.json")) if _FIXTURES.is_dir() else []


def test_corpus_holds_fixtures() -> None:
    assert _CASES, "corpus directory exists but holds no fixtures"


@pytest.mark.parametrize("name", _CASES)
def test_corpus_round_trip(name: str) -> None:
    tree = json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    assert isinstance(tree, dict), "fixture is not a JSON object"
    # Corpus numbers stay within 2^53 (E18), so json.loads' int/float split is
    # exact and from_map receives the same value tree on every host.
    cfg = from_map(tree, name)
    before = json.dumps(cfg.to_object(), sort_keys=True)
    text = cfg.render_hocon()
    reparsed = hocon.parse_string(text, env={})
    after = json.dumps(reparsed.to_object(), sort_keys=True)
    assert before == after, (
        f"round trip changed the tree\n  before: {before}\n  after:  {after}"
        f"\n--- emitted ---\n{text}"
    )
