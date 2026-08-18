"""Spec verification wave — substitution, self-reference, and `+=` items
(S13.3/S13.5/S13.9/S13.12/S13.16, S13a.6/S13a.7/S13a.9, S13b.2/S13b.3,
S22.3, S26.4).

Ports the sibling pins for rows this repo carried as 🤷: ts.hocon
``tests/resolver.test.ts`` / ``tests/parser.test.ts`` and go.hocon
``spec_phase5_test.go``.
"""

import pytest

from hocon import ParseError, ResolveError, parse

_D = chr(36)  # '$' — avoids editor lint on ${...} inside literals


def _sub(path: str, *, optional: bool = False) -> str:
    return _D + "{" + ("?" if optional else "") + path + "}"


class TestS13SubstitutionSyntax:
    """S13.3 / S13.5 / S13.16 — where substitutions are (not) recognised."""

    def test_s13_3_whitespace_before_question_mark_rejected(self) -> None:
        # ${ ?foo} is not an optional substitution. Probe both env states so a
        # miss-driven error cannot masquerade as the syntax rejection.
        with pytest.raises((ParseError, ResolveError)):
            parse("x = " + _D + "{ ?foo}")
        with pytest.raises((ParseError, ResolveError)):
            parse("foo = 1\nx = " + _D + "{ ?foo}")

    def test_s13_5_substitution_inside_quoted_string_is_literal(self) -> None:
        assert parse('x = "' + _sub("foo") + '"').get_string("x") == _sub("foo")

    def test_s13_16_substitution_in_key_position_rejected(self) -> None:
        with pytest.raises(ParseError):
            parse(_sub("foo") + " = 1")


class TestS13EnvAndArrayElements:
    """S13.9 / S13.12 — env-var suppression by config null, and optional
    undefined array elements."""

    def test_s13_9_config_null_blocks_env_var_lookup(self) -> None:
        cfg = parse(
            "HOME = null\nresult = " + _sub("HOME", optional=True),
            env={"HOME": "/from/env"},
        )
        # The config null wins over the environment value.
        assert cfg.get("result") is None
        assert cfg.to_object()["result"] is None

    def test_s13_12_optional_undefined_array_element_skipped(self) -> None:
        cfg = parse("arr = [1, " + _sub("missing", optional=True) + ", 3]")
        assert cfg.get("arr") == [1, 3]


class TestS13aCycles:
    """S13a.6 / S13a.7 / S13a.9 — substitution cycles are errors."""

    def test_s13a_6_cycle_inside_object(self) -> None:
        with pytest.raises(ResolveError):
            parse("a = { b = " + _sub("a") + " }")

    def test_s13a_7_cycle_inside_array(self) -> None:
        with pytest.raises(ResolveError):
            parse("a = [" + _sub("a") + "]")

    def test_s13a_9_multi_step_cycle(self) -> None:
        with pytest.raises(ResolveError):
            parse("a = " + _sub("b") + "\nb = " + _sub("c") + "\nc = " + _sub("a"))


class TestS13bPlusEquals:
    """S13b.2 / S13b.3 — `+=` desugars to `a = ${?a} [b]`."""

    def test_s13b_2_plus_equals_on_non_array_prior_errors(self) -> None:
        with pytest.raises(ResolveError):
            parse("a = 5\na += 6")

    def test_s13b_3_plus_equals_without_prior_makes_singleton_array(self) -> None:
        assert parse("a += 1").get("a") == [1]

    def test_s13b_3_plus_equals_then_append(self) -> None:
        assert parse("a += 1\na += 2").get("a") == [1, 2]


class TestS22_3NullClearsObject:
    """S22.3 — a null at higher priority clears an earlier object value."""

    def test_null_clears_object_in_fallback(self) -> None:
        top = parse("a = null")
        base = parse("a { x = 1 }")
        assert top.with_fallback(base).get("a") is None

    def test_object_wins_over_null_fallback(self) -> None:
        top = parse("a { x = 1 }")
        base = parse("a = null")
        assert top.with_fallback(base).to_object() == {"a": {"x": 1}}

    def test_null_clears_object_within_one_document(self) -> None:
        cfg = parse("a { x = 1 }\na = null")
        assert cfg.get("a") is None


class TestS26_4EnvVarsBecomeStrings:
    """S26.4 — environment values enter as strings; typed getters convert."""

    def test_env_value_is_string_with_auto_conversion(self) -> None:
        cfg = parse("a = " + _sub("EV"), env={"EV": "42"})
        assert cfg.get_string("a") == "42"
        assert cfg.get_int("a") == 42
        # The stored value is a string — the untyped getter shows it verbatim.
        assert cfg.get("a") == "42"

    def test_env_boolean_string_converts_via_get_boolean(self) -> None:
        cfg = parse("flag = " + _sub("EV"), env={"EV": "true"})
        assert cfg.get("flag") == "true"
        assert cfg.get_boolean("flag") is True
