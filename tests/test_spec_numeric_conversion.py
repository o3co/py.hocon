"""Spec verification wave — numerically-indexed objects and type conversion
(S15.1/S15.4/S15.5/S15.6/S15.7, S17.1/S17.2/S17.3/S17.4/S17.8).

Ports the sibling pins for rows this repo carried as 🤷: ts.hocon
``tests/config.test.ts`` / ``tests/numeric-array.test.ts`` and go.hocon
``config_test.go`` / ``spec_phase5_test.go``.
"""

import pytest

from hocon import ConfigError, parse


class TestS15NumericObjectToArray:
    """S15 — {"0": ..., "1": ...} converts to an array when an array is
    requested through the getter API."""

    def test_s15_1_basic_conversion(self) -> None:
        cfg = parse('items = {"0":"a","1":"b"}')
        assert cfg.get_list("items") == ["a", "b"]

    def test_s15_4_empty_object_not_converted(self) -> None:
        cfg = parse("items = {}")
        with pytest.raises(ConfigError):
            cfg.get_list("items")

    def test_s15_5_non_integer_keys_ignored(self) -> None:
        cfg = parse('items = {"0":"a","foo":"b","1":"c"}')
        assert cfg.get_list("items") == ["a", "c"]

    def test_s15_6_missing_indices_compacted(self) -> None:
        cfg = parse('items = {"0":"a","2":"c"}')
        assert cfg.get_list("items") == ["a", "c"]

    def test_s15_7_sorted_by_integer_key(self) -> None:
        cfg = parse('items = {"1":"b","0":"a"}')
        assert cfg.get_list("items") == ["a", "b"]


class TestS17TypeConversion:
    """S17.1–S17.4 — implicit conversions through the typed getters, and
    S17.8 — array → other must error."""

    def test_s17_1_number_to_string(self) -> None:
        cfg = parse("n = 42\nf = 1.5")
        assert cfg.get_string("n") == "42"
        assert cfg.get_string("f") == "1.5"

    def test_s17_2_boolean_to_string(self) -> None:
        cfg = parse("t = true\nf = false")
        assert cfg.get_string("t") == "true"
        assert cfg.get_string("f") == "false"

    def test_s17_3_string_to_number(self) -> None:
        cfg = parse('n = "42"\nf = "1.5"')
        assert cfg.get_int("n") == 42
        assert cfg.get_number("n") == 42
        assert cfg.get_float("f") == 1.5

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("true", True),
            ("yes", True),
            ("on", True),
            ("false", False),
            ("no", False),
            ("off", False),
        ],
    )
    def test_s17_4_string_to_bool(self, raw: str, expected: bool) -> None:
        cfg = parse(f'b = "{raw}"')
        assert cfg.get_boolean("b") is expected

    def test_s17_8_array_to_other_errors(self) -> None:
        cfg = parse("val = [1, 2, 3]")
        with pytest.raises(ConfigError):
            cfg.get_string("val")
        with pytest.raises(ConfigError):
            cfg.get_number("val")
        with pytest.raises(ConfigError):
            cfg.get_boolean("val")
        with pytest.raises(ConfigError):
            cfg.get_config("val")
