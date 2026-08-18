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


def test_interior_sibling_ref_stays_lazy_final_tree() -> None:
    # ${a.p.v} sits INSIDE a's object literal — an object-interior sibling
    # reference, not a value-stack layer. It must keep S13a.14 lazy final-tree
    # semantics (the allow_prefix narrowing), not fold to a below value.
    v = parse("a = { p : { v : 1 }, x : " + D + "{a.p.v} }\na = { y : 2 }").to_object()
    assert v["a"] == {"p": {"v": 1}, "x": 1, "y": 2}


# --- prior-fold recursion at a save site whose key has no below value ---
# First definition of `foo` contains a self-ref and is then overwritten:
# fold_or_skip_prior runs with old=None, so the optional-absent fold walks
# the container (concat / array / object literal / merged object). Optional
# self-refs fold to known-absent placeholders; a required one drops the
# whole prior (nothing "below" can ever satisfy it).


def test_first_def_concat_optional_selfref_prior_folds() -> None:
    got = foo('foo : "x "' + D + "{?foo.a}\nfoo : { a : 1 }")
    assert got == {"a": 1}


def test_first_def_concat_required_selfref_prior_skipped() -> None:
    got = foo('foo : "x "' + D + "{foo.a}\nfoo : { a : 1 }")
    assert got == {"a": 1}


def test_first_def_array_optional_selfref_prior_folds() -> None:
    got = foo("foo : [" + D + "{?foo.a}]\nfoo : { a : 1 }")
    assert got == {"a": 1}


def test_first_def_array_required_selfref_prior_skipped() -> None:
    got = foo("foo : [" + D + "{foo.a}]\nfoo : { a : 1 }")
    assert got == {"a": 1}


def test_first_def_object_interior_optional_exact_selfref_prior_folds() -> None:
    got = foo("foo : { x : " + D + "{?foo} }\nfoo : 2")
    assert got == 2


def test_first_def_object_interior_required_exact_selfref_prior_skipped() -> None:
    got = foo("foo : { x : " + D + "{foo} }\nfoo : 2")
    assert got == 2


def test_first_def_merged_obj_optional_selfref_prior_folds() -> None:
    got = foo("foo : { x : " + D + "{?foo} }\nfoo : { y : 1 }\nfoo : 2")
    assert got == 2


def test_first_def_merged_obj_required_selfref_prior_skipped() -> None:
    got = foo("foo : { x : " + D + "{foo} }\nfoo : { y : 1 }\nfoo : 2")
    assert got == 2


# --- allow_unresolved keeps the placeholder instead of erroring ---


def test_allow_unresolved_keeps_prefix_miss_placeholder() -> None:
    cfg = parse(
        "foo : { a : 1 }\nfoo : " + D + "{foo.b}", resolve_substitutions=False
    ).resolve(allow_unresolved=True)
    assert "foo" not in cfg.to_object()


def test_allow_unresolved_keeps_known_absent_placeholder() -> None:
    src = "foo : { a : 1 }\nfoo : " + D + "{foo.b}\nfoo : " + D + "{foo.a}"
    cfg = parse(src, resolve_substitutions=False).resolve(allow_unresolved=True)
    assert "foo" not in cfg.to_object()


# --- `[]`-suffixed substitutions report their own path in the error ---
# `${foo.b[]}` is surface syntax (the internal form of `+=`), so a REQUIRED
# list-suffix substitution can reach both undefined-classification errors.


def test_required_list_suffix_prefix_miss_error_key() -> None:
    with pytest.raises(ResolveError, match=r"could not resolve substitution: \$\{foo\.b\[\]\}"):
        foo("foo : { a : 1 }\nfoo : " + D + "{foo.b[]}")


def test_required_list_suffix_known_absent_error_key() -> None:
    src = "foo : { a : 1 }\nfoo : " + D + "{foo.b[]}\nfoo : " + D + "{foo.a}"
    with pytest.raises(ResolveError, match=r"could not resolve substitution: \$\{foo\.b\[\]\}"):
        foo(src)


def test_first_def_array_object_literal_optional_selfref_prior_folds() -> None:
    # Self-ref sits inside an object literal that is itself an array element —
    # the fold walks array → object interior (exact-match-only there).
    got = foo("foo : [{ x : " + D + "{?foo} }]\nfoo : { a : 1 }")
    assert got == {"a": 1}


def test_first_def_array_object_literal_required_selfref_prior_skipped() -> None:
    got = foo("foo : [{ x : " + D + "{foo} }]\nfoo : { a : 1 }")
    assert got == {"a": 1}


def test_prior_fold_leaves_foreign_subst_untouched() -> None:
    # Prior concat mixes a prefix self-ref with a foreign substitution; the
    # fold rewrites only the self-ref and passes ${other} through unchanged.
    src = (
        "other : 9\nfoo : { a : 1 }\nfoo : "
        + D
        + "{foo.a} "
        + D
        + "{other}\nfoo : { b : 2 }"
    )
    assert foo(src) == {"b": 2}


def test_prior_fold_recurses_object_literal_beside_selfref() -> None:
    # A value-stack self-ref makes the prior foldable; the object literal
    # sitting beside it is walked (interior refs keep exact-match-only rule).
    src = (
        "foo : { a : 1 }\nfoo : ["
        + D
        + "{foo.a}, { x : "
        + D
        + "{foo} }]\nfoo : { b : 2 }"
    )
    assert foo(src) == {"b": 2}
