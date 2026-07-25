"""F1.9 — a process-environment entry that is not valid UTF-8.

Python decodes ``os.environ`` with ``surrogateescape`` rather than failing, so
undecodable bytes survive as lone surrogates and would otherwise reach config
values as text that raises on ``.encode("utf-8")`` somewhere far away. The rule
depends on whether the caller asked for that variable: a substitution lookup
treats it as absent (F1.9a), a bulk mount of a matching prefix errors (F1.9b).

The environment has to carry real undecodable bytes for any of this to mean
anything, and it cannot be built inside the test process (``os.environ`` only
takes ``str``), so the assertions run in a child launched with a bytes environ.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows environment strings are UTF-16 and have no surrogateescape path",
)

_CHILD = r"""
import json
import hocon
from hocon.adapters import AdapterError, env

out = {}

# F1.9b — mounting the namespace that contains the undecodable entries.
try:
    cfg = env.load("APP_")
    out["bulk_app"] = {"ok": sorted(cfg.keys())}
except AdapterError as e:
    out["bulk_app"] = {"error": str(e)}

# The prefix filter bounds the check: this mount does not touch APP_*.
try:
    cfg = env.load("OTHER_")
    out["bulk_other"] = {"ok": {k: cfg.get_string(k) for k in cfg.keys()}}
except AdapterError as e:
    out["bulk_other"] = {"error": str(e)}

# F1.9a — optional substitution falls through to the default.
out["optional"] = hocon.parse('a = "default"\na = ${?APP_BAD}').get_string("a")

# F1.9a — required substitution raises the ordinary unresolved error.
try:
    hocon.parse("a = ${APP_BAD}")
    out["required"] = {"ok": "no error"}
except Exception as e:  # noqa: BLE001 - the type is the assertion
    out["required"] = {"error": type(e).__name__, "msg": str(e)}

# A decodable variable in the same environment is unaffected.
out["decodable"] = hocon.parse("a = ${OTHER_OK}").get_string("a")

# env-var list expansion reads the same map (S13c).
out["list"] = hocon.parse("a = ${LIST[]}").get_list("a")

print(json.dumps(out))
"""


def _run_child() -> dict[str, object]:
    """Run the assertions in a child whose environ carries undecodable bytes."""
    child_env: dict[bytes, bytes] = {
        k: v
        for k, v in os.environb.items()
        if k in (b"PATH", b"HOME", b"SYSTEMROOT", b"VIRTUAL_ENV")
    }
    child_env[b"PYTHONDONTWRITEBYTECODE"] = b"1"
    child_env[b"APP_BAD"] = b"\xff\xfe"  # undecodable value
    child_env[b"APP_N\xffAME"] = b"fine"  # undecodable name
    child_env[b"APP_GOOD"] = b"ok"
    child_env[b"OTHER_OK"] = b"elsewhere"
    child_env[b"LIST_0"] = b"one"
    child_env[b"LIST_1"] = b"two"

    proc = subprocess.run(
        [sys.executable, "-c", _CHILD],
        env=child_env,  # type: ignore[arg-type]  # POSIX accepts bytes pairs
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    result: dict[str, object] = json.loads(proc.stdout)
    return result


def test_undecodable_environment_entries_follow_f1_9() -> None:
    out = _run_child()

    # (b) the mount that asked for the namespace refuses it, naming the entry.
    bulk_app = out["bulk_app"]
    assert isinstance(bulk_app, dict) and "error" in bulk_app, bulk_app
    assert "F1.9" in str(bulk_app["error"])
    assert "not valid UTF-8" in str(bulk_app["error"])

    # …and the check is bounded by the prefix, so an unrelated mount is fine.
    assert out["bulk_other"] == {"ok": {"ok": "elsewhere"}}

    # (a) absent, not surrogate text: the optional form keeps its default and
    # the required form raises the ordinary unresolved error.
    assert out["optional"] == "default"
    required = out["required"]
    assert isinstance(required, dict) and required.get("error") == "ResolveError", required
    assert "could not resolve substitution" in str(required["msg"])

    # Nothing else in the environment is disturbed.
    assert out["decodable"] == "elsewhere"
    assert out["list"] == ["one", "two"]
