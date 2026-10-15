"""S18.4 units-default fixture harness — duration / bytes / negative families.

Drives the xx.hocon fixtures under ``tests/conformance/testdata/hocon/units-default/``
(synced by ``make testdata``) against :meth:`Config.get_duration` /
:meth:`Config.get_bytes`, porting rs.hocon ``tests/units_default_test.rs`` (the
reference implementation for accessor semantics) with go.hocon
``spec_s18_units_default_test.go`` as a second opinion.

Families covered here (the up01–up05 period scenarios are inlined in
``tests/test_period.py`` and are NOT duplicated):

- ud01–ud08  duration (bare int, WS variants, fractional, negative, unit regressions)
- ud09–ud11  duration, E20 exact decimal arithmetic
- ud12–ud13  duration, E21 overflow is an error (integer and fractional form)
- ud14–ud20  duration, E20 exponent forms (xx.hocon#111)
- ub01–ub06  bytes (bare int, WS, fractional-truncated, negative-accessor, unit, empty)
- ub07–ub08  bytes, E20 exact product then truncation
- ub09–ub13  bytes, E20 exponent forms (xx.hocon#111)
- un01–un03  cross-family negative edge cases (empty, WS-only, unit-only)

S-items pinned: S18.1 (number default unit, via the same parse path), S18.2
(ws+number+ws+unit+ws), S18.4 (no unit → default unit, HOCON.md L1290), S19.3
(``ms``), S19.8 (regression guards keep lowercase units working), S21.1 (default
bytes), S21.4 (single-letter ``K`` = 1024, L1385), S21.5 (fractional bytes).

rs → py expectation mapping
---------------------------
- rs ``get_duration`` returns ``std::time::Duration``; py returns **float
  milliseconds** by default, with an optional output-unit parameter. rs
  ``Duration::from_millis(500)`` ⇒ py ``get_duration(p) == 500.0``; rs
  ``.as_nanos() == 500_500_000`` ⇒ py ``get_duration(p) == 500.5`` (ms) and
  ``get_duration(p, "ns") == 500_500_000.0``.
- rs ``get_bytes`` returns ``i64`` bytes; py returns a number of bytes (default
  unit ``"B"``). Values compare directly.
- rs ``Err(...)`` ⇒ py raises :class:`ConfigError`.
- **ud06 caveat**: rs pins ``Err`` for ``"-500"`` only because
  ``std::time::Duration`` is unsigned — an rs-specific limitation documented in
  rs's own test + CHANGELOG. Lightbend's ``java.time.Duration`` is signed and
  go pins ``-500ms``. py's float is signed and returns ``-500.0``, matching
  Lightbend/go. Both facts are pinned below: the Lightbend-faithful value as a
  passing test, and the literal rs expectation as ``xfail(strict=True)``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import hocon
from hocon import Config, ConfigError

_FIXTURES = Path(__file__).parent / "conformance" / "testdata" / "hocon" / "units-default"

pytestmark = pytest.mark.skipif(
    not _FIXTURES.is_dir(),
    reason="conformance corpus not synced — run `make testdata`",
)


def _load(name: str) -> Config:
    """Load a units-default fixture (mirrors rs.hocon's ``load`` helper).

    ``env={}`` keeps the parse deterministic: ``parse_file`` otherwise captures
    ``dict(os.environ)`` by default, and CI results must not depend on ambient
    environment (same convention as ``tests/conformance/test_conformance.py``)."""
    return hocon.parse_file(str(_FIXTURES / name), env={})


# ─────────────────────────────────────────────────────────────────────────────
# Duration family (ud01–ud08)
# ─────────────────────────────────────────────────────────────────────────────


# ud01: bare integer string "500" → 500 ms (default unit, S18.4).
def test_ud01_duration_bare() -> None:
    assert _load("ud01-duration-bare.conf").get_duration("t") == 500.0


# ud02: leading whitespace '" 500"' → still 500 ms (S18.2 optional leading ws).
def test_ud02_duration_leading_ws() -> None:
    assert _load("ud02-duration-leading-ws.conf").get_duration("t") == 500.0


# ud03: trailing whitespace '"500 "' → still 500 ms (S18.2 optional trailing ws).
def test_ud03_duration_trailing_ws() -> None:
    assert _load("ud03-duration-trailing-ws.conf").get_duration("t") == 500.0


# ud04: leading + trailing whitespace '" 500 "' → still 500 ms.
def test_ud04_duration_both_ws() -> None:
    assert _load("ud04-duration-both-ws.conf").get_duration("t") == 500.0


# ud05: fractional "500.5" is ACCEPTED (Lightbend Double×nanos path). rs pins
# .as_nanos() == 500_500_000; in py conventions that is 500.5 ms by default and
# 500_500_000.0 via the "ns" output unit.
def test_ud05_duration_fractional() -> None:
    cfg = _load("ud05-duration-fractional.conf")
    assert cfg.get_duration("t") == 500.5
    assert cfg.get_duration("t", "ns") == 500_500_000.0


# ud06: negative "-500" → -500 ms. Lightbend java.time.Duration is signed and
# go.hocon pins -500ms; py's float duration is signed too. rs.hocon Errs here
# only because std::time::Duration is unsigned (documented rs-specific
# divergence, see rs CHANGELOG) — that literal rs expectation is pinned as
# strict-xfail in the companion test below.
def test_ud06_duration_negative_lightbend_signed() -> None:
    assert _load("ud06-duration-negative.conf").get_duration("t") == -500.0


# ud06 (rs literal expectation): get_duration("-500") must raise. py diverges
# deliberately (signed float, Lightbend/go-faithful), so this is a strict xfail
# documenting the cross-impl divergence rather than a py bug.
@pytest.mark.xfail(
    strict=True,
    reason=(
        "ud06: rs.hocon pins Err for '-500' because std::time::Duration is unsigned "
        "(rs-specific limitation, rs CHANGELOG); py returns signed -500.0 ms, "
        "matching Lightbend java.time.Duration and go.hocon (-500ms)"
    ),
)
def test_ud06_duration_negative_rs_expectation() -> None:
    with pytest.raises(ConfigError):
        _load("ud06-duration-negative.conf").get_duration("t")


# ud07: explicit unit "500ms" → 500 ms (S19.3 regression guard for S18.2 path).
def test_ud07_duration_with_unit() -> None:
    assert _load("ud07-duration-with-unit.conf").get_duration("t") == 500.0


# ud08: whitespace between number and unit "500 ms" → 500 ms (S18.2 regression).
def test_ud08_duration_ws_between() -> None:
    assert _load("ud08-duration-ws-between.conf").get_duration("t") == 500.0


# ud09–ud11 (E20): the numeric part is an exact decimal and the unit product is
# exact, so a fractional duration that is exact in decimal stays exact (no
# 1000.9999999999999 ms, no Lightbend-style 1000999999 ns).
def test_ud09_duration_fractional_exact() -> None:
    cfg = _load("ud09-duration-fractional-exact.conf")
    assert cfg.get_duration("t") == 1001.0
    assert cfg.get_duration("t", "ns") == 1_001_000_000.0


def test_ud10_duration_fractional_exact_hours() -> None:
    cfg = _load("ud10-duration-fractional-exact-hours.conf")
    assert cfg.get_duration("t") == 8_280_000.0
    assert cfg.get_duration("t", "ns") == 8_280_000_000_000.0


def test_ud11_duration_fractional_exact_no_unit() -> None:
    cfg = _load("ud11-duration-fractional-exact-no-unit.conf")
    assert cfg.get_duration("t") == 1.001
    assert cfg.get_duration("t", "ns") == 1_001_000.0


# ud12–ud13 (E21): a duration the implementation cannot represent is an error.
# py's float output overflows past ~1.8e308 in the requested unit; it must
# raise rather than return inf, for the integer and the fractional form alike.
def test_ud12_duration_overflow_rejected() -> None:
    cfg = _load("ud12-duration-overflow-rejected.conf")
    with pytest.raises(ConfigError, match="duration overflows"):
        cfg.get_duration("t")


def test_ud13_duration_overflow_fractional_rejected() -> None:
    cfg = _load("ud13-duration-overflow-fractional-rejected.conf")
    with pytest.raises(ConfigError, match="duration overflows"):
        cfg.get_duration("t")


# ud14–ud20 (E20 exponent forms, xx.hocon#111): the number part of a unit value
# may carry an exponent, computed exactly; Lightbend 1.4.6 reads them all.
@pytest.mark.parametrize(
    ("name", "ms"),
    [
        ("ud14-duration-exponent-unit.conf", 100_000.0),  # "1e+5ms"
        ("ud15-duration-exponent-fraction.conf", 150_000.0),  # "1.5e2s"
        ("ud16-duration-exponent-no-unit.conf", 1_000.0),  # "1E3"
        ("ud17-duration-exponent-number-value.conf", 1_000.0),  # 1e3 (NUMBER)
        ("ud18-duration-negative-exponent.conf", 1.0),  # "1e-3s"
    ],
)
def test_ud14_ud18_duration_exponent_forms(name: str, ms: float) -> None:
    assert _load(name).get_duration("t") == ms


def test_ud18_duration_negative_exponent_in_ns() -> None:
    assert _load("ud18-duration-negative-exponent.conf").get_duration("t", "ns") == 1_000_000.0


def test_ud19_duration_exponent_overflow() -> None:
    # E21: "1e400s" is past the float range — an error (Lightbend saturates).
    with pytest.raises(ConfigError, match="duration overflows"):
        _load("ud19-duration-exponent-overflow.conf").get_duration("t")


def test_ud20_duration_exponent_bad_mantissa() -> None:
    with pytest.raises(ConfigError, match="invalid duration"):  # "1e3.5ms"
        _load("ud20-duration-exponent-bad-mantissa.conf").get_duration("t")


# ─────────────────────────────────────────────────────────────────────────────
# Bytes family (ub01–ub08)
# ─────────────────────────────────────────────────────────────────────────────


# ub01: bare integer string "1024" → 1024 bytes (default unit = bytes, S18.4/S21.1).
def test_ub01_bytes_bare() -> None:
    assert _load("ub01-bytes-bare.conf").get_bytes("b") == 1024


# ub02: whitespace-padded '" 1024 "' → 1024 bytes.
def test_ub02_bytes_leading_trailing_ws() -> None:
    assert _load("ub02-bytes-leading-trailing-ws.conf").get_bytes("b") == 1024


# ub03: fractional "1024.5" → 1024 bytes, truncated toward zero (Lightbend
# BigDecimal.toBigInteger — NOT rounded to 1025). S21.5 fractional path.
def test_ub03_bytes_fractional_truncated() -> None:
    assert _load("ub03-bytes-fractional-truncated.conf").get_bytes("b") == 1024


# ub04: negative "-1" → rejected at the ACCESSOR layer (Lightbend positive-only
# invariant on byte sizes; diverges from duration/period which allow negatives).
def test_ub04_bytes_negative_accessor_rejects() -> None:
    with pytest.raises(ConfigError):
        _load("ub04-bytes-negative-accessor-rejects.conf").get_bytes("b")


# ub05: "1024K" → 1_048_576 bytes (single-letter K = 1024 binary, S21.4,
# HOCON.md L1385 — Lightbend ground truth; NOT SI-decimal 1_024_000).
def test_ub05_bytes_with_unit() -> None:
    assert _load("ub05-bytes-with-unit.conf").get_bytes("b") == 1_048_576


# ub06: empty string "" → raises (no number to parse, HOCON.md L1284).
def test_ub06_bytes_empty_rejected() -> None:
    with pytest.raises(ConfigError):
        _load("ub06-bytes-empty-rejected.conf").get_bytes("b")


# ub07 (E20): exact product, then truncate toward zero — 1.0009kB is 1000.9
# bytes, so 1000 (rounding, half-up or half-even, would give 1001). The
# truncation happens in bytes, before any output-unit conversion.
def test_ub07_bytes_fractional_unit_truncated() -> None:
    cfg = _load("ub07-bytes-fractional-unit-truncated.conf")
    assert cfg.get_bytes("b") == 1000
    assert cfg.get_bytes("b", "KB") == 1.0


# ub08 (E20): the product is exact before truncation — 1.001kB is 1001 bytes
# (a float product, 1000.9999999999999, would truncate to 1000).
def test_ub08_bytes_fractional_unit_exact() -> None:
    cfg = _load("ub08-bytes-fractional-unit-exact.conf")
    assert cfg.get_bytes("b") == 1001
    assert cfg.get_bytes("b", "KB") == 1.001


# ub09–ub13 (E20 exponent forms): exact product, truncated toward zero.
def test_ub09_ub12_bytes_exponent_forms() -> None:
    assert _load("ub09-bytes-exponent-unit.conf").get_bytes("b") == 1_000_000  # "1e3kB"
    assert _load("ub10-bytes-exponent-no-unit.conf").get_bytes("b") == 1_000  # "1e3"
    assert _load("ub11-bytes-exponent-binary.conf").get_bytes("b") == 204_800  # "2E2KiB"
    cfg = _load("ub12-bytes-negative-exponent-truncated.conf")
    assert cfg.get_bytes("b") == 1  # "1e-3kB"
    assert cfg.get_bytes("b2") == 1_000  # "1.0005e3B" truncates


def test_ub13_bytes_exponent_overflow() -> None:
    with pytest.raises(ConfigError, match="byte size overflows"):  # "1e400B"
        _load("ub13-bytes-exponent-overflow.conf").get_bytes("b")


# ─────────────────────────────────────────────────────────────────────────────
# Cross-family negative edge cases (un01–un03)
# ─────────────────────────────────────────────────────────────────────────────


# un01: empty string "" → get_duration raises (no number, HOCON.md L1284).
def test_un01_empty_duration() -> None:
    with pytest.raises(ConfigError):
        _load("un01-empty-duration.conf").get_duration("t")


# un02: whitespace-only '"   "' → get_duration raises.
def test_un02_ws_only_duration() -> None:
    with pytest.raises(ConfigError):
        _load("un02-ws-only-duration.conf").get_duration("t")


# un03: unit-only "ms" → get_duration raises (number is required per L1284).
def test_un03_unit_only_duration() -> None:
    with pytest.raises(ConfigError):
        _load("un03-unit-only-duration.conf").get_duration("t")
