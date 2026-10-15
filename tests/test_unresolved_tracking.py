"""E12 decision 12 — unresolved paths raise, resolved paths read.

Regression tests for two bugs (found in ts.hocon, reproduced in py):

(a) After ``resolve(allow_unresolved=True)`` the NotResolvedError checks used
    the pre-resolve tree, so a subtree that had resolved still raised.
(b) A placeholder left inside an array was not seen: ``is_resolved()`` was
    True after ``resolve(allow_unresolved=True)`` and the getters crashed.

Also pinned: ``get`` / ``config[path]`` / ``to_object`` raise
NotResolvedError on an unresolved path instead of reporting it absent.
"""

from __future__ import annotations

import pytest

from hocon import NotResolvedError, parse_string


def _partial(text: str) -> object:
    return parse_string(text, resolve_substitutions=False).resolve(allow_unresolved=True)


def test_a_resolved_subtree_reads_after_partial_resolve() -> None:
    cfg = parse_string(
        "a { x = ${v} }\nb { y = ${missing} }\nv = 1", resolve_substitutions=False
    ).resolve(allow_unresolved=True)
    assert not cfg.is_resolved()
    sub = cfg.get_config("a")
    assert sub.is_resolved()
    assert sub.to_object() == {"x": 1}
    assert cfg.get_value("a") is not None
    assert cfg.get("a") == {"x": 1}
    assert cfg.get_int("a.x") == 1
    with pytest.raises(NotResolvedError):
        cfg.get_config("b")


@pytest.mark.parametrize("text", ["a = [1, ${y}]\nb = 2", "a = [1, {x = ${y}}]\nb = 2"])
def test_b_placeholder_in_an_array_is_unresolved(text: str) -> None:
    cfg = parse_string(text, resolve_substitutions=False).resolve(allow_unresolved=True)
    assert not cfg.is_resolved()
    for read in (lambda: cfg.get_list("a"), lambda: cfg.get("a"), lambda: cfg["a"]):
        with pytest.raises(NotResolvedError):
            read()
    assert cfg.get("b") == 2
    with pytest.raises(NotResolvedError):
        cfg.to_object()


def test_unresolved_path_is_not_reported_absent_before_resolve() -> None:
    cfg = parse_string("a = [1, ${y}]\nb = { c = ${z} }\nd = 2", resolve_substitutions=False)
    assert not cfg.is_resolved()
    with pytest.raises(NotResolvedError):
        cfg.get("a")
    with pytest.raises(NotResolvedError):
        cfg["b"]
    with pytest.raises(NotResolvedError):
        cfg.get("b.c")
    with pytest.raises(NotResolvedError):
        cfg.to_object()
    assert cfg.get("d") == 2
    assert cfg.get("nope", "dflt") == "dflt"  # absent stays absent
    with pytest.raises(KeyError):
        cfg["nope"]


def test_partial_resolve_can_still_be_completed() -> None:
    cfg = parse_string(
        "a { x = ${v} }\nb { y = ${missing} }\nv = 1", resolve_substitutions=False
    ).resolve(allow_unresolved=True)
    done = cfg.with_fallback(parse_string("missing = 7")).resolve()
    assert done.to_object() == {"a": {"x": 1}, "b": {"y": 7}, "v": 1, "missing": 7}


def test_typed_getter_traverses_even_when_a_literal_dotted_key_exists() -> None:
    cfg = parse_string('"a.b" = 1\na.b { x = ${missing} }', resolve_substitutions=False)
    with pytest.raises(NotResolvedError):
        cfg.get_config("a.b")  # the nested a.b, which is unresolved
    assert cfg.get("a.b") == 1  # get() prefers the literal key, as before


@pytest.mark.parametrize("partial", [False, True])
def test_path_under_an_unresolved_value_is_unresolved_not_absent(partial: bool) -> None:
    cfg = parse_string("a = ${missing}", resolve_substitutions=False)
    if partial:
        cfg = cfg.resolve(allow_unresolved=True)
    with pytest.raises(NotResolvedError):
        cfg.get_value("a.b")
    with pytest.raises(NotResolvedError):
        cfg.get_int("a.b")


def test_resolve_with_partial_keeps_resolved_paths_readable() -> None:
    receiver = parse_string("a { x = ${v} }\nb = ${missing}", resolve_substitutions=False)
    cfg = receiver.resolve_with(parse_string("v = 1"), allow_unresolved=True)
    assert not cfg.is_resolved()
    assert cfg.get("a") == {"x": 1}
    assert cfg["a"] == {"x": 1}
    with pytest.raises(NotResolvedError):
        cfg.get("b")


def test_mapping_view_lists_unresolved_keys_and_reading_them_raises() -> None:
    cfg = parse_string("t = ${missing}\nv = 1\nu { x = ${m2}, y = 2 }", resolve_substitutions=False)
    assert list(cfg) == ["t", "v", "u"]
    assert len(cfg) == 3
    assert cfg.keys() == ["t", "v", "u"]
    assert "t" in cfg  # the key exists; its value does not yet
    assert "u.x" in cfg
    assert "zz" not in cfg
    with pytest.raises(NotResolvedError):
        "t.q" in cfg  # noqa: B015 — below an unresolved value: unknowable
    for read in (lambda: dict(cfg), lambda: cfg == {"v": 1}, lambda: list(cfg.items())):
        with pytest.raises(NotResolvedError):
            read()
    assert cfg.get("v") == 1


def test_has_is_true_for_an_unresolved_path_and_never_raises() -> None:
    # Cross-implementation rule (go / rs return bool): the path exists, only
    # its value waits. Reading it is what raises.
    cfg = parse_string("t = ${missing}\nv = 1\nu { x = ${m2}, y = 2 }", resolve_substitutions=False)
    assert cfg.has("t")
    assert cfg.has("u")
    assert cfg.has("u.x")
    assert cfg.has("v")
    assert cfg.has("u.y")
    assert not cfg.has("zz")
    assert not cfg.has("t.q")  # below an unresolved value: not confirmable
    with pytest.raises(NotResolvedError):
        cfg.get("t")
    partial = cfg.resolve(allow_unresolved=True)
    assert partial.has("t")
    assert partial.has("u.x")


@pytest.mark.parametrize("partial", [False, True])
def test_unresolved_literal_dotted_key_is_not_replaced_by_the_nested_path(partial: bool) -> None:
    cfg = parse_string('"a.b" = ${missing}\na.b = 1', resolve_substitutions=False)
    if partial:
        cfg = cfg.resolve(allow_unresolved=True)
    with pytest.raises(NotResolvedError):
        cfg["a.b"]
    with pytest.raises(NotResolvedError):
        dict(cfg)
    assert cfg.get_int("a.b") == 1  # typed getters traverse the path


@pytest.mark.parametrize("partial", [False, True])
def test_unresolved_literal_key_that_is_not_a_valid_path_is_present(partial: bool) -> None:
    # A quoted key named `"a` cannot be parsed as a path expression; `in` must
    # answer from the key set instead of raising a path-syntax ConfigError.
    cfg = parse_string('"\\"a" = ${missing}\nv = 1', resolve_substitutions=False)
    if partial:
        cfg = cfg.resolve(allow_unresolved=True)
    assert cfg.keys() == ['"a', "v"]
    assert '"a' in cfg
    with pytest.raises(NotResolvedError):
        cfg['"a']
