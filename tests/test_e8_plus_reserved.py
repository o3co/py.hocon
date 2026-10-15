"""S8.1 / E8 — `+` is reserved outside quotes.

HOCON.md L245 lists `+` among the characters an unquoted string may not
contain (it is the `+=` operator). Outside quotes the only `+` that survives
is the sign of a number's exponent (`1e+5`). E8 step 4 makes a number run that
consumed a `+` but is not a number (`1e+x`, fixture us15; `1e+5.5`) a
reserved-character error rather than a fallback to text, as in Lightbend 1.4.6;
the shared cross-impl table below is pinned verbatim.
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
        # E8 step 4: the greedy [0-9.eE+-] prefix holds a '+' but is no number
        "a = 1e+5e5",
        "a = 1e+5.2",
        "a = 1e+5-",
        "a = .5e+3",  # '.'-leading runs are text, so this '+' is not a sign
        "a = foo+bar",  # concat-continuation
        "a = x1e+5",
        "a = [1e+x]",
        "a+b = 1",  # key position
        "a.1e+5 = 1",  # `1e+5` is not a number when it continues a key run
        "a = +foo",  # token-start '+': same rule, same message
        "a = foo +bar",
        'a = "x"+y',
        "x = 1\na = ${x}+bar",
        "a = \u0661e+5",  # Unicode digits are text, not number characters
        "a = 1\u0665e+5",
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
        ("a = 1e-5e5", "1e-5e5"),  # likewise
        ('a = "foo+bar"', "foo+bar"),  # quoted: '+' is content
        ('a = """1e+x"""', "1e+x"),
        ('a = "x"1e+5', "x1e+5"),  # a number token starts after the quoted one
        ("x = foo\na = ${x}1e+5", "foo1e+5"),
    ],
)
def test_exponent_sign_and_quoted_plus_are_accepted(text: str, expected: object) -> None:
    assert parse_string(text).get("a") == expected


def test_plus_equals_still_appends() -> None:
    assert parse_string("a = [1]\na += 2\na+=3").get("a") == [1, 2, 3]


def test_number_key_with_exponent_sign_is_a_key() -> None:
    cfg = parse_string("1e+5 = 1\na { 1e+5 = 2 }")
    assert cfg.get('"1e+5"') == 1
    assert cfg.get('a."1e+5"') == 2


# The cross-impl table (Lightbend 1.4.6 = go.hocon develop, measured
# 2026-10-16): outside quotes, '+' survives only as an exponent sign.
_SHARED_TABLE: list[tuple[str, object]] = [
    ("1e+x", ParseError),
    ("1+2", ParseError),
    ("1.2.3+build", ParseError),
    ("1.0.0+abc", ParseError),
    ("+1", ParseError),
    ("1e+5", 100000.0),
    ("1x+2", ParseError),
    ("abc+1", ParseError),
    ("abc+", ParseError),
    ("a+b", ParseError),
    ("1e+5ms", "1e+5ms"),
    ("1e+5 ms", "1e+5 ms"),
    ("1.5e+3s", "1.5e+3s"),
]


@pytest.mark.parametrize(("value", "expected"), _SHARED_TABLE)
def test_shared_cross_impl_table(value: str, expected: object) -> None:
    if expected is ParseError:
        with pytest.raises(ParseError, match="reserved character '\\+'"):
            parse_string(f"a = {value}")
    else:
        assert parse_string(f"a = {value}").get("a") == expected


# The rest of the shared table (Lightbend 1.4.6 is the baseline; go.hocon is
# being aligned on the rows it diverges from).
_SHARED_TABLE_MORE: list[tuple[str, object]] = [
    ("1e+5x", "1e+5x"),
    ("1e-x", "1e-x"),
    ("1e-5e5", "1e-5e5"),
    ("-1.5e+3", -1500.0),
    ("x1e+5", ParseError),
    (".5e+3", ParseError),
    ("1e+5.5", ParseError),
    ("1e+5.2", ParseError),
    ("1e+5e5", ParseError),
    ("1e+5-", ParseError),
    ("1.e+5", 100000.0),
]


@pytest.mark.parametrize(("value", "expected"), _SHARED_TABLE_MORE)
def test_shared_cross_impl_table_more(value: str, expected: object) -> None:
    test_shared_cross_impl_table(value, expected)


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        ("1e+5 = 1", {"1e+5": 1}),
        ("1e+5x = 1", {"1e+5x": 1}),
        ("a+b = 1", ParseError),
        ("a.1e+5 = 1", ParseError),
        ("x = [1]\nx += 2", {"x": [1, 2]}),
    ],
)
def test_shared_table_key_position(document: str, expected: object) -> None:
    if expected is ParseError:
        with pytest.raises(ParseError, match="reserved character '\\+'"):
            parse_string(document)
    else:
        assert parse_string(document).to_object() == expected


# Number-lex edges without '+' (S8.4, Lightbend 1.4.6). Digits are ASCII:
# a Unicode digit makes the run text.
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.", 1.0),
        ("1.e5", 100000.0),
        ("-1.", -1.0),
        ("-.5", -0.5),
        ("-.5e+3", -500.0),
        ("1.5.", "1.5."),
        (".5", ".5"),
        ("-.", "-."),
        ("1.e", "1.e"),
        ("1٥", "1٥"),
    ],
)
def test_number_lex_edges(value: str, expected: object) -> None:
    got = parse_string(f"a = {value}").get("a")
    assert got == expected
    assert isinstance(got, str) == isinstance(expected, str)


def test_long_malformed_run_is_rejected_quickly() -> None:
    # The number regexes have no overlapping quantifiers, so this is linear.
    import time

    start = time.perf_counter()
    with pytest.raises(ParseError):
        parse_string("1" * 8000 + "e+5.2 = 1")
    assert time.perf_counter() - start < 1.0
