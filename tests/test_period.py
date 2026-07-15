"""S20 Period accessor tests.

Mirrors rs.hocon's ``parse_period`` unit tests (src/config.rs) and the
units-default period fixtures up01–up05 (scenarios inlined here; the
fixture-runner harness for the whole units-default group lands with the
conformance-corpus expansion).
"""

from __future__ import annotations

import pytest

import hocon
from hocon import Config, ConfigError, Period


def _cfg(src: str) -> Config:
    return hocon.parse(src)


# up01: bare integer string defaults to days (HOCON.md L1321).
def test_period_bare_integer_string() -> None:
    assert _cfg('p = "7"').get_period("p") == Period(0, 0, 7)


# up02: HOCON-whitespace padding is trimmed.
def test_period_leading_trailing_ws() -> None:
    assert _cfg('p = " 7 "').get_period("p") == Period(0, 0, 7)


# up03: fractional is rejected — period is integer-only (Lightbend
# Integer.parseInt), diverging from duration/bytes which accept fractional.
def test_period_fractional_rejected() -> None:
    with pytest.raises(ConfigError):
        _cfg('p = "7.5"').get_period("p")


# up04: negative periods are permitted at the accessor (Lightbend).
def test_period_negative() -> None:
    assert _cfg('p = "-7"').get_period("p") == Period(0, 0, -7)


# up05: explicit weeks unit multiplies into days.
def test_period_weeks_to_days() -> None:
    assert _cfg('p = "7w"').get_period("p") == Period(0, 0, 49)


def test_period_bare_number_scalar() -> None:
    assert _cfg("p = 7").get_period("p") == Period(0, 0, 7)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("7d", Period(0, 0, 7)),
        ("7 days", Period(0, 0, 7)),
        ("2 week", Period(0, 0, 14)),
        ("3m", Period(0, 3, 0)),
        ("3mo", Period(0, 3, 0)),
        ("3 months", Period(0, 3, 0)),
        ("1y", Period(1, 0, 0)),
        ("10 years", Period(10, 0, 0)),
    ],
)
def test_period_units(raw: str, expected: Period) -> None:
    assert _cfg(f'p = "{raw}"').get_period("p") == expected


# Unit names are case-sensitive, lowercase only (HOCON.md L1304 — the S19.8
# duration rule applies to periods too).
@pytest.mark.parametrize("raw", ["7D", "7 Days", "1Y", "3 Months"])
def test_period_uppercase_unit_rejected(raw: str) -> None:
    with pytest.raises(ConfigError):
        _cfg(f'p = "{raw}"').get_period("p")


@pytest.mark.parametrize("raw", ["", " ", "d", "days", "x7", "7x", "--7", "+-7"])
def test_period_invalid_strings_rejected(raw: str) -> None:
    with pytest.raises(ConfigError):
        _cfg(f'p = "{raw}"').get_period("p")


def test_period_missing_path() -> None:
    with pytest.raises(ConfigError):
        _cfg('p = "7"').get_period("missing")


def test_period_non_scalar_rejected() -> None:
    with pytest.raises(ConfigError):
        _cfg("p { a = 1 }").get_period("p")


def test_period_null_rejected() -> None:
    with pytest.raises(ConfigError):
        _cfg("p = null").get_period("p")


# i32 bounds mirror Lightbend Integer.parseInt / rs.hocon's i32 fields.
def test_period_i32_overflow_rejected() -> None:
    with pytest.raises(ConfigError):
        _cfg(f'p = "{2**31}"').get_period("p")
