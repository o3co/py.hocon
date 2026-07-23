"""S3.5 — an array-root document (``[1,2]``) is syntactically valid HOCON
(HOCON.md L989-991: "both JSON and HOCON allow arrays as root values in a
document"), but the object-rooted Config API rejects it with a TYPE error
after a successful syntax parse. Reference: Lightbend parses the document,
then ``Parseable.forceParsedToObject`` throws ``ConfigException.WrongType``
"has type LIST rather than object at file root". The former behavior — a
``ParseError`` "expected key, got lbracket" — was the right net outcome
(reject) as the wrong kind of error at the wrong layer.

S14b.1 (HOCON.md L993-994): an INCLUDED file with an array root is invalid;
the error names the *innermost* included source.

Fixtures: xx.hocon array-root/ar01-ar03 with ``.error`` sidecars — covered by
the auto-discovering error-fixture harness (tests/conformance/
test_error_fixtures.py) once ``make testdata`` syncs them; this file pins the
exact error classes and messages.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import hocon
from hocon import ConfigError, ParseError, ResolveError


def _expect_config_error(src: str, label: str, **kwargs: object) -> str:
    with pytest.raises(ConfigError) as excinfo:
        hocon.parse(src, **kwargs)  # type: ignore[arg-type]
    err = excinfo.value
    assert not isinstance(err, ParseError), (
        f"{label}: got ParseError; array-root documents are valid syntax"
    )
    msg = str(err)
    assert "array rather than object at file root" in msg, (
        f"{label}: message must name the array-at-file-root condition, got: {msg}"
    )
    assert err.path == "", f"{label}: file-root errors carry no access path, got: {err.path}"
    return msg


class TestTopLevel:
    @pytest.mark.parametrize(
        ("label", "src"),
        [
            ("basic", "[1,2]"),
            ("multiline-objects", "[\n  { a : 1 },\n  { b : 2 }\n]\n"),
            ("empty-array", "[]"),
        ],
    )
    def test_type_error(self, label: str, src: str) -> None:
        _expect_config_error(src, label)

    def test_error_carries_position(self) -> None:
        msg = _expect_config_error("\n  [1,2]", "position")
        assert "2:3" in msg, f"message must carry the bracket position 2:3, got: {msg}"

    def test_origin_default_is_input(self) -> None:
        msg = _expect_config_error("[1,2]", "origin")
        assert "input: 1:1" in msg, f"expected 'input: 1:1' origin prefix, got: {msg}"

    def test_custom_origin_honored(self) -> None:
        msg = _expect_config_error("[1,2]", "custom origin", origin_description="my-source")
        assert "my-source: 1:1" in msg, f"expected custom origin prefix, got: {msg}"

    def test_parse_file_names_the_file(self, tmp_path: Path) -> None:
        f = tmp_path / "arr.conf"
        f.write_text("[1,2]\n", encoding="utf-8")
        with pytest.raises(ConfigError) as excinfo:
            hocon.parse_file(str(f))
        msg = str(excinfo.value)
        assert "arr.conf" in msg and not msg.startswith("input:"), (
            f"file parse must name the file in the origin, got: {msg}"
        )

    def test_deferred_lifecycle(self) -> None:
        _expect_config_error("[1,2]", "deferred", resolve_substitutions=False)


class TestMalformedStaysSyntaxError:
    @pytest.mark.parametrize(
        ("label", "src"),
        [("unterminated", "[1,2"), ("trailing-content", "[1,2]\na = 1")],
    )
    def test_parse_error(self, label: str, src: str) -> None:
        with pytest.raises(ParseError):
            hocon.parse(src)


class TestIncludePaths:
    def test_include_names_included_file(self, tmp_path: Path) -> None:
        (tmp_path / "arr.conf").write_text("[1,2]\n", encoding="utf-8")
        src = f'include "{tmp_path.as_posix()}/arr.conf"\na = 1\n'
        with pytest.raises(ResolveError) as excinfo:
            hocon.parse(src)
        msg = str(excinfo.value)
        assert "array at file root" in msg, f"must name the condition, got: {msg}"
        assert "arr.conf" in msg, f"must name the included file, got: {msg}"

    def test_nested_include_names_innermost_file(self, tmp_path: Path) -> None:
        # parent -> mid -> arr: the error must accuse arr.conf, never mid.conf.
        (tmp_path / "arr.conf").write_text("[1,2]\n", encoding="utf-8")
        (tmp_path / "mid.conf").write_text('include "arr.conf"\nb = 2\n', encoding="utf-8")
        src = f'include "{tmp_path.as_posix()}/mid.conf"\na = 1\n'
        with pytest.raises(ResolveError) as excinfo:
            hocon.parse(src)
        msg = str(excinfo.value)
        assert "array at file root" in msg, f"must name the condition, got: {msg}"
        assert "arr.conf" in msg, f"must name the innermost file, got: {msg}"
        assert "mid.conf" not in msg, f"must not accuse the intermediate file, got: {msg}"

    def test_package_include_is_resolve_error(self, tmp_path: Path) -> None:
        pkg = tmp_path / "ref.conf"
        pkg.write_text("[1,2]\n", encoding="utf-8")

        def resolver(identifier: str, file: str, _including: object, _base: object) -> str:
            return str(pkg)

        with pytest.raises(ResolveError) as excinfo:
            hocon.parse(
                'a = 1\ninclude package("my-lib", "ref.conf")',
                env={},
                package_resolver=resolver,
            )
        msg = str(excinfo.value)
        assert "array at file root" in msg, f"must name the condition, got: {msg}"


class TestNonRootArraysUnaffected:
    def test_field_value_array(self) -> None:
        cfg = hocon.parse("a = [1,2]")
        assert cfg.to_object() == {"a": [1, 2]}

    def test_braced_root_with_array_field(self) -> None:
        assert hocon.parse("{ a = [1,2] }").to_object() == {"a": [1, 2]}
