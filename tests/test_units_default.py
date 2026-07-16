"""S18.4 units-default fixture harness — duration / bytes / negative families.

Drives the xx.hocon fixtures under ``tests/conformance/testdata/hocon/units-default/``
(synced by ``make testdata``) against :meth:`Config.get_duration` /
:meth:`Config.get_bytes`, porting rs.hocon ``tests/units_default_test.rs`` (the
reference implementation for accessor semantics) with go.hocon
``spec_s18_units_default_test.go`` as a second opinion.

Families covered here (the up01–up05 period scenarios are inlined in
``tests/test_period.py`` and are NOT duplicated):

- ud01–ud08  duration (bare int, WS variants, fractional, negative, unit regressions)
- ub01–ub06  bytes (bare int, WS, fractional-truncated, negative-accessor, unit, empty)
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
    """Load a units-default fixture (mirrors rs.hocon's ``load`` helper)."""
    return hocon.parse_file(str(_FIXTURES / name))


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


# ─────────────────────────────────────────────────────────────────────────────
# Bytes family (ub01–ub06)
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
