#!/usr/bin/env python3
"""py.hocon adapter for the cross-impl differential harness (xx.hocon/generate).

Parses + resolves a HOCON file and prints the resolved tree as canonical JSON to
stdout. On any parse/resolve error it prints a single-line
``{"__error__":{"type":..,"message":..}}`` record to stdout and exits 3, so the
differential driver can compare error-vs-success behaviour uniformly across the
go / rs / ts / py adapters and the Lightbend oracle.

Usage: ``python tools/hocon_json.py <conf-file>``

Output is produced by ``Config._render_json_for_test`` — the same canonical
renderer the conformance harness validates against the Lightbend-generated
expected JSON, so the adapter's success output is oracle-aligned by construction.
Unlike rs.hocon's renderer, py's escapes object keys (``json.dumps(k)``), so no
serde-style rebuild is needed — this mirrors ts.hocon's ``_renderJSONForTest``
adapter.

Environment substitutions resolve against the process environment; the
differential driver controls hermeticity by clearing / setting the subprocess
env, so this adapter deliberately does NOT force ``env={}`` (that would break the
env-substitution corpus cases the driver sets variables for).
"""

from __future__ import annotations

import json
import sys

EXIT_USAGE = 2
EXIT_ERROR = 3


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: hocon-json <conf-file>", file=sys.stderr)
        return EXIT_USAGE
    # Import inside main so even a broken import surfaces as the single-line
    # error record rather than an uncaught module-load traceback (mirrors ts).
    try:
        import hocon

        cfg = hocon.parse_file(argv[1])
        sys.stdout.write(cfg._render_json_for_test() + "\n")
        return 0
    except Exception as exc:  # noqa: BLE001 — adapter must never crash; all errors → record
        record = {"__error__": {"type": type(exc).__name__, "message": str(exc)}}
        sys.stdout.write(json.dumps(record) + "\n")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main(sys.argv))
