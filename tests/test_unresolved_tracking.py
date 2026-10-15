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
