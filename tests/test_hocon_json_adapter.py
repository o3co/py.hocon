"""Tests for the differential-harness adapter ``tools/hocon_json.py``.

The adapter is what registers py.hocon in xx.hocon's cross-impl differential
driver (``generate/DifferentialDriver.java``, ``IMPLS``). Two things are checked:

1. **Oracle differential** — for every spec-corpus fixture the adapter's success
   output, normalized, equals the Lightbend-generated expected JSON. Because the
   expected files ARE the Lightbend oracle, this is an in-repo differential check
   against the reference implementation for the whole success corpus (run
   in-process for speed; a full ``make differential`` under xx.hocon additionally
   compares error records and env-substitution cases against a live oracle).
2. **CLI contract** — exit 0 + JSON on success, exit 3 + ``__error__`` record on
   parse/resolve error, exit 2 on usage error, and env substitutions resolving
   against the *process* environment (the driver's hermeticity lever).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).parent
_ADAPTER = _HERE.parent / "tools" / "hocon_json.py"
_TESTDATA = _HERE / "conformance" / "testdata"
_EXPECTED = _TESTDATA / "expected"
_CONF = _TESTDATA / "hocon"

# JVM system-property fixtures (${?java.version} / ${?user.home}) — non-JVM
# parsers cap here exactly as in the conformance harness.
_JVM_SKIP = {"test01", "test03"}

pytestmark = pytest.mark.skipif(
    not _EXPECTED.is_dir() or not _CONF.is_dir(),
    reason="conformance corpus not synced — run `make testdata`",
)


def _load_adapter() -> Any:
    spec = importlib.util.spec_from_file_location("hocon_json_adapter", _ADAPTER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_adapter = _load_adapter()


def _norm(v: Any) -> Any:
    """Canonicalize a JSON value (same rules as the conformance harness:
    key order ignored, numbers by value, null-valued keys dropped)."""
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


def _spec_fixtures() -> list[tuple[str, Path, Any]]:
    out: list[tuple[str, Path, Any]] = []
    if not _EXPECTED.is_dir():
        return out
    for root, _dirs, files in os.walk(_EXPECTED):
        for f in files:
            if not f.endswith("-expected.json") or f.endswith("-expected-error.json"):
                continue
            rel = Path(root, f).relative_to(_EXPECTED).as_posix()
            base = rel[: -len("-expected.json")]
            if base.startswith("empty-file/") or base in _JVM_SKIP:
                continue
            conf = _CONF / (base + ".conf")
            if not conf.exists():
                continue
            try:
                exp = json.loads((_EXPECTED / rel).read_text(encoding="utf-8"))
            except Exception:
                continue
            out.append((base, conf, exp))
    out.sort(key=lambda t: t[0])
    return out


_SPEC = _spec_fixtures()


@pytest.mark.parametrize("base,conf,expected", [pytest.param(b, c, e, id=b) for b, c, e in _SPEC])
def test_adapter_matches_oracle(base: str, conf: Path, expected: Any, capsys: Any) -> None:
    """Adapter success output equals the Lightbend expected tree (in-process)."""
    sidecar = conf.with_suffix(".env")
    env_backup = dict(os.environ)
    if sidecar.exists():
        for line in sidecar.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, val = line.split("=", 1)
                os.environ[k] = val
    try:
        code = _adapter.main(["hocon-json", str(conf)])
        out = capsys.readouterr().out
    finally:
        os.environ.clear()
        os.environ.update(env_backup)
    assert code == 0, f"{base}: adapter exited {code} (out={out!r})"
    assert _norm(json.loads(out)) == _norm(expected), base


def test_adapter_corpus_non_empty() -> None:
    assert len(_SPEC) > 100, "spec corpus looks too small — run `make testdata`"


def _run(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_ADAPTER), *args],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )


def test_cli_usage_error() -> None:
    r = _run([])
    assert r.returncode == 2
    assert "usage:" in r.stderr


def test_cli_success_exit_zero() -> None:
    conf = next(c for _, c, _ in _SPEC)
    r = _run([str(conf)])
    assert r.returncode == 0
    json.loads(r.stdout)  # valid JSON


def test_cli_parse_error_record() -> None:
    err_conf = _CONF / "empty-file" / "ef01-empty.conf"
    if not err_conf.exists():
        pytest.skip("empty-file fixture not present")
    r = _run([str(err_conf)])
    assert r.returncode == 3
    rec = json.loads(r.stdout)
    assert "__error__" in rec
    assert set(rec["__error__"]) >= {"type", "message"}


def test_cli_env_resolves_against_process_env(tmp_path: Path) -> None:
    """Adapter reads the process environment (the driver's hermeticity lever) —
    it must NOT hard-code env={}, or the driver's env-substitution cases break."""
    conf = tmp_path / "e.conf"
    conf.write_text('x = ${HOCON_ADAPTER_PROBE}\n', encoding="utf-8")
    r = _run([str(conf)], env={"HOCON_ADAPTER_PROBE": "sentinel"})
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"x": "sentinel"}
