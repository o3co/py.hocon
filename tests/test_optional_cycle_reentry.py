r"""A substitution cycle written twice (py counterpart of go.hocon#218 /
rs.hocon#199).

``a = ${?b}`` / ``b = ${?a}`` written twice made the former resolver re-enter
a key's saved prior forever. go and rs overflowed the stack; py hit its
recursion limit and raised a ``ParseError`` ("nested too deeply … or contains
a cycle"), where Lightbend gives ``{}``. py.hocon#68 added an interim guard.
The #67 window's resolution layer (xx.hocon ``docs/resolution-model.md``)
replaced it, and these inputs now follow the resolution model. Where a value
differs from what #68 pinned, it is the reference model's value, and
Lightbend 1.4.10 agrees once the keys are named so that its hash order is the
document order (§11: the result must not depend on key names).

The model's work on a dense web of optional cycles grows faster than
exponentially, and a ring of optional references can double its value on
every lap. #68's interim bounds for these are replaced by the limits of
resolution-model §10.3 (E24): 100,000 lookups and 10,000 weight units per
document value, counted only in the region of an optional cycle break, past
which the resolve fails with ``ResolutionLimitError``.

Pinning fixtures (auto-discovered by the conformance harnesses once
``make testdata`` syncs them): ``optional-cycle-repeat/oc01–oc06``
(o3co/xx.hocon#136).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import hocon
from hocon import ResolutionLimitError, ResolveError


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
        # `a` reads o.y, whose `+=` looks back at `${?a}`: a re-entry caught by
        # the required ${o.y}. Lightbend 1.4.10 gives a value only because `a`
        # hashes before `o`; with the keys renamed to document order it errors.
        ("o = { y = ${?a} }\na = ${o.y}\no.x = 5\no.y += [3]\n", "ERR"),
        # `${k}` in `k = ${k}z` looks back at `${?o.x}`: found (raw-present
        # under o's own `${?k}z`) and missing, so the required ${k} is an
        # error (#123); Lightbend 1.4.10 agrees.
        ("o = ${?k}z\no.y = ${?o.y}\nk = ${?o.x}\nk = ${k}z\n", "ERR"),
        ("o = ${?k}z\no.y.z = ${?o.y.z}\nk = ${?o.x}\nk = ${k}z\n", "ERR"),
        (
            "o = { y = ${?k} }\nk = [${?o.y}]\nk = ${?m}\nm = ${?k}\no = ${?k}\n",
            {"k": [], "m": [], "o": []},
        ),
        ("a = 1\na = ${a}x\na = ${a}y\nb = ${a}\n", {"a": "1xy", "b": "1xy"}),
        ("a = ${?b}\nb = ${?a}\na = ${?b}\n", {}),
    ],
    ids=[
        "o-y-append",
        "prefix-prior-two-element-path",
        "prefix-prior-deep",
        "field-path",
        "self-ref-chain",
        "cycle-once",
    ],
)
def test_reentry_inputs(src: str, want: object) -> None:
    # The first four were re-pinned in the #67 window (#68 pinned the values
    # its guard gave); the last two are unchanged.
    if want == "ERR":
        with pytest.raises(ResolveError):
            _json(src)
    else:
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
    # Was a ParseError (recursion limit). Only termination is asserted: the
    # value follows the interim cycle rule (resolution-model §6.3).
    _json("a = ${?b}x\nb = ${?a}y\na = ${?b}x\nb = ${?a}y\n")


_R3 = (
    "o.x = 2\n"
    "o.x = ${?o}\n"
    "o.y = { z = ${?o.y.z} }\n"
    "o.y.z = ${?o}\n"
    "o.x = ${?o.x}\n"
    "o.y = { x = ${?o.y} }\n"
)


@pytest.mark.parametrize(
    ("src", "want"),
    [
        # r3c from review: #68's guard stopped it only after the value had
        # nested deeply, then its value budget raised. The resolution model
        # resolves it (Lightbend 1.4.10 agrees with the keys renamed so that
        # hash order is document order).
        (
            _R3 + "o.y = { q = ${?o.y.z} }\n",
            {
                "o": {
                    "x": {"x": 2, "y": {"q": {"x": 2, "y": {}}, "z": {"x": 2, "y": {}}}},
                    "y": {"q": {"x": 2, "y": {}}, "z": {"x": 2, "y": {}}},
                }
            },
        ),
        # r3b with `o.y.q = ${?o.x}` written twice.
        (
            _R3 + "o.y = ${?o.y.z}\no.y.q = ${?o.x}\no.y.q = ${?o.x}\n",
            {
                "o": {
                    "x": {"x": 2, "y": {"q": 2, "x": 2, "y": {}, "z": {"x": 2, "y": {}}}},
                    "y": {"q": 2, "x": 2, "y": {}, "z": {"x": 2, "y": {}}},
                }
            },
        ),
    ],
    ids=["r3c", "r3b-plus-q"],
)
def test_formerly_growing_cycle_resolves(src: str, want: object) -> None:
    assert _json(src) == want


def test_limits_spare_acyclic_configs() -> None:
    # The §10.3 limits count only in the region of a cycle break, so large
    # acyclic configs are never charged: an exponential chain of references
    # (billion laughs, N=12) and deeply nested objects.
    src = "a0 = { v = 1 }\n" + "".join(
        f"a{i} = {{ x = ${{a{i - 1}}}, y = ${{a{i - 1}}} }}\n" for i in range(1, 13)
    )
    leaf = _json(src)
    for _ in range(12):
        assert isinstance(leaf, dict)
        leaf = leaf["a12"]["x"] if "a12" in leaf else leaf["x"]
    assert leaf == {"v": 1}
    deep = _json("a { " * 250 + "x = 1" + " }" * 250 + "\n")
    for _ in range(250):
        assert isinstance(deep, dict)
        deep = deep["a"]
    assert deep == {"x": 1}
    path = _json(".".join(["a"] * 200) + " = 1\n")
    for _ in range(199):
        assert isinstance(path, dict)
        path = path["a"]
    assert path == {"a": 1}


def test_doubling_array_ring_resolves() -> None:
    # A 16-key ring of `[${?next}, ${?next}]` written twice. Resolved values
    # are shared, so it resolves, as in Lightbend and the reference model
    # (#68's value budget raised here).
    n = 16
    ring = "".join(f"a{i} = [${{?a{(i + 1) % n}}}, ${{?a{(i + 1) % n}}}]\n" for i in range(n))
    got = _json(ring + ring)
    assert isinstance(got, dict) and len(got) == n


def test_doubling_string_ring_fails_without_exhausting_memory() -> None:
    # A 16-key ring of `${?next}${?next}x` written twice: the string doubles
    # on every lap (Lightbend 1.4.10: OutOfMemoryError; the reference model
    # does not finish). The §10.3 weight limit stops it while it is built.
    n = 16
    ring = "".join(f"a{i} = ${{?a{(i + 1) % n}}}${{?a{(i + 1) % n}}}x\n" for i in range(n))
    with pytest.raises(ResolutionLimitError, match="weight units"):
        hocon.parse_string(ring + ring, env={})


# Counterexamples from review of #68's guard, re-pinned to the reference model
# (Lightbend 1.4.10 agrees): cx1 resolves, and cx2 writes `+=` inside a list,
# a parse error (resolution-model §2.3).
_CX1 = (
    "a.a = ${?b}\nc.b { b { a += x, b += ${?a}, a += [${?c}] } }\nc.b { b { a"
    " += [] } }\na = ${c}\na = ${?a}\n"
)
_CX1_WANT = (
    '{"a":{"b":{"b":{"a":["x",[{"b":{"b":{"a":["x"],"b":[{}]}}}],[]],"b":[{}]}}},'
    '"c":{"b":{"b":{"a":["x",[{"b":{"b":{"a":["x"],"b":[{}]}}}],[]],"b":[{}]}}}}'
)
_CX2 = (
    "b += { b { a { a = ${?c} }, a += [{ a = 1 }] }, b += { b { b { a = 1 }"
    " ${?a}, a { a = 1 } } } } { b += 2, b = [[${?c}]] }\nc = [${?b}]\nc = ${"
    "?b}\na.a.a = ${?c}\nb += { b { a { a { a = 1 } }, a += [{ a = 1 }] }, b "
    "+= { b { b { a = 1 } { a = 1 } } } }\n"
)


def test_review_counterexamples() -> None:
    assert _json(_CX1) == json.loads(_CX1_WANT)
    with pytest.raises(hocon.ParseError):
        _json(_CX2)


# Inputs that failed fast before #68's guard and hung with an early version of
# it. They must fail fast.
_S16427 = (
    "o.o = { o = ${?o.a} ${?o.o} }\no.b = ${o.b}x\no.o.a = ${o.o.a} y\no.o.a +"
    "= ${?o}[1]\no.o.a = x${?o.o}\no.a = ${o.o.a}y\no.o.a = ${o.o.a} y\no.o.a +"
    "= ${?o}[1]\no.o.a = x${?o.o}\no.a = ${o.o.a}y\no.o.a = x${?o.o}\no.o.a = $"
    "{o.o.a} y\no.o.a += ${?o}[1]\no.o.a = x${?o.o}\no.a = ${o.o.a}y\n"
)
_H04998 = (
    "o.y = ${o.y} ${o.y}\nb = ${a}${b}\no.y.z = ${?o.y.z}${?o}\no.x = ${o.x} y"
    "\no.y.z += ${?o.y.z} ${?c}\no.x = ${o.x}\no.y.z = ${?o.y.z}${?o}\no.x = ${"
    "o.x} y\no.y.z += ${?o.y.z} ${?c}\no.x = ${o.x}\no.y.z = ${?o.y.z}${?o}\no."
    "x = ${o.x} y\no.y.z += ${?o.y.z} ${?c}\no.x = ${o.x}\no.x = ${o.x}x\no.y.z"
    " = ${o.y.z} y\n"
)


def test_former_fast_errors_still_fail() -> None:
    with pytest.raises(ResolveError, match="circular substitution"):
        hocon.parse_string(_S16427, env={})
    # Re-pinned (was the recursion-limit ParseError): Lightbend 1.4.10 and the
    # reference model find ${o.y} undefined.
    with pytest.raises(ResolveError, match="could not resolve substitution"):
        hocon.parse_string(_H04998, env={})


def _wide_reference() -> str:
    # w8: a two-key cycle written twice, each value referencing the other key
    # eight times.
    a = "a = " + "${?b}" * 8 + "\n"
    b = "b = " + "${?a}" * 8 + "\n"
    return (a + b) * 2


def _dense_cycle() -> str:
    # e6: six keys, written twice, each referencing all six.
    refs = "".join(f"${{?k{j}}}" for j in range(1, 7))
    return "".join(f"k{i} = {refs}\n" for i in range(1, 7)) * 2


def _object_ring() -> str:
    # ring_obj16_keys64 (§10.3 probes): a 16-key ring of objects with 64-byte
    # keys, written twice. Keys carry no weight, so the outcome is that of the
    # same ring with one-letter keys. (#68 pinned a variant next to a
    # 10,000-item list; B grows with the document, so that one now loads.)
    x, y = "x" * 64, "y" * 64
    ring = "".join(
        f"a{i} = {{ {x} = ${{?a{(i + 1) % 16}}}, {y} = ${{?a{(i + 1) % 16}}} }}\n"
        for i in range(16)
    )
    return ring * 2


def test_wide_reference_cycle_resolves() -> None:
    # Re-pinned (#68's work budget raised here): the model resolves it to {}.
    assert _json(_wide_reference()) == {}


@pytest.mark.parametrize(
    "build",
    [_dense_cycle, _object_ring],
    ids=["dense-cycle", "object-ring"],
)
def test_post_cut_work_is_bounded(build: object) -> None:
    # A cycle that keeps branching runs for minutes in the reference model and
    # in Lightbend, and a ring of objects doubles its written-out size on every
    # lap (review of the rs memory exhaustion: 1–3 GB from 20 KB). Each fails
    # with the §10.3 limit (lookups and weight respectively).
    assert callable(build)
    with pytest.raises(ResolutionLimitError, match="resolution limit exceeded after a cycle break"):
        hocon.parse_string(build(), env={})


# Inputs that pinned the state components of #68's prior re-entry guard. The
# guard is gone; the inputs stay as regressions, re-pinned to the reference
# model (Lightbend 1.4.10 agrees on each).
_STATE_PREFIX_PRIOR_SRC = "x = ${a}\nx = ${a}\na = ${?x.y}\na = ${?a}ok\n"
_STATE_CONCAT_SRC = "a = 5\na.a += { a = ${?a} }\na.a += ${?b.a}\n"
_STATE_SCOPE_SRC = (
    "b += { b += { a = { a = ${?c}, a = { a = 1 } ${?c} }, a += { a = ${?a}"
    "x } }, b = { b = { b = { a = 1 } ${?a}, a = ${?c} }, a += [{ a = 1 } $"
    "{a}] }, b += { b = { b += { a = 1 } ${?a}, b = 2, a += { a = 1 } ${?a."
    "a} } } }\na.a.a = { b += 2, b = [[${?c}]] }\nc = [${?b}]\nc = ${?b}\na.a.a"
    " = ${?c}\nb += { b += { a = { a = ${?c}, a = { a = 1 } ${?c} }, a += { "
    "a = ${?a}x } }, b = { b = { b = { a = 1 } ${?a}, a = ${?c} }, a += [{ "
    "a = 1 } ${a}] }, b += { b = { b += { a = 1 } ${?a}, b = 2, a += { a = "
    "1 } ${?a.a} } } }\na.a.a = { b += 2, b = [[${?c}]] }\nc = [${?b}]\nc = ${"
    "?b}\na.a.a = ${?c}\nb.a = [${?b}]\n"
)
_STATE_FIELD_PATH_SRC = (
    "o = { b = ${?o}${?o.b} }\na.a = { a = { a += { a = 1 } ${?o}, a = { a ="
    " 1 } ${?a.a} } }\no = { b = ${?o}${?o.b} }\na.a = { a = { a += { a = 1 }"
    " ${?o}, a = { a = 1 } ${?a.a} } }\n"
)


def test_former_guard_state_inputs() -> None:
    with pytest.raises(ResolveError, match="circular substitution"):
        _json(_STATE_PREFIX_PRIOR_SRC)
    assert _json(_STATE_CONCAT_SRC) == {"a": {"a": []}}
    with pytest.raises(hocon.ParseError):  # `+=` inside a list (§2.3)
        _json(_STATE_SCOPE_SRC)
    with pytest.raises(ResolveError, match="cannot concatenate"):
        _json(_STATE_FIELD_PATH_SRC)


def test_snapshot_cost_stays_small_with_long_keys() -> None:
    # pd_120_2000: a 121-step chain over 2,000-byte keys leading into the dense
    # 6-key cycle. The snapshot is built from frozensets of keys and identities,
    # so long keys do not make each guard entry expensive (rs had to bound its
    # snapshot cost); it ends in the §10.3 lookup limit.
    q = "q" * 2000
    chain = "".join(f"{q}{i} = ${{{q}{i + 1}}}\n" for i in range(120)) + f"{q}120 = ${{k1}}\n"
    refs = "".join(f"${{?k{j}}}" for j in range(1, 7))
    dense = "".join(f"k{i} = {refs}\n" for i in range(1, 7)) * 2
    with pytest.raises(ResolutionLimitError, match="lookups"):
        hocon.parse_string(chain + dense, env={})
