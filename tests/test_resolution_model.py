"""Per-implementation pins of xx.hocon ``docs/resolution-model.md`` (#67 window).

The ``resolution-model/`` fixture group covers the hermetic cases. This file
holds what a fixture cannot:

- **§6.3 interim values.** Until window step (b) adds E23 rule 1, a cycle is
  broken by the innermost active substitution (Lightbend's rule). The spec
  pins the interim value of each #128 row; every implementation must give
  exactly these. The E23 final values are strict xfails, so step (b) turns
  them into failures to flip.
- **Environment cases.** The ``resolution-model/`` group is hermetic, so the
  own-path environment fallback (§4.4) and J5 are checked here. Values are
  the reference model's (``generate/reference-model``, window corpus).
"""

from __future__ import annotations

from typing import Any

import pytest

from hocon import NotResolvedError, ResolveError, from_map, parse


def _resolve(src: str, env: dict[str, str] | None = None) -> Any:
    return parse(src, env=env or {}).to_object()


ERR = "ERR"

# (zig-hocon row, source, interim value, E23 final value) — resolution-model
# §6.3 "Pinned interim values". The rows' text is the zig-hocon conformance
# suite's (plus-equals-field-separator/…, self-referential-examples/…).
_INTERIM_ROWS: list[tuple[str, str, Any, Any]] = [
    ("024", "e += ${?c}\ne += ${?c}\nc = ${e}", ERR, {"e": [[]], "c": []}),
    ("025", "c = ${e}\ne += ${?c}\ne += ${?c}", ERR, {"e": [[]], "c": []}),
    ("026", "a += ${?b}\nb += ${?a}", {"a": [[]], "b": []}, {"a": [[]], "b": []}),
    ("027", "b += ${?a}\na += ${?b}", {"b": [[]], "a": []}, {"b": [[]], "a": []}),
    ("039", "v { x = ${?r} }\nr = ${v}", ERR, {"v": {}, "r": {}}),
    ("045", "d = yes${?c}\nc = ${d}", ERR, {"d": "yes", "c": "yes"}),
    ("046", "e += ${?c}\nc = ${e}", ERR, {"e": [], "c": []}),
    ("057", "b = [${?a}]\na = [${?b}]", {"b": [[]], "a": []}, {"b": [[]], "a": []}),
    ("063", "d = [${?c}]\nc = ${?d}", {"d": []}, {"d": []}),
    ("064", "c = ${?d}\nd = [${?c}]", {"c": [], "d": []}, {"c": [], "d": []}),
    ("065", "e = x${?c}\ne = ${e}y${?c}\nc = ${e}", ERR, {"e": "xyx", "c": "x"}),
    ("066", "c = ${e}\ne = x${?c}\ne = ${e}y${?c}", ERR, {"e": "xyx", "c": "x"}),
    # #127 rows 022 / 023 need no cycle break in this model.
    ("022", "b.c += ${y}\nb.c += 2\ny = [1, ${?b}]", {"b": {"c": [[1], 2]}, "y": [1]}, None),
    ("023", "y = [1, ${?b}]\nb.c += ${y}\nb.c += 2", {"b": {"c": [[1], 2]}, "y": [1]}, None),
    # rv121 (resolution-model/rv121-e23-x5-pending-step-b): E23's own example.
    ("rv121", "a = ${?b} {y = 1}\nb = ${a.y}", ERR, {"a": {"y": 1}, "b": 1}),
]


def _outcome(src: str) -> Any:
    try:
        return _resolve(src)
    except ResolveError:
        return ERR


@pytest.mark.parametrize(
    "src,interim", [pytest.param(s, i, id=r) for r, s, i, _ in _INTERIM_ROWS]
)
def test_interim_value(src: str, interim: Any) -> None:
    assert _outcome(src) == interim


@pytest.mark.parametrize(
    "src,final",
    [
        pytest.param(
            s,
            f,
            id=r,
            marks=pytest.mark.xfail(
                strict=True, reason="pending step (b), E23 rule 1 (resolution-model §6.3)"
            ),
        )
        for r, s, i, f in _INTERIM_ROWS
        if f is not None and f != i
    ],
)
def test_e23_final_value(src: str, final: Any) -> None:
    assert _outcome(src) == final


# (case, source, env, value) — the window corpus' environment cases.
_ENV_CASES: list[tuple[str, str, dict[str, str], Any]] = [
    (
        "db-url-env",
        "db { host = localhost, port = 5432 }\ndb.host = ${?X}\ndb.port = ${?Y}\n"
        'url = "jdbc://"${db.host}":"${db.port}',
        {"X": "dbhost"},
        {"db": {"host": "dbhost", "port": 5432}, "url": "jdbc://dbhost:5432"},
    ),
    # §4.4 own-path exception: the bottom entry's own reference reads the env.
    ("own-path-env", "X = ${X}\nX = {x: 1}", {"X": "seed"}, {"X": {"x": 1}}),
    ("own-path-bottom", "a = ${a}\na = {k : 1}", {"a": "seed"}, {"a": {"k": 1}}),
    (
        "own-path-bottom-concat",
        'a = ${a}"-suffix"\na = ${?nope}',
        {"a": "seed"},
        {"a": "seed-suffix"},
    ),
    # E23-am3: a single `a = ${a}` is a cycle even with `a` set.
    ("single-self-ref", "a = ${a}", {"a": "seed"}, ERR),
    # J5: an alias reaching an EMPTY field is first looked up as absent, so
    # the environment answers (Lightbend gives the same in key-hash order).
    (
        "alias-reaches-empty",
        "a : ${b}\na : {k : 1}\nb = ${a}",
        {"a": "bar"},
        {"a": {"k": 1}, "b": "bar"},
    ),
    (
        "alias-reaches-empty-2",
        "foo : ${p}\nfoo : {a : 1}\np = ${foo}",
        {"foo": "bar"},
        {"foo": {"a": 1}, "p": "bar"},
    ),
]


@pytest.mark.parametrize(
    "src,env,want",
    [pytest.param(s, e, w, id=c) for c, s, e, w in _ENV_CASES],
)
def test_environment_case(src: str, env: dict[str, str], want: Any) -> None:
    try:
        got = _resolve(src, env)
    except ResolveError:
        got = ERR
    assert got == want


# --- deferred API (E12) on top of the stacks ---


def test_resolve_with_keeps_only_the_receivers_keys_for_a_stacked_field() -> None:
    # The receiver's `a` has two assignments. Its key shape is the union of
    # its object entries, so the source's own `a.q` is not copied into the
    # result (E12 decision 9).
    receiver = parse("a = ${x}\na = {p = 1}", resolve_substitutions=False)
    source = from_map({"a": {"q": 2, "p": 0}, "x": {"y": 1}})
    assert receiver.resolve_with(source).to_object() == {"a": {"p": 1}}


def test_resolve_with_keeps_what_a_receiver_substitution_brings_in() -> None:
    # The top of the receiver's `a` is a substitution, so its whole resolved
    # value is kept, including `c` from the source's `template`.
    receiver = parse("a = {b = 1}\na = ${template}", resolve_substitutions=False)
    source = from_map({"template": {"c": 2}})
    assert receiver.resolve_with(source).to_object() == {"a": {"b": 1, "c": 2}}


def test_allow_unresolved_still_aborts_on_a_cycle_after_an_unresolved_piece() -> None:
    with pytest.raises(ResolveError, match="cycle"):
        parse("a = ${missing}${a}", resolve_substitutions=False).resolve(allow_unresolved=True)


def test_allow_unresolved_concatenation_of_an_unresolved_object_stays_unresolved() -> None:
    cfg = parse("a = {x = ${nope}}\nb = ${a} [1]", resolve_substitutions=False).resolve(
        allow_unresolved=True
    )
    assert not cfg.is_resolved()
    with pytest.raises(NotResolvedError):
        cfg.get("b")


def test_allow_unresolved_field_whose_walk_reaches_an_undefined_substitution() -> None:
    # Lightbend keeps the whole delayed merge unresolved; py used to answer
    # with the object layer alone.
    cfg = parse("a = ${nope}\na = {x = 1}", resolve_substitutions=False).resolve(
        allow_unresolved=True
    )
    assert not cfg.is_resolved()
    with pytest.raises(NotResolvedError):
        cfg.get("a")
