"""S13a.12 (HOCON.md L791) — prefix self-reference resolves to "below".

A substitution whose target lies INSIDE the field being defined
(``foo : ${foo.a}``) resolves against the field's below value (the merge of
the stack beneath the substitution), never the final tree. Found 2026-08-18 by
a cross-impl probe: all four siblings resolved the spec example against the
final tree, yielding {a:2} instead of {a:2, c:1}. Port of ts.hocon's
s13a12-prefix-self-ref.test.ts; the fix mirrors ts (fold-side prefix folding
with layer merge + resolve-side prior navigation with undefined semantics).
"""

from __future__ import annotations

import pytest

from hocon import ResolveError, parse

D = chr(36)  # '$' — avoids IDE template-string lint on ${...} literals


def foo(src: str) -> object:
    return parse(src).to_object()["foo"]


def test_spec_example_sandwich() -> None:
    got = foo("foo : { a : { c : 1 } }\nfoo : " + D + "{foo.a}\nfoo : { a : 2 }")
    assert got == {"a": 2, "c": 1}


def test_two_layers_subst_last() -> None:
    got = foo("foo : { a : { c : 1 } }\nfoo : " + D + "{foo.a}")
    assert got == {"a": {"c": 1}, "c": 1}


def test_below_layer_keys_survive() -> None:
    got = foo(
        "foo : { a : { c : 1 }, keep : 9 }\nfoo : " + D + "{foo.a}\nfoo : { a : 2 }"
    )
    assert got == {"a": 2, "keep": 9, "c": 1}


def test_scalar_navigation_resets_stack() -> None:
    got = foo("foo : { a : 5 }\nfoo : " + D + "{foo.a}\nfoo : { b : 2 }")
    assert got == {"b": 2}


def test_optional_miss_vanishes_transparently() -> None:
    got = foo("foo : { a : 1 }\nfoo : " + D + "{?foo.nope}\nfoo : { b : 2 }")
    assert got == {"a": 1, "b": 2}


def test_required_miss_is_undefined_error() -> None:
    with pytest.raises(ResolveError, match="could not resolve substitution"):
        foo("foo : { a : 1 }\nfoo : " + D + "{foo.nope}\nfoo : { b : 2 }")


def test_nested_paths() -> None:
    v = parse(
        "srv : { foo : { a : { c : 1 } } }\nsrv : { foo : "
        + D
        + "{srv.foo.a} }\nsrv : { foo : { a : 2 } }"
    ).to_object()
    assert v["srv"]["foo"] == {"a": 2, "c": 1}


def test_unnavigable_below_optional_stays_resolvable() -> None:
    got = foo(
        "foo : { a : "
        + D
        + "{x} }\nfoo : "
        + D
        + "{?foo.a.b}\nfoo : { z : 1 }\nx : { b : 7 }"
    )
    assert got == {"z": 1}


def test_layer_merge_recurses_into_shared_keys() -> None:
    got = foo(
        "foo : { shared : { p : 1 }, a : { shared : { q : 2 } } }\nfoo : "
        + D
        + "{foo.a}\nfoo : { z : 0 }"
    )
    assert got == {"shared": {"p": 1, "q": 2}, "a": {"shared": {"q": 2}}, "z": 0}


def test_two_layers_required_miss_errors() -> None:
    with pytest.raises(ResolveError, match="could not resolve substitution"):
        foo("foo : { a : 1 }\nfoo : " + D + "{foo.nope}")


def test_two_layers_optional_miss_keeps_prior() -> None:
    got = foo("foo : { a : 1 }\nfoo : " + D + "{?foo.nope}")
    assert got == {"a": 1}


def test_regression_non_self_ref_sandwich_unchanged() -> None:
    got = foo(
        "d = { x : { c : 1 } }\nfoo : { a : { c : 9 } }\nfoo : "
        + D
        + "{d.x}\nfoo : { a : 2 }"
    )
    assert got == {"c": 1, "a": 2}


def test_regression_sibling_ref_in_deeper_prior_sees_final_tree() -> None:
    v = parse(
        "bar { nested { x = { q: 10 }\na = " + D + "{bar.nested.x}\na = { c: 3 } } }"
    ).to_object()
    assert v["bar"]["nested"]["a"] == {"q": 10, "c": 3}
