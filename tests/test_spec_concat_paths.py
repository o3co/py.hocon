"""Spec verification wave — concatenation, merge, and path items (S7.5,
S10.9/S10.10/S10.15/S10.16, S11.4/S11.5/S11.8/S11.9/S11.10, S23.2).

Ports the sibling pins for rows this repo carried as 🤷: ts.hocon
``tests/resolver.test.ts`` / ``tests/parser.test.ts`` and go.hocon
``spec_phase5_test.go``.
"""

from pathlib import Path

import pytest

from hocon import ParseError, ResolveError, parse, parse_file

_D = chr(36)  # '$' — avoids editor lint on ${...} inside literals


class TestS7_5RecursiveMerge:
    """S7.5 — duplicate keys whose values are both objects merge recursively."""

    def test_object_fields_merge_recursively(self) -> None:
        cfg = parse("a = {x: {p: 1}}\na = {x: {q: 2}}")
        assert cfg.get("a") == {"x": {"p": 1, "q": 2}}

    def test_last_wins_inside_the_recursive_merge(self) -> None:
        cfg = parse("a = {x: {p: 1}}\na = {x: {p: 2, q: 3}}")
        assert cfg.get("a") == {"x": {"p": 2, "q": 3}}


class TestS10ConcatStringify:
    """S10.9 / S10.10 — true/false/null stringify inside value concatenation;
    a single non-string value keeps its type."""

    def test_s10_9_true_stringifies_in_concat(self) -> None:
        assert parse("x = true foo").get_string("x") == "true foo"

    def test_s10_9_false_stringifies_in_concat(self) -> None:
        assert parse("x = false bar").get_string("x") == "false bar"

    def test_s10_10_null_stringifies_in_concat(self) -> None:
        assert parse("x = null foo").get_string("x") == "null foo"

    def test_s10_10_single_null_keeps_type(self) -> None:
        assert parse("x = null").get("x") is None


class TestS10_15QuotedWhitespaceBetweenContainers:
    """S10.15 — quoted whitespace between substitution-resolved objects/arrays
    is a real string operand, so the container+string concat is a type error."""

    def test_between_arrays_raises(self) -> None:
        src = "a = [1]\nb = [2]\nx = " + _D + '{a} " " ' + _D + "{b}"
        with pytest.raises(ResolveError):
            parse(src)

    def test_between_objects_raises(self) -> None:
        src = "a = { p: 1 }\nb = { q: 2 }\nx = " + _D + '{a} " " ' + _D + "{b}"
        with pytest.raises(ResolveError):
            parse(src)


class TestS10_16WhitespaceInArrays:
    """S10.16 — non-newline whitespace inside an array builds one concatenated
    element; newlines separate elements."""

    def test_space_separated_values_concatenate(self) -> None:
        assert parse("a = [ 1 2 3 4 ]").get("a") == ["1 2 3 4"]

    def test_newline_separated_values_stay_distinct(self) -> None:
        assert parse("a = [\n1\n2\n3\n4\n]").get("a") == [1, 2, 3, 4]


class TestS11Paths:
    """S11.4 / S11.5 / S11.8 / S11.9 / S11.10 — path expression splitting,
    stringification, and the substitutions-in-paths prohibition."""

    def test_s11_4_number_first_path_splits_on_dot(self) -> None:
        # 10.0foo → path [10, 0foo]
        assert parse("10.0foo = 2").to_object() == {"10": {"0foo": 2}}

    def test_s11_5_number_last_path_splits_on_dot(self) -> None:
        # foo10.0 → path [foo10, 0]
        assert parse("foo10.0 = 1").to_object() == {"foo10": {"0": 1}}

    def test_s11_8_keyword_key_stringifies(self) -> None:
        assert parse("true = 1").to_object() == {"true": 1}

    def test_s11_9_substitution_only_key_rejected(self) -> None:
        with pytest.raises(ParseError):
            parse(_D + "{x} = 1")

    def test_s11_9_substitution_inside_path_rejected(self) -> None:
        with pytest.raises(ParseError):
            parse("a." + _D + "{x}.b = 1")

    def test_s11_10_quoted_segment_respected_by_getters(self) -> None:
        cfg = parse('foo { "bar.baz" = 7 }')
        assert cfg.get('foo."bar.baz"') == 7
        # The unquoted spelling addresses a different (absent) nested path.
        assert cfg.get("foo.bar.baz") is None


class TestS23_2EmptyPathElements:
    """S23.2 — .properties keys with empty path elements (trailing dot)
    preserve the empty segment. .properties enters through the include
    loader (py has no direct properties parse entry point)."""

    def test_trailing_dot_key_preserves_empty_segment(self, tmp_path: Path) -> None:
        (tmp_path / "test.properties").write_text("a.=hello\n", encoding="utf-8")
        (tmp_path / "main.conf").write_text('include "test.properties"\n', encoding="utf-8")
        cfg = parse_file(str(tmp_path / "main.conf"))
        assert cfg.to_object() == {"a": {"": "hello"}}
