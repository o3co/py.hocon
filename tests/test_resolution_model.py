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

# allow_unresolved without the process environment, so a variable that
# happens to be named like a missing key cannot change a test.
_PARTIAL: dict[str, bool] = {"allow_unresolved": True, "use_system_environment": False}


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


@pytest.mark.parametrize("src,interim", [pytest.param(s, i, id=r) for r, s, i, _ in _INTERIM_ROWS])
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
        parse("a = ${missing}${a}", resolve_substitutions=False).resolve(**_PARTIAL)


def test_allow_unresolved_concatenation_of_an_unresolved_object_stays_unresolved() -> None:
    cfg = parse("a = {x = ${nope}}\nb = ${a} [1]", resolve_substitutions=False).resolve(**_PARTIAL)
    assert not cfg.is_resolved()
    with pytest.raises(NotResolvedError):
        cfg.get("b")


def test_allow_unresolved_field_whose_walk_reaches_an_undefined_substitution() -> None:
    # Lightbend keeps the whole delayed merge unresolved; py used to answer
    # with the object layer alone.
    cfg = parse("a = ${nope}\na = {x = 1}", resolve_substitutions=False).resolve(**_PARTIAL)
    assert not cfg.is_resolved()
    with pytest.raises(NotResolvedError):
        cfg.get("a")


@pytest.mark.parametrize(
    "src",
    ["a.x.y = ${?unset}\nb = ${?a.x.y}", "b = ${?a.x.y}\na.x.y = ${?unset}"],
    ids=["reader-last", "reader-first"],
)
def test_j2_presence_on_the_whole_raw_path_ignores_the_environment(src: str) -> None:
    # §5.3 / J2 (rv127 / rv128 with the environment set): a.x.y is
    # raw-present, so it is found, resolves to nothing, and §7.2 never reaches
    # the environment, in both line orders.
    assert _resolve(src, {"a.x.y": "ENV"}) == {"a": {"x": {}}}


# --- §10.2: shapes that must not nest the interpreter's stack ---


def test_long_object_concatenation_is_one_overlay() -> None:
    # 1,200 `${base}` pieces: each object join goes on top of one overlay
    # instead of nesting one overlay per piece.
    src = "base = {x: 1}\na = " + " ".join(["${base}"] * 1200) + "\n"
    assert _resolve(src)["a"] == {"x": 1}


def test_deep_object_substitution_resolves() -> None:
    # A 350-level object read through a substitution: "resolved" is computed
    # without recursion, and §5.5 asks for it only per child.
    path = ".".join(f"k{i}" for i in range(350))
    got = _resolve(f"a.{path} = 1\nb = ${{a}}\n")
    leaf = got["b"]
    for i in range(350):
        leaf = leaf[f"k{i}"]
    assert leaf == 1


# --- §3.4 / §10.1: a merged-leaf alias stays a merged leaf (xx.hocon#142) ---


def test_merged_leaf_alias_terminates() -> None:
    # rv132: the alias of a merged leaf used to be keyed as a fresh document
    # slot at every rebuild, so the cycle markers had no bound and this
    # cycle-free config recursed without end. Lightbend 1.4.10: [a, b, c].
    src = (
        "app = ${?overrides}\n"
        "app { opts { flags = [], flags += a } }\n"
        "app { opts { flags += b, flags += c } }\n"
    )
    assert _resolve(src) == {"app": {"opts": {"flags": ["a", "b", "c"]}}}


# --- §10.2 item 5: "resolved" without a field map ---


def test_resolved_question_builds_no_field_map() -> None:
    from hocon._internal.resolver.merge import Overlay
    from hocon._internal.resolver.values import Obj, Patch, Scalar, Slot, Subst

    def obj(**fields: object) -> Obj:
        return Obj({k: Slot(k, [v], (k,)) for k, v in fields.items()})  # type: ignore[list-item]

    base = obj(**{f"k{i}": Scalar(str(i), "number", False) for i in range(100)})
    pending = obj(u=Subst(("nope",), True))
    overlay = Overlay([pending, base])
    assert not overlay.is_resolved()
    assert overlay._fields is None  # answered from the unresolved keys only
    assert list(overlay._cache) == ["u"]  # no resolved key was even merged
    # A patch whose base is unresolved only in the key it replaces.
    rest = {f"k{i}": Scalar(str(i), "number", False) for i in range(1, 100)}
    unresolved_base = obj(k0=Subst(("nope",), True), **rest)
    patch = Patch(unresolved_base, "k0", Slot("k0", [Scalar("x", "string", True)], ("k0",)))
    assert patch.is_resolved()
    assert patch._fields is None


# --- review threads on #67 (each against Lightbend 1.4.10) ---


@pytest.mark.parametrize(
    "src",
    ["a { x = ${missing} }\nb = ${a.x}", "b = ${a.x}\na { x = ${missing} }"],
    ids=["reader-last", "reader-first"],
)
def test_allow_unresolved_reads_a_memoized_unresolved_leaf(src: str) -> None:
    # Reading a.x after `a` was memoized with an unresolved leaf used to raise
    # "internal: cannot resolve Unresolved" in one line order. Lightbend
    # leaves both a.x and b unresolved.
    cfg = parse(src, resolve_substitutions=False).resolve(**_PARTIAL)
    assert not cfg.is_resolved()
    with pytest.raises(NotResolvedError):
        cfg.get("b")


def test_allow_unresolved_still_rejects_a_known_concatenation_type_error() -> None:
    # The object and the quoted string can never join, whatever ${missing}
    # becomes: Lightbend raises WrongType here even under allowUnresolved.
    src = 'a = ${missing}${obj}${text}\nobj = {p = 1}\ntext = "x"'
    with pytest.raises(ResolveError, match="cannot concatenate"):
        parse(src, resolve_substitutions=False).resolve(**_PARTIAL)


def test_deferred_merge_keeps_an_unquoted_whitespace_value() -> None:
    # `x` resolves to unquoted whitespace, which a list drops (§1.3 rule 3).
    # A resolved Config handed to with_fallback keeps it unquoted, as one
    # parse of the same text does (Lightbend gives a = [1] both ways).
    one_go = parse("a = [1]${x}\nx = ${?p} ${?q}", env={}).to_object()
    fallback = parse("x = ${?p} ${?q}", env={})
    deferred = (
        parse("a = [1]${x}", resolve_substitutions=False)
        .with_fallback(fallback)
        .resolve(use_system_environment=False)
        .to_object()
    )
    assert one_go == deferred == {"a": [1], "x": " "}


def test_resolved_config_keeps_ignoring_fallbacks() -> None:
    # `a = null` / `a = {x = 1}` makes `a` ignore fallbacks (F6). That holds
    # for a resolved Config too, so a later with_fallback adds nothing to `a`
    # (Lightbend: {a: {x: 1}} deferred or resolved first).
    fb = from_map({"a": {"helper": 0}})
    deferred = parse("a = null\na = {x = 1}", resolve_substitutions=False).with_fallback(fb)
    resolved_first = parse("a = null\na = {x = 1}").with_fallback(fb)
    assert deferred.resolve().to_object() == {"a": {"x": 1}}
    assert resolved_first.resolve().to_object() == {"a": {"x": 1}}


@pytest.mark.parametrize(
    ("src", "want"),
    [
        ("d { x = [] }\nc = ${d}\nc { x += 1, x += 2 }", {"d": {"x": []}, "c": {"x": [1, 2]}}),
        ("d { x = [0] }\nc = ${d}\nc { x += 1, x += 2 }", {"d": {"x": [0]}, "c": {"x": [0, 1, 2]}}),
        # Keys renamed so that Lightbend's hash order is the document order.
        ("a { x = [] }\nb = ${a}\nb { x += 1, x += 2 }", {"a": {"x": []}, "b": {"x": [1, 2]}}),
    ],
    ids=["pe013", "pe013-nonempty-base", "pe013-renamed"],
)
def test_look_back_through_a_merged_leaf(src: str, want: object) -> None:
    # zig-hocon plus-equals-field-separator/013 (§3.5, J3; rv125 / rv126).
    assert _resolve(src) == want


@pytest.mark.parametrize(
    "src",
    ["a = { b: 1 } x", "a = [1] x", "x = s\nc = [1] ${x}"],
    ids=["object-then-text", "list-then-text", "substituted-text"],
)
def test_text_after_a_list_or_object_is_an_error(src: str) -> None:
    # §1.3 rule 3 / E5 option (B): only whitespace is dropped, at parse time
    # and when resolving alike (Lightbend 1.4.10).
    with pytest.raises(ResolveError, match="cannot concatenate"):
        _resolve(src)


_FB_HELPER = {"a": {"helper": 0}}


def test_resolve_with_result_keeps_ignoring_fallbacks() -> None:
    # resolve_with rebuilds the receiver's objects; `a` still ignores a later
    # fallback (Lightbend 1.4.10: {a: {x: 1}, b: 1}).
    cfg = parse("a = null\na = {x = 1}\nb = ${c}", resolve_substitutions=False)
    got = cfg.resolve_with(from_map({"c": 1})).with_fallback(from_map(_FB_HELPER)).resolve()
    assert got.to_object() == {"a": {"x": 1}, "b": 1}


def test_unresolved_parse_keeps_ignoring_fallbacks() -> None:
    # A Config read from an unresolved tree (get_config of a deferred parse).
    cfg = parse("p { a = null\na = {x = 1} }", resolve_substitutions=False)
    got = cfg.get_config("p").with_fallback(from_map(_FB_HELPER)).resolve()
    assert got.to_object() == {"a": {"x": 1}}


def test_allow_unresolved_result_keeps_ignoring_fallbacks() -> None:
    # A partially resolved Config: its resolved part is copied without the
    # unresolved values, and `a` still ignores fallbacks.
    cfg = parse("a = null\na = {x = 1}\nb = ${missing}", resolve_substitutions=False)
    partial = cfg.resolve(**_PARTIAL)
    got = partial.get_config("a").with_fallback(from_map({"helper": 0})).resolve()
    assert got.to_object() == {"x": 1}


def test_allow_unresolved_partial_concatenation_is_joined_again() -> None:
    # `${a}` is a partial concatenation ({p: 1} after an unresolved piece);
    # joined with "x" it is a type error whatever ${missing} becomes
    # (Lightbend flattens it and raises WrongType).
    src = 'a = ${missing} {p = 1}\nb = ${a} "x"'
    with pytest.raises(ResolveError, match="cannot concatenate"):
        parse(src, resolve_substitutions=False).resolve(**_PARTIAL)


def test_merge_with_unhashable_public_value_subclasses() -> None:
    # The resolver's marks on public values are kept by identity, so a value
    # subclass that defines __eq__ without __hash__ still merges.
    from hocon import Config
    from hocon.value import HoconObject, HoconScalar

    class Scalar(HoconScalar):
        def __eq__(self, other: object) -> bool:
            return isinstance(other, HoconScalar) and other.raw == self.raw

    class Obj(HoconObject):
        def __eq__(self, other: object) -> bool:
            return isinstance(other, HoconObject) and other.fields == self.fields

    cfg = Config(Obj({"a": Scalar("1", "number")}))
    assert cfg.with_fallback(from_map({"b": 2})).resolve().to_object() == {"a": 1, "b": 2}
