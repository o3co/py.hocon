"""Spec verification wave — duration/byte unit items (S18.3, S19.1–S19.7,
S21.2/S21.3/S21.4).

Ports the sibling pins for rows this repo carried as 🤷 (S18.3, S19.1/S19.2/
S19.5–S19.7, S21.2) and completes the ⚠️ remainders of S19.3/S19.4 (full
alias batteries) and S21.3/S21.4 (two-letter and single-letter binary
ladders). Sources: go.hocon ``spec_phase5_test.go`` and the HOCON.md unit
tables (L1307–L1385), with Lightbend probes for the contested spellings.
``get_duration`` returns milliseconds as float (rs Duration parity — see
tests/test_units_default.py).
"""

from decimal import Decimal

import pytest

from hocon import ConfigError, parse
from hocon.coerce import UnitReadError, read_bytes, read_duration


def _duration_ms(value: str) -> float:
    return parse(f'd = "{value}"').get_duration("d")


def _bytes(value: str) -> float:
    return parse(f'b = "{value}"').get_bytes("b")


def _trunc(count: str, factor: int) -> int:
    """E20: the exact decimal product, truncated toward zero (Lightbend
    ``BigDecimal.toBigInteger``)."""
    return int(Decimal(count) * factor)


class TestS18_3UnitNameLettersOnly:
    """S18.3 — a unit name consists only of letters; digits inside the unit
    make the whole value invalid."""

    def test_valid_unit_parses(self) -> None:
        assert _duration_ms("10ms") == 10.0

    def test_digit_in_unit_rejected(self) -> None:
        with pytest.raises(ConfigError):
            _duration_ms("10ms2")

    def test_non_letter_symbol_in_unit_rejected(self) -> None:
        with pytest.raises(ConfigError):
            _duration_ms("10m/s")


class TestS19DurationAliases:
    """S19.1–S19.7 — every documented alias for nanoseconds, microseconds,
    milliseconds, seconds, minutes, hours, and days (plus the `sec`/`secs`
    rejection Lightbend enforces)."""

    @pytest.mark.parametrize("unit", ["ns", "nano", "nanos", "nanosecond", "nanoseconds"])
    def test_s19_1_nanosecond_aliases(self, unit: str) -> None:
        assert _duration_ms(f"1{unit}") == 1e-6

    @pytest.mark.parametrize("unit", ["us", "micro", "micros", "microsecond", "microseconds"])
    def test_s19_2_microsecond_aliases(self, unit: str) -> None:
        assert _duration_ms(f"1{unit}") == 1e-3

    @pytest.mark.parametrize("unit", ["ms", "milli", "millis", "millisecond", "milliseconds"])
    def test_s19_3_millisecond_aliases(self, unit: str) -> None:
        assert _duration_ms(f"1{unit}") == 1.0

    @pytest.mark.parametrize("unit", ["s", "second", "seconds"])
    def test_s19_4_second_aliases(self, unit: str) -> None:
        assert _duration_ms(f"1{unit}") == 1_000.0

    def test_s19_4_sec_shorthand_rejected(self) -> None:
        # "sec"/"secs" are NOT in the spec's list; Lightbend rejects them
        # (probe 2026-08-18).
        with pytest.raises(ConfigError):
            _duration_ms("1sec")

    @pytest.mark.parametrize("unit", ["m", "minute", "minutes"])
    def test_s19_5_minute_aliases(self, unit: str) -> None:
        assert _duration_ms(f"1{unit}") == 60_000.0

    @pytest.mark.parametrize("unit", ["h", "hour", "hours"])
    def test_s19_6_hour_aliases(self, unit: str) -> None:
        assert _duration_ms(f"1{unit}") == 3_600_000.0

    @pytest.mark.parametrize("unit", ["d", "day", "days"])
    def test_s19_7_day_aliases(self, unit: str) -> None:
        assert _duration_ms(f"1{unit}") == 86_400_000.0


class TestS21_2PowersOfTen:
    """S21.2 — decimal (SI, powers of 10) byte units, short and long forms.

    Magnitudes at or above 2^53 bytes hit the documented overflow guard
    (ts.hocon parity), so the EB/ZB/YB rows pin unit RECOGNITION with
    fractional counts whose product stays representable — the same shape
    Lightbend itself needs past its own Java-long ceiling (probe 2026-08-18:
    `0.001ZB` parses, `1ZB` is a range error, never an unknown unit).
    """

    @pytest.mark.parametrize(
        ("unit", "factor"),
        [
            ("kB", 10**3),
            ("MB", 10**6),
            ("GB", 10**9),
            ("TB", 10**12),
            ("PB", 10**15),
        ],
    )
    def test_short_forms(self, unit: str, factor: int) -> None:
        assert _bytes(f"1{unit}") == factor

    @pytest.mark.parametrize(
        ("unit", "factor"),
        [
            ("kilobyte", 10**3),
            ("kilobytes", 10**3),
            ("megabyte", 10**6),
            ("megabytes", 10**6),
            ("gigabyte", 10**9),
            ("gigabytes", 10**9),
            ("terabyte", 10**12),
            ("terabytes", 10**12),
            ("petabyte", 10**15),
            ("petabytes", 10**15),
        ],
    )
    def test_long_forms(self, unit: str, factor: int) -> None:
        assert _bytes(f"1{unit}") == factor

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("0.001EB", 1e-3 * 10**18),
            ("0.000001ZB", 1e-6 * 10**21),
            ("0.000000001YB", 1e-9 * 10**24),
            ("0.001exabyte", 1e-3 * 10**18),
            ("0.000001zettabytes", 1e-6 * 10**21),
            ("0.000000001yottabyte", 1e-9 * 10**24),
        ],
    )
    def test_large_units_recognised(self, value: str, expected: float) -> None:
        assert _bytes(value) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            # Binary long/short forms of the new large units; counts chosen to
            # stay under the 2^53 guard (E20: get_bytes truncates the exact byte product).
            ("1PiB", 1024**5),
            ("1pebibyte", 1024**5),
            ("1pebibytes", 1024**5),
            ("0.001EiB", _trunc("1e-3", 1024**6)),
            ("0.001exbibyte", _trunc("1e-3", 1024**6)),
            ("0.000001ZiB", _trunc("1e-6", 1024**7)),
            ("0.000001zebibytes", _trunc("1e-6", 1024**7)),
            ("0.000000001YiB", _trunc("1e-9", 1024**8)),
            ("0.000000001yobibyte", _trunc("1e-9", 1024**8)),
        ],
    )
    def test_large_binary_units_recognised(self, value: str, expected: float) -> None:
        assert _bytes(value) == expected

    def test_magnitude_past_the_guard_overflows(self) -> None:
        # A ConfigError carrying the key path, like every other get_bytes
        # failure (it used to leak a bare OverflowError).
        with pytest.raises(ConfigError, match="byte size overflows .* at b") as e:
            _bytes("1EB")
        assert e.value.path == "b"

    def test_powers_of_ten_distinct_from_powers_of_two(self) -> None:
        # 1K (binary shorthand) is 1024; 1kB (SI) is 1000.
        assert _bytes("1K") == 1024
        assert _bytes("1kB") == 1000

    @pytest.mark.parametrize(
        "bad",
        ["1KB", "1kb", "1Kb", "1mB", "1Kilobyte", "1MEGABYTES", "1kiB", "1ki", "1Byte", "1pb"],
    )
    def test_lightbend_case_sensitivity_rejections(self, bad: str) -> None:
        # Lightbend's unit table is case-sensitive: `kB` parses, every case
        # variant here is an error (probe 2026-08-18). The ts-port
        # case-insensitive fallback and lowercase alias rows were removed in
        # the four-impl units audit.
        with pytest.raises(ConfigError):
            _bytes(bad)

    def test_two_case_exceptions_kept(self) -> None:
        # The bare byte unit and the single-letter -Xmx forms accept both
        # cases, exactly as Lightbend does.
        assert _bytes("1B") == 1
        assert _bytes("1b") == 1
        assert _bytes("1K") == _bytes("1k") == 1024


class TestS21_3TwoLetterBinaryPrefixes:
    """S21.3 — Ki/Mi/Gi/... two-letter forms equal their KiB/MiB/... spellings."""

    @pytest.mark.parametrize(
        ("unit", "power"),
        [("Ki", 1), ("Mi", 2), ("Gi", 3), ("Ti", 4), ("Pi", 5)],
    )
    def test_two_letter_forms(self, unit: str, power: int) -> None:
        assert _bytes(f"1{unit}") == 1024**power

    @pytest.mark.parametrize(
        ("value", "power", "count"),
        [("0.001Ei", 6, 1e-3), ("0.000001Zi", 7, 1e-6), ("0.000000001Yi", 8, 1e-9)],
    )
    def test_two_letter_large_forms(self, value: str, power: int, count: float) -> None:
        # Ei/Zi/Yi at count 1 exceed the 2^53 guard; fractional counts pin
        # unit recognition (E20: get_bytes truncates the exact byte product).
        assert _bytes(value) == _trunc(repr(count), 1024**power)

    def test_matches_full_spelling(self) -> None:
        assert _bytes("1Ki") == _bytes("1KiB") == 1024


class TestS21_4SingleLetterBinary:
    """S21.4 — single letters are powers of two (java -Xmx convention),
    through the full prefix ladder."""

    @pytest.mark.parametrize(
        ("unit", "power"),
        [("K", 1), ("k", 1), ("M", 2), ("m", 2), ("G", 3), ("g", 3),
         ("T", 4), ("t", 4), ("P", 5), ("p", 5)],
    )
    def test_single_letters(self, unit: str, power: int) -> None:
        assert _bytes(f"1{unit}") == 1024**power

    @pytest.mark.parametrize(
        ("value", "power", "count"),
        [
            # 1E/1Z/1Y exceed the 2^53 guard, so unit recognition is pinned
            # with fractional counts; get_bytes truncates the exact byte product (E20).
            ("0.001E", 6, 1e-3),
            ("0.001e", 6, 1e-3),
            ("0.000001Z", 7, 1e-6),
            ("0.000001z", 7, 1e-6),
            ("0.000000001Y", 8, 1e-9),
            ("0.000000001y", 8, 1e-9),
        ],
    )
    def test_e_z_y_recognised(self, value: str, power: int, count: float) -> None:
        assert _bytes(value) == _trunc(repr(count), 1024**power)


class TestE20ExactByteProduct:
    """E20 — the byte product is exact before truncation, whatever the number
    of digits, and huge counts are rejected cheaply as overflow."""

    def test_long_fraction_is_not_rounded_before_truncation(self) -> None:
        # 65 nines: a 60-digit context would round the product up to 1000.
        assert _bytes("0." + "9" * 65 + "kB") == 999
        assert _bytes("0." + "9" * 65 + "KiB") == 1023

    def test_truncation_happens_before_the_sign_check(self) -> None:
        # -0.5 bytes truncates to 0 and is accepted (Lightbend: toBigInteger,
        # then signum); -500 bytes is rejected.
        assert _bytes("-0.0005kB") == 0
        with pytest.raises(ConfigError, match="non-negative"):
            _bytes("-0.5kB")

    def test_truncated_product_at_the_guard(self) -> None:
        # 9007199254740991.9 bytes truncates to 2^53 - 1, which is in range.
        assert _bytes("9007199254740.9919kB") == 2**53 - 1
        # A long fraction must not round up past the guard in the range check.
        assert _bytes("9007199254740991.9999999999999") == 2**53 - 1
        assert _bytes("9007199254740.9919999999999999999999999kB") == 2**53 - 1
        with pytest.raises(ConfigError, match="overflows"):
            _bytes("9007199254741kB")

    # The huge-count cases call the readers directly: lexing a megabyte of
    # config text would dominate the test, and the getters' mapping of
    # UnitReadError to ConfigError is pinned above.
    @pytest.mark.parametrize("unit", ["B", "kB", ""])
    def test_huge_count_is_an_overflow_error(self, unit: str) -> None:
        # Rejected by magnitude before any big-number arithmetic (no slow
        # int conversion, no decimal.Overflow escaping as a bare exception).
        with pytest.raises(UnitReadError) as e:
            read_bytes("1" + "0" * 1_000_000 + unit)
        assert e.value.problem == "overflow"

    def test_duration_rounds_once_for_long_inputs(self) -> None:
        # E20: a float result is rounded once, at the end. A 60-digit
        # intermediate rounding would give 9007199254740996.0 here.
        value = "9007199254740994." + "9" * 70 + "ms"
        assert read_duration(value) == 9007199254740994.0
        # A non-terminating output conversion still rounds once: 7 min in h.
        assert read_duration("7m", "h") == 7 / 60


class TestE21DurationOverflow:
    """E21 — a duration past the float range is an error, never ±inf."""

    @pytest.mark.parametrize("sign", ["", "-"])
    def test_huge_duration_is_an_overflow_error(self, sign: str) -> None:
        # Also never a bare decimal.Overflow. The reader is called directly:
        # lexing a megabyte of config text would dominate the test.
        with pytest.raises(UnitReadError) as e:
            read_duration(sign + "1" + "0" * 1_000_000 + "d")
        assert e.value.problem == "overflow"

    def test_overflow_only_in_the_output_unit(self) -> None:
        # 1e305 ms is finite; the same value in ns is not.
        value = "1" + "0" * 305 + "ms"
        assert read_duration(value) == 1e305
        with pytest.raises(UnitReadError, match="duration overflows"):
            read_duration(value, "ns")


class TestS18_1NumberValueDefaultUnit:
    """S18.1 — a number value (unquoted) takes the default unit, through the
    same reader as a string: ms for durations, bytes for byte sizes."""

    def test_number_duration_is_milliseconds(self) -> None:
        cfg = parse("t = 500, f = 1.5")
        assert cfg.get_duration("t") == 500.0
        assert cfg.get_duration("t", "s") == 0.5
        assert cfg.get_duration("f") == 1.5

    def test_number_byte_size_is_bytes(self) -> None:
        cfg = parse("b = 1024, f = 1024.9")
        assert cfg.get_bytes("b") == 1024
        assert cfg.get_bytes("f") == 1024  # truncated toward zero (S21.5)
        assert cfg.get_bytes("b", "KiB") == 1.0


class TestE20ExponentForms:
    """E20 exponent forms (xx.hocon#111): `[+-]? (digits [. digits?] | . digits)
    ([eE] [+-]? digits)?` before the unit; huge exponents decided without
    big-number work; periods stay integer-only."""

    @pytest.mark.parametrize(
        ("value", "ms"),
        [
            ("-1e3ms", -1000.0),
            ("1e3 ms", 1000.0),
            ("1.e3ms", 1000.0),
            ("1e-400s", 0.0),
            ("0e999999999s", 0.0),
            (".5s", 500.0),
            ("+2E0s", 2000.0),
            ("1e" + "0" * 5000 + "1ms", 10.0),  # zero-padded exponent
        ],
    )
    def test_duration_values(self, value: str, ms: float) -> None:
        assert _duration_ms(value) == ms

    # A malformed number part ("1e3.5ms", "e3s", "1e+s", "1ee3s"), or a well-formed
    # number followed by an unknown unit ("1e3e" is 1e3 + unit "e", "1e" is 1 + "e").
    @pytest.mark.parametrize("value", ["1e3.5ms", "1e3e", "1e", "e3s", "1e+s", "1ee3s"])
    def test_malformed_number_or_unknown_unit_is_invalid(self, value: str) -> None:
        with pytest.raises(ConfigError, match="invalid duration"):
            _duration_ms(value)

    @pytest.mark.parametrize("value", ["1e999999999s", "1e" + "9" * 40 + "s", "-1e400ms"])
    def test_huge_exponent_is_an_overflow_error_at_once(self, value: str) -> None:
        with pytest.raises(UnitReadError) as e:
            read_duration(value)
        assert e.value.problem == "overflow"

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("1e-999999999kB", 0),
            ("1e-" + "9" * 40 + "B", 0),
            ("0e20B", 0),
            ("9.007199254740991e15B", 2**53 - 1),
            ("1e" + "0" * 5000 + "3B", 1000),  # zero-padded exponent
        ],
    )
    def test_byte_values(self, value: str, expected: int) -> None:
        assert read_bytes(value) == expected

    @pytest.mark.parametrize("value", ["1e999999999B", "9.007199254740992e15B", "-1e400B"])
    def test_huge_byte_size_is_an_overflow_error(self, value: str) -> None:
        with pytest.raises(UnitReadError) as e:
            read_bytes(value)
        assert e.value.problem == "overflow"

    def test_period_stays_integer_only(self) -> None:
        with pytest.raises(ConfigError, match="invalid period"):
            parse('p = "1e2d"').get_period("p")
