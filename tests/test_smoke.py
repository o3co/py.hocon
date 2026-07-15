"""Scaffold smoke tests: public surface exists and the error hierarchy holds."""

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
    # ParseError / ResolveError and ConfigError are intentionally separate
    # trees (parity with ts.hocon src/errors.ts).
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


def test_parse_not_implemented_yet() -> None:
    with pytest.raises(NotImplementedError):
        hocon.parse("a = 1")
    with pytest.raises(NotImplementedError):
        hocon.parse_string("a = 1")
    with pytest.raises(NotImplementedError):
        hocon.parse_file("app.conf")
