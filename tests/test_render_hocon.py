"""``Config.render_hocon()`` — E18 HOCON emitter, porting go.hocon
``render_hocon_test.go`` (the reference implementation, v1.11.0).

The correctness contract is the round trip, not the byte format: for a
resolved, data-only config, ``parse(render(tree))`` must yield the same value
tree. Trees are compared as canonical JSON (``to_object()`` +
``json.dumps(sort_keys=True)``), never as text — byte-for-byte output is
deliberately unpinned (E18). The shared cross-impl corpus lives in
``tests/test_e18_emitter_roundtrip.py``; this file pins the emitter's decision
tables directly.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import hocon
from hocon import Config, NotResolvedError, from_map


def _canonical(cfg: Config) -> str:
    return json.dumps(cfg.to_object(), sort_keys=True)


def _round_trip(values: dict[str, Any]) -> tuple[str, str, str]:
    """Render ``values`` to HOCON, parse it back, and return the re-parsed
    config's canonical JSON alongside the original's (plus the emitted text
    for failure messages). Equal JSON means the emit → parse round trip
    preserved the value tree. ``env={}`` keeps the re-parse deterministic per
    the conformance-test convention (the emitted text never contains
    substitutions, so the environment must not matter — and must not leak)."""
    cfg = from_map(values, "test")
    before = _canonical(cfg)
    text = cfg.render_hocon()
    reparsed = hocon.parse_string(text, env={})
    after = _canonical(reparsed)
    return before, after, text


# Ported 1:1 from go.hocon TestRenderHOCONRoundTrip.
_ROUND_TRIP_CASES: dict[str, dict[str, Any]] = {
    "scalars": {
        "s": "hello", "n": 8080, "f": 1.5, "b": True, "z": False, "nul": None,
    },
    "nested-objects": {
        "db": {"host": "localhost", "port": 5432, "opts": {"ssl": True}},
    },
    "arrays": {
        "tags": ["a", "b", "c"],
        "nums": [1, 2, 3],
        "objs": [{"id": 1}, {"id": 2}],
        "nested": [[1, 2], [3, 4]],
        "empty-a": [],
    },
    # Strings that would re-parse as another type MUST stay strings.
    "ambiguous-strings": {
        "looks-num": "8080",
        "looks-float": "1.5",
        "looks-bool": "true",
        "looks-null": "null",
        "norway": "no",
        "neg": "-5",
    },
    # Strings needing quoting for their content.
    "special-strings": {
        "spaces": "hello world",
        "empty": "",
        "reserved": "a:b=c,d",
        "leading": "  padded  ",
        "url": "https://example.com/a?b=1",
        "substish": "${foo.bar}",
    },
    "multiline": {
        "block": "line1\nline2\nline3",
        "crlf": "a\r\nb",
        "tab": "a\tb",
    },
    # Keys that cannot be bare.
    "awkward-keys": {
        "a.b": "dotted key",
        "has space": 1,
        "": "empty key",
        "a=b": True,
        "123": "numeric key ok",
    },
    "empty-object": {
        "outer": {"inner": {}},
    },
    "unicode": {
        "jp": "こんにちは", "emoji": "😀", "mixed": "a😀b",
    },
    # Strings that defeat triple-quoting (embedded \"\"\", a trailing ") must
    # fall through to escaped double quotes and still round-trip.
    "quote-heavy": {
        "embedded-triple": 'a"""b\nc',
        "trailing-quote": 'ends"',
        "lone-quote": 'a"b',
        "multiline-quote": 'x\ny"',
        "backslash": "a\\b\\\\c",
    },
    # Empty object as an array element and as a direct value exercise the
    # value-position empty-object branch (distinct from a nested key).
    "empty-object-positions": {
        "in-array": [{}, {"a": 1}],
        "direct": {},
    },
}


@pytest.mark.parametrize("name", _ROUND_TRIP_CASES)
def test_round_trip(name: str) -> None:
    before, after, text = _round_trip(_ROUND_TRIP_CASES[name])
    assert before == after, (
        f"round trip changed the tree\n  before: {before}\n  after:  {after}"
        f"\n--- emitted ---\n{text}"
    )


# An unresolved config has no textual round trip through a value tree, so
# render_hocon must refuse it rather than emit a broken document. The
# placeholders sit at three depths so the whole-config resolvedness gate
# (E12 decision 11) covers the nested object and array paths, not only the
# top level.
@pytest.mark.parametrize(
    ("name", "src"),
    [
        ("top-level", "a = 1\nb = ${a}\n"),
        ("nested", "a = 1\nb { c = ${a} }\n"),
        ("in-array", "a = 1\nb = [1, ${a}, 3]\n"),
        ("obj-in-arr", "a = 1\nb = [{ c = ${a} }]\n"),
    ],
)
def test_rejects_unresolved(name: str, src: str) -> None:
    cfg = hocon.parse_string(src, resolve_substitutions=False, env={})
    assert not cfg.is_resolved(), f"{name}: expected an unresolved Config"
    with pytest.raises(NotResolvedError):
        cfg.render_hocon()


# The emitted text should be idiomatic where it is safe: a plain identifier
# value and key stay bare, a number is not quoted.
def test_idiomatic_output() -> None:
    cfg = from_map({"name": "svc", "port": 8080, "enabled": True})
    got = cfg.render_hocon()
    for want in ("name = svc\n", "port = 8080\n", "enabled = true\n"):
        assert want in got, f"emitted HOCON missing {want!r}\n--- got ---\n{got}"


# A parsed HOCON document (not from from_map) also round-trips once resolved.
def test_from_parsed_document() -> None:
    src = '\na = 1\nb { c = "x", d = [1, 2, "three"] }\ne = ${a}\n'
    cfg = hocon.parse_string(src, env={})
    text = cfg.render_hocon()
    reparsed = hocon.parse_string(text, env={})
    before = _canonical(cfg)
    after = _canonical(reparsed)
    assert before == after, (
        f"parsed-doc round trip diverged\n  before: {before}\n  after:  {after}\n{text}"
    )
