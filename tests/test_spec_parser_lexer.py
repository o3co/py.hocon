"""Spec verification wave — parser/lexer items (S3.2, S5.2–S5.6, S6.1/6.2/6.4/6.5,
S8.7, S9.1–S9.5).

Ports the sibling pins for rows this repo carried as 🤷 ("ported, pending
dedicated test"): ts.hocon ``tests/parser.test.ts`` (comma rules, root
scalar), ``tests/lexer.test.ts`` (Unicode whitespace, unquoted escapes),
go.hocon ``spec_phase5_test.go`` (S6.5), and the S9 triple-quote battery
verified against the Lightbend oracle (typesafe-config 1.4.6 probe,
2026-08-18) — including the leading-newline case Lightbend PRESERVES, which
the ported ts lexer used to strip (fixed in this branch).
"""

import pytest

from hocon import ParseError, parse
from hocon._internal.lexer.lexer import tokenize


class TestS3_2RootScalar:
    """S3.2 — root non-object/non-array is invalid."""

    def test_root_bare_string_rejected(self) -> None:
        with pytest.raises(ParseError):
            parse('"hello"')

    def test_root_bare_number_rejected(self) -> None:
        with pytest.raises(ParseError):
            parse("42")


class TestS5CommaRules:
    """S5.2–S5.6 — comma rules for arrays and objects."""

    def test_s5_2_single_trailing_comma_in_array(self) -> None:
        assert parse("list = [1, 2, 3,]").get("list") == [1, 2, 3]

    def test_s5_2_single_trailing_comma_in_object(self) -> None:
        assert parse("{ a = 1, b = 2, }").to_object() == {"a": 1, "b": 2}

    def test_s5_3_two_trailing_commas_in_array_rejected(self) -> None:
        with pytest.raises(ParseError):
            parse("list = [1, 2, 3,,]")

    def test_s5_3_two_trailing_commas_in_object_rejected(self) -> None:
        with pytest.raises(ParseError):
            parse("{ a = 1, b = 2,, }")

    def test_s5_4_leading_comma_in_array_rejected(self) -> None:
        with pytest.raises(ParseError):
            parse("list = [,1, 2, 3]")

    def test_s5_4_leading_comma_in_object_rejected(self) -> None:
        with pytest.raises(ParseError):
            parse("{ , a = 1 }")

    def test_s5_5_two_consecutive_commas_in_array_rejected(self) -> None:
        with pytest.raises(ParseError):
            parse("list = [1,, 2, 3]")

    def test_s5_6_two_consecutive_commas_in_object_rejected(self) -> None:
        with pytest.raises(ParseError):
            parse("{ a = 1,, b = 2 }")


def _token_values(src: str) -> list[str]:
    return [t.value for t in tokenize(src) if t.kind != "eof"]


def _token_kinds(src: str) -> list[str]:
    return [t.kind for t in tokenize(src) if t.kind != "eof"]


class TestS6Whitespace:
    """S6.1 / S6.2 / S6.4 — the HOCON whitespace set at the lexer level, and
    S6.5 — "newline" means specifically LF (0x000A)."""

    @pytest.mark.parametrize(
        "ch",
        ["\u2003", "\u2028", "\u2029"],
        ids=["em-space-Zs", "line-separator-Zl", "paragraph-separator-Zp"],
    )
    def test_s6_1_unicode_zs_zl_zp_separate_tokens(self, ch: str) -> None:
        assert _token_values(f"a{ch}b") == ["a", "b"]

    @pytest.mark.parametrize(
        "ch",
        ["\u00a0", "\u2007", "\u202f"],
        ids=["nbsp", "figure-space", "narrow-nbsp"],
    )
    def test_s6_2_non_breaking_spaces_separate_tokens(self, ch: str) -> None:
        assert _token_values(f"a{ch}b") == ["a", "b"]

    @pytest.mark.parametrize(
        "ch",
        ["\t", "\x0b", "\x0c", "\r", "\x1c", "\x1d", "\x1e", "\x1f"],
        ids=["tab", "vtab", "form-feed", "cr", "fs", "gs", "rs", "us"],
    )
    def test_s6_4_ascii_control_whitespace_separates_tokens(self, ch: str) -> None:
        assert _token_values(f"a{ch}b") == ["a", "b"]

    def test_s6_5_lf_separates_fields(self) -> None:
        cfg = parse("a=1\nb=2")
        assert (cfg.get_int("a"), cfg.get_int("b")) == (1, 2)

    def test_s6_5_crlf_separates_fields(self) -> None:
        # CR is plain whitespace; the LF that follows is the actual separator.
        cfg = parse("a=1\r\nb=2")
        assert (cfg.get_int("a"), cfg.get_int("b")) == (1, 2)

    def test_s6_5_cr_alone_is_not_a_newline_token(self) -> None:
        # A lone CR is whitespace, not a newline: no newline token is emitted,
        # while LF emits one.
        assert "newline" not in _token_kinds("a\rb")
        assert "newline" in _token_kinds("a\nb")


class TestS8_7NoUnquotedEscapes:
    """S8.7 — no escape sequences in unquoted strings: a backslash terminates
    the unquoted run and is itself rejected, never decoded."""

    def test_backslash_in_unquoted_rejected(self) -> None:
        with pytest.raises(ParseError):
            tokenize("a\\n")

    def test_backslash_value_rejected_end_to_end(self) -> None:
        with pytest.raises(ParseError):
            parse("x = a\\nb")


class TestS9TripleQuoted:
    """S9.1–S9.5 — triple-quoted strings. Expected values verified against the
    Lightbend oracle (typesafe-config 1.4.6 probe, 2026-08-18)."""

    def test_s9_1_basic(self) -> None:
        assert parse('x = """hello"""').get_string("x") == "hello"

    def test_s9_2_newlines_and_whitespace_preserved(self) -> None:
        assert parse('x = """a\n  b"""').get_string("x") == "a\n  b"

    def test_s9_2_leading_newline_preserved(self) -> None:
        # Lightbend probe: """\nhello""" → "\nhello". The ported ts lexer used
        # to strip the leading newline (spec deviation, fixed in this branch);
        # go.hocon always preserved it.
        assert parse('x = """\nhello"""').get_string("x") == "\nhello"

    def test_s9_3_unicode_escapes_not_interpreted(self) -> None:
        # Lightbend probe: """aA\n""" → the six characters aA plus
        # literal backslash-n — escapes stay literal inside triple quotes.
        assert parse('x = """a\\u0041\\n"""').get_string("x") == "a\\u0041\\n"

    def test_s9_4_trailing_extra_quotes_are_content(self) -> None:
        # Lightbend probe: """foo"""" → foo" and """foo""""" → foo"".
        assert parse('x = """foo""""').get_string("x") == 'foo"'
        assert parse('x = """foo"""""').get_string("x") == 'foo""'

    def test_s9_5_unterminated_rejected(self) -> None:
        with pytest.raises(ParseError):
            parse('x = """oops')
        with pytest.raises(ParseError):
            parse('x = """line1\nline2')
