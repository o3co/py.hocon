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
        "prefix-prior-two-element-path",
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


_R3 = (
    "o.x = 2\n"
    "o.x = ${?o}\n"
    "o.y = { z = ${?o.y.z} }\n"
    "o.y.z = ${?o}\n"
    "o.x = ${?o.x}\n"
    "o.y = { x = ${?o.y} }\n"
)


@pytest.mark.parametrize(
    "src",
    [
        # r3c from review: the prior guard stops the cycle, but only after the
        # value has nested deeply enough to build megabytes and burn minutes.
        _R3 + "o.y = { q = ${?o.y.z} }\n",
        # r3b with `o.y.q = ${?o.x}` written twice.
        _R3 + "o.y = ${?o.y.z}\no.y.q = ${?o.x}\no.y.q = ${?o.x}\n",
    ],
    ids=["r3c", "r3b-plus-q"],
)
def test_value_budget_stops_a_growing_cycle(src: str) -> None:
    # The value budget (rs.hocon#199 counterpart) turns it into an error.
    # Both raised the recursion-limit ParseError before the guard.
    with pytest.raises(ResolveError, match="resolved value too large"):
        hocon.parse_string(src, env={})


def test_value_budget_spares_acyclic_configs() -> None:
    # The budget applies only after the guard has cut a cycle, so large
    # acyclic configs that load today are never charged: an exponential chain
    # of references (billion laughs, N=12) and deeply nested objects.
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


@pytest.mark.parametrize(
    ("name", "element"),
    [("array", "[${?a%}, ${?a%}]"), ("string", "${?a%}${?a%}x")],
)
def test_doubling_ring_fails_without_exhausting_memory(name: str, element: str) -> None:
    # A 16-key ring written twice whose value doubles on every lap (review of
    # go.hocon#223 / rs.hocon#203: the string ring took 4 GB in py, a model of
    # the array ring reaches 17 billion nodes). Before the guard it was a
    # recursion-limit ParseError. After a cut every substitution result is
    # charged as it is produced and the substitutions resolved are counted, so
    # the ring is stopped while it is being built.
    n = 16
    ring = "".join(f"a{i} = {element.replace('%', str((i + 1) % n))}\n" for i in range(n))
    with pytest.raises(
        (ResolveError, hocon.ParseError),
        match="resolved value too large|too complex to resolve|nested too deeply",
    ):
        hocon.parse_string(ring + ring, env={})


def test_document_walks_visit_shared_children_once() -> None:
    # Current values and saved priors share children. Overriding nested
    # prefixes from the deepest to the shallowest gives a document whose
    # tree, unshared, is exponential in its depth: here 2**60 paths. The walks
    # that size the guard state and the value budget must stay linear.
    from hocon._internal.resolver import substitution_resolver as sr
    from hocon._internal.resolver.types import ResObj
    from hocon.value import HoconScalar

    node = ResObj()
    node.fields["v"] = HoconScalar("1", "number")
    for _ in range(60):
        parent = ResObj()
        parent.fields["k"] = node
        parent.prior_values["k"] = node
        node = parent
    assert sr._max_subst_len(node) == 0
    assert sr._source_nodes(node) == 62


# Counterexamples from review of the py guard: each loads today, and each is
# cut by the guard. They pin the py-specific parts of the guard state: the
# concatenations mid-iteration and the scope (a state without them changed
# both results).
_CX1 = (
    "a.a = ${?b}\nc.b { b { a += x, b += ${?a}, a += [${?c}] } }\nc.b { b { a"
    " += [] } }\na = ${c}\na = ${?a}\n"
)
_CX1_WANT = (
    '{"a":{"b":{"b":{"a":["x",[{"b":{"b":{"a":["x",[]],"b":[["x"],["x"]]}}}'
    '],[]],"b":[["x"],["x",[{"b":{"b":{"a":["x",[]],"b":[["x"],["x"]]}}}]]]'
    '}}},"c":{"b":{"b":{"a":["x",[{"b":{"b":{"a":["x",[{"b":{"b":{"a":["x",'
    '[]],"b":[["x"],{"b":{"b":{"a":["x",[{"b":{"b":{"a":["x",[]],"b":[["x"]'
    ',["x"]]}}}],[]],"b":[["x"],["x",[{"b":{"b":{"a":["x",[]],"b":[["x"],["'
    'x"]]}}}]]]}}}]}}}],[]],"b":[["x"],{"b":{"b":{"a":["x",[{"b":{"b":{"a":'
    '["x",[]],"b":[["x"],["x"]]}}}],[]],"b":[["x"],["x",[{"b":{"b":{"a":["x'
    '",[]],"b":[["x"],["x"]]}}}]]]}}}]}}}],[]],"b":[{"b":{"b":{"a":["x",[{"'
    'b":{"b":{"a":["x",[]],"b":[["x"],["x"]]}}}],[]],"b":[["x"],["x",[{"b":'
    '{"b":{"a":["x",[]],"b":[["x"],["x"]]}}}]]]}}}]}}}}'
)
_CX2 = (
    "b += { b { a { a = ${?c} }, a += [{ a = 1 }] }, b += { b { b { a = 1 }"
    " ${?a}, a { a = 1 } } } } { b += 2, b = [[${?c}]] }\nc = [${?b}]\nc = ${"
    "?b}\na.a.a = ${?c}\nb += { b { a { a { a = 1 } }, a += [{ a = 1 }] }, b "
    "+= { b { b { a = 1 } { a = 1 } } } }\n"
)
_CX2_WANT = (
    '{"a":{"a":{"a":[{"b":[[[{"b":[[[[2]]]]}]]]},{"b":[{"b":{"b":{"a":1}}}]'
    '}]}},"b":[{"b":[[[{"b":[[[[2]]]]}]]]},{"b":[{"b":{"b":{"a":1}}}]}],"c"'
    ':[{"b":[[[{"b":[[[[2]]]]}]]]},{"b":[{"b":{"b":{"a":1}}}]}]}'
)


@pytest.mark.parametrize(
    ("src", "want"), [(_CX1, _CX1_WANT), (_CX2, _CX2_WANT)], ids=["cx1", "cx2"]
)
def test_cut_config_that_loads_reads_the_same(src: str, want: str) -> None:
    assert _json(src) == json.loads(want)


# Inputs that failed fast before the guard and hung after it, until the state
# held the concatenations and the scope. They must fail fast, as before.
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
    with pytest.raises(hocon.ParseError, match="nested too deeply"):
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


def _padded_object_ring() -> str:
    # objring_64_p10000: a 10,000-element array inflates the document's node
    # count (and so the uncapped value budget), next to a 16-key ring of
    # objects with 64-byte keys, written twice.
    pad = "pad = [" + ",".join(["1"] * 10_000) + "]\n"
    x, y = "x" * 64, "y" * 64
    ring = "".join(
        f"a{i} = {{ {x} = ${{?a{(i + 1) % 16}}}, {y} = ${{?a{(i + 1) % 16}}} }}\n"
        for i in range(16)
    )
    return pad + ring * 2


@pytest.mark.parametrize(
    "build",
    [_wide_reference, _dense_cycle, _padded_object_ring],
    ids=["wide-reference", "dense-cycle", "padded-object-ring"],
)
def test_post_cut_work_is_bounded(build: object) -> None:
    # Review of the rs memory exhaustion: before the value budget was capped
    # and counted key text, a 20 KB input could reach 1–3 GB; a cycle that
    # keeps branching could run for seconds. Each must now fail with one of
    # the two post-cut limits.
    assert callable(build)
    with pytest.raises(ResolveError, match="too complex to resolve|resolved value too large"):
        hocon.parse_string(build(), env={})


# Each state component of the prior re-entry guard is load-bearing: removing
# it alone changes the result below (verified by building the resolver with
# that component replaced by a constant). Review of the py guard.

# The S13a.12 prefix-prior guard set. Loads in base as shown. Without the
# prefix-prior set the guard cuts the second pass and it becomes
# `circular substitution: a`.
_STATE_PREFIX_PRIOR_SRC = "x = ${a}\nx = ${a}\na = ${?x.y}\na = ${?a}ok\n"
_STATE_PREFIX_PRIOR_WANT = '{"a":"ok","x":"ok"}'

# The concatenations mid-iteration. A recursion-limit ParseError in base.
# Without the concat set one nested `{"a":5}` becomes `{}`.
_STATE_CONCAT_SRC = "a = 5\na.a += { a = ${?a} }\na.a += ${?b.a}\n"
_STATE_CONCAT_WANT = '{"a":{"a":[{"a":{"a":[{"a":{"a":[{"a":{"a":[{"a":5}]}},{"a":5}]}}]}}]}}'

# The scope (which picks the prior). Loads in base as shown. Without the
# scope one `[[[[2]]]]` becomes `[[[]]]`.
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
_STATE_SCOPE_WANT = (
    '{"a":{"a":{"a":[{"b":[{"b":{"a":[{"a":{"b":[[[[2]]]]}}],"b":2}}]},{"b"'
    ':[{"b":{"a":[{"a":{"b":[[[[2]]]]}}],"b":2}}]}]}},"b":{"a":[[{"b":[{"b"'
    ':{"a":[{"a":[{"b":[{"b":{"a":[{"a":{"b":[[[[2]]]]}}],"b":2}}]},{"b":[{'
    '"b":{"a":[{"a":{"b":[[[[2]]]]}}],"b":2}}]}]}],"b":2}}]},{"b":[{"b":{"a'
    '":[{"a":[{"b":[{"b":{"a":[{"a":{"b":[[[[2]]]]}}],"b":2}}]},{"b":[{"b":'
    '{"a":[{"a":{"b":[[[[2]]]]}}],"b":2}}]}]}],"b":2}}]}]]},"c":{"a":[[{"b"'
    ':[{"b":{"a":[{"a":[{"b":[{"b":{"a":[{"a":{"b":[[[[2]]]]}}],"b":2}}]},{'
    '"b":[{"b":{"a":[{"a":{"b":[[[[2]]]]}}],"b":2}}]}]}],"b":2}}]},{"b":[{"'
    'b":{"a":[{"a":[{"b":[{"b":{"a":[{"a":{"b":[[[[2]]]]}}],"b":2}}]},{"b":'
    '[{"b":{"a":[{"a":{"b":[[[[2]]]]}}],"b":2}}]}]}],"b":2}}]}]]}}'
)

# The truncated field path. A recursion-limit ParseError in base; no input in the 157,254-input
# differential that loads in base depends on the field path. Without it
# `"o":{"b":{"b":{"b":{}}}}` loses one level.
_STATE_FIELD_PATH_SRC = (
    "o = { b = ${?o}${?o.b} }\na.a = { a = { a += { a = 1 } ${?o}, a = { a ="
    " 1 } ${?a.a} } }\no = { b = ${?o}${?o.b} }\na.a = { a = { a += { a = 1 }"
    " ${?o}, a = { a = 1 } ${?a.a} } }\n"
)
_STATE_FIELD_PATH_WANT = '{"a":{"a":{"a":{"a":{"a":{"a":{"a":1}}}}}},"o":{"b":{"b":{"b":{}}}}}'


@pytest.mark.parametrize(
    ("src", "want"),
    [
        (_STATE_PREFIX_PRIOR_SRC, _STATE_PREFIX_PRIOR_WANT),
        (_STATE_CONCAT_SRC, _STATE_CONCAT_WANT),
        (_STATE_SCOPE_SRC, _STATE_SCOPE_WANT),
        (_STATE_FIELD_PATH_SRC, _STATE_FIELD_PATH_WANT),
    ],
    ids=["prefix-prior", "concat", "scope", "field-path"],
)
def test_each_guard_state_component_is_load_bearing(src: str, want: str) -> None:
    assert _json(src) == json.loads(want)


def test_snapshot_cost_stays_small_with_long_keys() -> None:
    # pd_120_2000: a 121-step chain over 2,000-byte keys leading into the dense
    # 6-key cycle. The snapshot is built from frozensets of keys and identities,
    # so long keys do not make each guard entry expensive (rs had to bound its
    # snapshot cost); it ends in the post-cut work limit.
    q = "q" * 2000
    chain = "".join(f"{q}{i} = ${{{q}{i + 1}}}\n" for i in range(120)) + f"{q}120 = ${{k1}}\n"
    refs = "".join(f"${{?k{j}}}" for j in range(1, 7))
    dense = "".join(f"k{i} = {refs}\n" for i in range(1, 7)) * 2
    with pytest.raises(ResolveError, match="too complex to resolve|resolved value too large"):
        hocon.parse_string(chain + dense, env={})
