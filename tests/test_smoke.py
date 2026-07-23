"""Smoke tests: public surface, error hierarchy, and basic parse/resolve."""

import pytest

import hocon
from hocon import (
    ConfigError,
    NotResolvedError,
    PackageLookupError,
    ParseError,
    ResolveError,
)


def test_version() -> None:
    assert hocon.__version__


def test_public_surface() -> None:
    for name in hocon.__all__:
        assert getattr(hocon, name, None) is not None, name


def test_error_hierarchy() -> None:
    # ParseError / ResolveError and ConfigError are intentionally separate trees
    # (parity with ts.hocon src/errors.ts).
    assert issubclass(PackageLookupError, ResolveError)
    assert issubclass(NotResolvedError, ConfigError)
    assert not issubclass(ParseError, ConfigError)
    assert not issubclass(ResolveError, ConfigError)


def test_error_fields() -> None:
    err = ParseError("bad token", line=3, col=7, file="app.conf")
    assert (err.line, err.col, err.file) == (3, 7, "app.conf")

    rerr = PackageLookupError("not found", "some-pkg", "defaults.conf", line=1, col=2)
    assert rerr.path == "some-pkg/defaults.conf"
    assert isinstance(rerr, ResolveError)

    nerr = NotResolvedError("a.b.c")
    assert nerr.path == "a.b.c"
    assert "resolve()" in str(nerr)


def test_parse_scalars_and_nesting() -> None:
    cfg = hocon.parse('a = 1\nb = "two"\nc { d = true, e = null }')
    assert cfg.get_int("a") == 1
    assert cfg.get_string("b") == "two"
    assert cfg.get_boolean("c.d") is True
    assert cfg.get("c.e") is None
    assert cfg.to_object() == {"a": 1, "b": "two", "c": {"d": True, "e": None}}


def test_substitution() -> None:
    cfg = hocon.parse('a = 1\nb = ${a}\nc = ${a}px')
    assert cfg.get_int("b") == 1
    assert cfg.get_string("c") == "1px"


def test_object_merge_and_arrays() -> None:
    cfg = hocon.parse("a { x = 1 }\na { y = 2 }\nlist = [1, 2, 3]")
    assert cfg.to_object() == {"a": {"x": 1, "y": 2}, "list": [1, 2, 3]}


def test_self_append() -> None:
    cfg = hocon.parse("a = [1]\na += 2\na += 3")
    assert cfg.get_list("a") == [1, 2, 3]


def test_duration_and_bytes() -> None:
    cfg = hocon.parse("t = 5s\nsize = 1K")
    assert cfg.get_duration("t") == 5000.0
    assert cfg.get_bytes("size") == 1024


def test_from_map_roundtrip() -> None:
    cfg = hocon.from_map({"a": 1, "b": [True, None, "x"], "c": {"d": 2.5}})
    assert cfg.to_object() == {"a": 1, "b": [True, None, "x"], "c": {"d": 2.5}}


def test_empty_input_parses_to_empty() -> None:
    # Corrected S3.1 (xx.hocon E10): an empty / whitespace-only / comment-only
    # document parses to {} per HOCON.md L134-136.
    assert hocon.parse("   \n # comment only \n").to_object() == {}
    assert hocon.parse("").to_object() == {}


def test_block_comment_only_input_is_rejected() -> None:
    # Boundary of the S3.1 loosening: /* */ block comments are not HOCON
    # syntax (# and // only), so a block-comment-only document is a syntax
    # error, NOT an empty document — the empty rule must not mask it.
    with pytest.raises(ParseError):
        hocon.parse("/* block comments are not HOCON */\n")


def test_missing_path_raises() -> None:
    cfg = hocon.parse("a = 1")
    with pytest.raises(ConfigError):
        cfg.get_string("nope")


def test_circular_substitution_raises() -> None:
    with pytest.raises(ResolveError):
        hocon.parse("a = ${b}\nb = ${a}")
