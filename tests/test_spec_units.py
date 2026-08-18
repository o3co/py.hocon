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

import pytest

from hocon import ConfigError, parse


def _duration_ms(value: str) -> float:
    return parse(f'd = "{value}"').get_duration("d")


def _bytes(value: str) -> float:
    return parse(f'b = "{value}"').get_bytes("b")


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
            # stay under the 2^53 guard (get_bytes rounds the byte result).
            ("1PiB", 1024**5),
            ("1pebibyte", 1024**5),
            ("1pebibytes", 1024**5),
            ("0.001EiB", round(1e-3 * 1024**6)),
            ("0.001exbibyte", round(1e-3 * 1024**6)),
            ("0.000001ZiB", round(1e-6 * 1024**7)),
            ("0.000001zebibytes", round(1e-6 * 1024**7)),
            ("0.000000001YiB", round(1e-9 * 1024**8)),
            ("0.000000001yobibyte", round(1e-9 * 1024**8)),
        ],
    )
    def test_large_binary_units_recognised(self, value: str, expected: float) -> None:
        assert _bytes(value) == expected

    def test_magnitude_past_the_guard_overflows(self) -> None:
        with pytest.raises(OverflowError):
            _bytes("1EB")

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
        # unit recognition (get_bytes rounds the byte result).
        assert _bytes(value) == round(count * 1024**power)

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
            # with fractional counts; get_bytes rounds the byte result.
            ("0.001E", 6, 1e-3),
            ("0.001e", 6, 1e-3),
            ("0.000001Z", 7, 1e-6),
            ("0.000001z", 7, 1e-6),
            ("0.000000001Y", 8, 1e-9),
            ("0.000000001y", 8, 1e-9),
        ],
    )
    def test_e_z_y_recognised(self, value: str, power: int, count: float) -> None:
        assert _bytes(value) == round(count * 1024**power)
