"""E19 — overflowing float literal is a parse error (xx.hocon#97, posture B).

A numeric literal whose magnitude overflows the double range is a parse
error in all four sibling implementations. This is a documented divergence
from Lightbend: the reference admits the literal as Infinity, but HOCON has
no Infinity literal, so the value cannot be rendered or re-parsed as a
number (Lightbend's own render -> re-parse silently turns it into the
STRING "Infinity"). go.hocon has always errored here via
strconv.ParseFloat; ts/py/rs align with it. Port of ts.hocon's
e19-float-overflow.test.ts.

Underflow is NOT an error: ``1e-400`` reads as 0 in every implementation
and in Lightbend, so only the infinite case is rejected.
"""

from __future__ import annotations

import pytest

from hocon import ParseError, parse


def test_rejects_overflow() -> None:
    with pytest.raises(ParseError, match=r'invalid float "1e999"'):
        parse("a = 1e999")


def test_rejects_negative_overflow() -> None:
    with pytest.raises(ParseError, match=r'invalid float "-1e999"'):
        parse("a = -1e999")


def test_rejects_fractional_overflow() -> None:
    with pytest.raises(ParseError):
        parse("a = 2.5e999")


def test_rejects_overflow_in_array_element() -> None:
    with pytest.raises(ParseError):
        parse("a = [1, 1e999]")


def test_rejects_integer_form_beyond_double_range() -> None:
    # E19 is keyed on the lexeme's value, not its spelling: an integer-form
    # literal beyond the double range errors too, even though Python's
    # unbounded int could hold it exactly — ts/rs reject it and go rejects
    # it far earlier (int64), so accepting it would make py the lone sibling
    # with an answer. The sub-double band where models genuinely differ is
    # xx.hocon#99. Copilot review on py#45 surfaced this trade-off.
    with pytest.raises(ParseError):
        parse("a = " + "9" * 400)


def test_accepts_integer_form_within_double_range_as_exact_int() -> None:
    # 2**200 is finite as a double, so E19 does not fire; py's unbounded int
    # keeps the exact value (the #99 band, unchanged by this window).
    raw = str(2**200)
    assert parse(f"a = {raw}").get_number("a") == 2**200


def test_accepts_underflow_as_zero() -> None:
    assert parse("a = 1e-400").get_number("a") == 0


def test_accepts_finite_extremes() -> None:
    assert parse("a = 1e308").get_number("a") == 1e308
    assert parse("a = 5e-324").get_number("a") == 5e-324


def test_quoted_overflow_stays_string() -> None:
    assert parse('a = "1e999"').get_string("a") == "1e999"


def test_unquoted_infinity_stays_string() -> None:
    # No Infinity literal exists in HOCON; the word is an unquoted string.
    assert parse("a = Infinity").get_string("a") == "Infinity"


def test_error_position_points_at_literal() -> None:
    with pytest.raises(ParseError) as exc_info:
        parse("a = 1e999")
    assert exc_info.value.line == 1
    assert exc_info.value.col == 5
