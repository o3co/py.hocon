r"""A substitution cycle written twice (py counterpart of go.hocon#218 /
rs.hocon#199).

``a = ${?b}`` / ``b = ${?a}`` written twice made the in-progress branch of the
resolver re-enter a key's saved prior forever. go and rs overflowed the stack;
py hit its recursion limit and raised a ``ParseError`` ("nested too deeply …
or contains a cycle"), where Lightbend gives ``{}``. The interim guard treats
a re-entry in an unchanged in-progress state as an unbreakable cycle; the full
fix is the resolver redesign in o3co/xx.hocon#67 / #125. Expected values are
Lightbend 1.4.9.

Pinning fixtures (auto-discovered by the conformance harnesses once
``make testdata`` syncs them): ``optional-cycle-repeat/oc01–oc06``
(o3co/xx.hocon#136).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import hocon
from hocon import ResolveError


def _json(src: str) -> object:
    return json.loads(hocon.parse_string(src, env={})._render_json_for_test())


@pytest.mark.parametrize(
    ("src", "want"),
    [
        ("a = ${?b}\nb = ${?a}\na = ${?b}\nb = ${?a}\n", {}),
        ("a = ${?b}\nb = ${?a}\na = ${?b}\nb = ${?a}\na = ${?b}\nb = ${?a}\n", {}),
        ("a = ${?b}\nb = ${?c}\nc = ${?a}\na = ${?b}\nb = ${?c}\nc = ${?a}\n", {}),
        ("o.a = ${?o.b}\no.b = ${?o.a}\no.a = ${?o.b}\no.b = ${?o.a}\n", {"o": {}}),
        ("a = ${?b}\nb = ${?a}\na = ${?b}\nb = ${?a}\nc = ${?a}x\n", {"c": "x"}),
        ("a = ${?b}\nb = ${?a}\na = ${?b}\nb = ${?a}\na = 1\n", {"a": 1, "b": 1}),
    ],
    ids=["twice", "thrice", "three-keys", "nested-path", "in-concat", "later-value"],
)
def test_unbreakable_cycle_through_priors(src: str, want: object) -> None:
    assert _json(src) == want


@pytest.mark.parametrize(
    ("src", "want"),
    [
        # The second pass through o.y's prior sees `a` in progress and stops
        # on its own: the guard must let this re-entry through.
        (
            "o = { y = ${?a} }\na = ${o.y}\no.x = 5\no.y += [3]\n",
            {"a": [[3]], "o": {"x": 5, "y": [[3]]}},
        ),
        # The second pass through k's prior terminates because `o` has
        # meanwhile entered the S13a.12 prefix-prior guard set: the guard's
        # state must include that set, not only the in-progress keys.
        (
            "o = ${?k}z\no.y = ${?o.y}\nk = ${?o.x}\nk = ${k}z\n",
            {"k": "z", "o": {}},
        ),
        (
            "o = ${?k}z\no.y.z = ${?o.y.z}\nk = ${?o.x}\nk = ${k}z\n",
            {"k": "z", "o": {"y": {}}},
        ),
        (
            "o = { y = ${?k} }\nk = [${?o.y}]\nk = ${?m}\nm = ${?k}\no = ${?k}\n",
            {"k": [[]], "m": [[]], "o": [[]]},
        ),
        ("a = 1\na = ${a}x\na = ${a}y\nb = ${a}\n", {"a": "1xy", "b": "1xy"}),
        ("a = ${?b}\nb = ${?a}\na = ${?b}\n", {}),
    ],
    ids=[
        "legal-reentry",
        "prefix-prior",
        "prefix-prior-deep",
        "field-path",
        "self-ref-chain",
        "cycle-once",
    ],
)
def test_legal_reentry_unchanged(src: str, want: object) -> None:
    assert _json(src) == want


@pytest.mark.parametrize(
    "src",
    [
        "a = ${b}\nb = ${a}\na = ${b}\nb = ${a}\n",
        "a = ${?b}\nb = ${a}\na = ${?b}\nb = ${a}\n",
    ],
    ids=["required", "mixed"],
)
def test_required_cycle_is_a_resolve_error(src: str) -> None:
    with pytest.raises(ResolveError, match="circular substitution"):
        hocon.parse_string(src, env={})


def test_cycle_through_include(tmp_path: Path) -> None:
    (tmp_path / "inner.conf").write_text("a = ${?b}\nb = ${?a}\n")
    main = tmp_path / "main.conf"
    main.write_text('a = ${?b}\nb = ${?a}\ninclude "inner.conf"\n')
    assert json.loads(hocon.parse_file(str(main), env={})._render_json_for_test()) == {}


def test_concat_cycle_terminates() -> None:
    # Was a ParseError (recursion limit). The value still differs from
    # Lightbend's ({"a":"yxyx","b":"yxy"}); that is the resolver redesign
    # (o3co/xx.hocon#67 / #125), so only termination is asserted.
    _json("a = ${?b}x\nb = ${?a}y\na = ${?b}x\nb = ${?a}y\n")
