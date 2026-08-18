"""Conformance against the shared format-ingestion fixtures from xx.hocon.

These expectations are not oracle-generated — Lightbend has no equivalent of
these adapters — so they encode the project's own F-item decisions. Their value
is cross-implementation: all four must agree with them, and with each other.
See ``tests/conformance/testdata/format-ingestion/manifest.json``.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from hocon.adapters import AdapterError, env, json5, jsonc, properties, toml, yaml
from hocon.config import Config

_ROOT = Path(__file__).parent / "conformance" / "testdata" / "format-ingestion"
_MANIFEST = _ROOT / "manifest.json"

pytestmark = pytest.mark.skipif(
    not _MANIFEST.is_file(),
    reason="format-ingestion corpus not synced — run `make testdata`",
)


def _cases() -> list[dict[str, Any]]:
    if not _MANIFEST.is_file():
        return []
    cases: list[dict[str, Any]] = json.loads(_MANIFEST.read_text(encoding="utf-8"))["cases"]
    return cases


_HAS_RUAMEL = importlib.util.find_spec("ruamel.yaml") is not None


def _ingest(case: dict[str, Any]) -> Config:
    # read_text applies universal-newline translation, which rewrites a lone CR to
    # LF before the adapter sees it — fi24 would then pass without exercising
    # anything. Decode explicitly instead.
    text = (_ROOT / case["input"]).read_bytes().decode("utf-8")
    fmt = case["format"]
    origin = case["id"]
    if fmt == "jsonc":
        return jsonc.parse(text, origin)
    if fmt == "json5":
        return json5.parse(text, origin)
    if fmt == "properties":
        return properties.parse(text, origin)
    if fmt == "toml":
        return toml.parse(text, origin)
    if fmt == "yaml":
        return yaml.parse(text, origin)
    if fmt == "env":
        if case.get("kind") == "dotenv":
            # `prefix` is optional and only dotenv cases carry it; an env-vars
            # input names its own prefix inside the JSON document.
            return env.parse_dotenv(
                text, case.get("prefix", ""), origin_description=origin
            )
        fixture = json.loads(text)
        return env.load(fixture["prefix"], fixture["vars"], origin_description=origin)
    raise AssertionError(f"unknown format {fmt}")


_CASES = _cases()


def test_manifest_is_not_empty() -> None:
    assert _CASES, "manifest lists no cases"


@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_format_ingestion_fixture(case: dict[str, Any]) -> None:
    if case["format"] == "yaml" and not _HAS_RUAMEL:
        pytest.skip("needs `pip install hocon-parser[yaml]`")
    if case["expect"] == "error":
        with pytest.raises(AdapterError) as excinfo:
            _ingest(case)
        cites = case.get("cites")
        if cites:
            assert cites in str(excinfo.value), f"{case['id']}: {excinfo.value}"
        return

    cfg = _ingest(case)
    got = json.loads(cfg._render_json_for_test())
    expected = json.loads((_ROOT / case["expected"]).read_text(encoding="utf-8"))
    assert got == expected, f"{case['id']} mismatch ({case['note']})"
