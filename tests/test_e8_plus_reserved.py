"""S8.1 / E8 — `+` is reserved outside quotes.

HOCON.md L245 lists `+` among the characters an unquoted string may not
contain (it is the `+=` operator). Inside an unquoted run the only `+` that
survives is the sign of a number's exponent (`1e+5`); E8 step 4 makes a failed
number-lex that consumed a `+` (`1e+x`, fixture us15) a reserved-character
error rather than a fallback to text. Matches Lightbend and go.hocon.
"""

from __future__ import annotations

import pytest

from hocon import ParseError, parse_string


@pytest.mark.parametrize(
    "text",
    [
        "a = 1e+x",  # us15: incomplete exponent
        "a = -1e+x",
        "a = 1e+",
        "a = 1+2",
        "a = 1+",
        "a = 1e+5e+5",  # second exponent: Lightbend's greedy number-lex fails
        "a = .5e+3",  # '.'-leading runs are text, so this '+' is not a sign
        "a = foo+bar",  # concat-continuation
        "a = x1e+5",
        "a = [1e+x]",
        "a+b = 1",  # key position
    ],
)
def test_plus_outside_quotes_is_rejected(text: str) -> None:
    with pytest.raises(ParseError, match="reserved character '\\+' outside quotes"):
        parse_string(text)


def test_error_points_at_the_plus() -> None:
    with pytest.raises(ParseError) as e:
        parse_string("a = foo+bar")
    assert (e.value.line, e.value.col) == (1, 8)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a = 1e+5", 100000.0),
        ("a = 1E+5", 100000.0),
        ("a = -1.5e+3", -1500.0),
        ("a = 1.e+5", 100000.0),  # Java Double.parseDouble accepts "1.e+5"
        ("a = 1e+5x", "1e+5x"),  # number, then text: a concatenation
        ("a = 1e-x", "1e-x"),  # no '+': failed number-lex falls back to text
        ('a = "foo+bar"', "foo+bar"),  # quoted: '+' is content
        ('a = """1e+x"""', "1e+x"),
    ],
)
def test_exponent_sign_and_quoted_plus_are_accepted(text: str, expected: object) -> None:
    assert parse_string(text).get("a") == expected


def test_plus_equals_still_appends() -> None:
    assert parse_string("a = [1]\na += 2\na+=3").get("a") == [1, 2, 3]
