"""xx.hocon conformance harness.

Discovers every ``<base>-expected.json`` under ``testdata/expected/`` (synced by
``make testdata``), maps it to ``testdata/hocon/<base>.conf``, parses the fixture
with py.hocon, and compares the resolved tree against the Lightbend-generated
expected JSON — using the same normalization as the shared ecosystem-bench
driver (key order ignored, numbers by value, null-valued keys dropped, ``.env``
sidecars loaded).

Two fixture groups are held outside the pass/fail corpus, matching the
ecosystem-bench method (see xx.hocon ``docs/ecosystem-conformance.md`` §Method):

- **empty-file (6)** — documented Lightbend-vs-strict divergence (E10). Lightbend
  accepts an empty/comment-only file as ``{}``; the o3co implementations reject
  it per spec §L130. ``test_empty_file_rejected`` asserts py.hocon rejects them,
  matching its siblings.
- **JVM system-property (test01, test03)** — reference ``${?java.version}`` /
  ``${?user.home}``, which resolve only inside a JVM. Every non-JVM parser
  (go.hocon / rs.hocon / ts.hocon included) caps at 14/16 here; marked xfail.

Error fixtures (``-expected-error.json``) are not part of the corpus either.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

import hocon
from hocon import ParseError

_HERE = Path(__file__).parent
_TESTDATA = _HERE / "testdata"
_EXPECTED = _TESTDATA / "expected"
_CONF = _TESTDATA / "hocon"

# Held-out fixtures (see module docstring).
_JVM_XFAIL = {"test01", "test03"}

pytestmark = pytest.mark.skipif(
    not _EXPECTED.is_dir() or not _CONF.is_dir(),
    reason="conformance corpus not synced — run `make testdata`",
)


def _norm(v: Any) -> Any:
    """Canonicalize a JSON value for comparison (mirrors ecosystem-bench driver.py)."""
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if isinstance(v, bool):
        return ("bool", v)
    if isinstance(v, (int, float)):
        return ("num", float(v))
    if v is None:
        return ("null",)
    return ("str", v)


def _discover() -> list[tuple[str, Path, Any]]:
    fixtures: list[tuple[str, Path, Any]] = []
    if not _EXPECTED.is_dir():
        return fixtures
    for root, _dirs, files in os.walk(_EXPECTED):
        for f in files:
            if not f.endswith("-expected.json") or f.endswith("-expected-error.json"):
                continue
            # Posix-normalized so the group-prefix holdouts below match on
            # Windows too (os.walk yields backslash separators there).
            rel = Path(root, f).relative_to(_EXPECTED).as_posix()
            base = rel[: -len("-expected.json")]
            # empty-file group is a documented divergence — held out (see docstring).
            if base.startswith("empty-file/"):
                continue
            conf = _CONF / (base + ".conf")
            if not conf.exists():
                continue
            try:
                exp = json.loads((_EXPECTED / rel).read_text(encoding="utf-8"))
            except Exception:
                continue
            fixtures.append((base, conf, exp))
    fixtures.sort(key=lambda t: t[0])
    return fixtures


def _load_env_sidecar(conf: Path) -> dict[str, str]:
    """Env for a fixture = its ``.env`` sidecar only (ambient os.environ is NOT
    included, keeping the run deterministic)."""
    env: dict[str, str] = {}
    sidecar = conf.with_suffix(".env")
    if sidecar.exists():
        for line in sidecar.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, val = line.split("=", 1)
                env[k] = val
    return env


def _params() -> list:
    params = []
    for base, conf, expected in _discover():
        marks = []
        if base in _JVM_XFAIL:
            marks.append(
                pytest.mark.xfail(
                    reason="JVM system property (${?java.version}/${?user.home}); "
                    "non-JVM parsers cap at 14/16",
                    strict=False,
                )
            )
        params.append(pytest.param(base, conf, expected, id=base, marks=marks))
    return params


_PARAMS = _params()


@pytest.mark.parametrize("base,conf,expected", _PARAMS)
def test_fixture(base: str, conf: Path, expected: Any) -> None:
    env = _load_env_sidecar(conf)
    cfg = hocon.parse_file(str(conf), env=env)
    got = json.loads(cfg._render_json_for_test())
    assert _norm(got) == _norm(expected)


def test_corpus_non_empty() -> None:
    # Guard against a silently-missing corpus producing a green run.
    assert len(_PARAMS) > 100, "conformance corpus looks too small — run `make testdata`"


def _empty_file_fixtures() -> list[Path]:
    group = _CONF / "empty-file"
    return sorted(group.glob("*.conf")) if group.is_dir() else []


@pytest.mark.parametrize(
    "conf", _empty_file_fixtures(), ids=[p.stem for p in _empty_file_fixtures()]
)
def test_empty_file_rejected(conf: Path) -> None:
    """E10 divergence: py.hocon rejects empty/comment-only files (spec §L130),
    matching its siblings, where Lightbend would accept them as ``{}``."""
    with pytest.raises(ParseError):
        hocon.parse_file(str(conf))
