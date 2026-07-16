"""E12 deferred-resolution scenario fixtures (dr01-dr30).

Layer-2 YAML scenario runner for the E12 corpus (deferred substitution
resolution — the Lightbend-aligned ``parse / withFallback / resolve()``
lifecycle; see xx.hocon ``docs/extra-spec-conventions.md`` §E12 and the fixture
group README under ``tests/conformance/testdata/hocon/deferred-resolution/``).

Each ``.yaml`` scenario declares input *sources* (``parseString`` with
``resolveSubstitutions: false`` per the runner contract, or ``fromMap``), an
explicit *build* step sequence (``take`` / ``extract`` / ``withFallback`` /
``resolve`` / ``resolveWith``), and an *expect* block (success: expected JSON +
``isResolved`` + getter assertions; error: category / step index / message
substring). Step semantics mirror rs.hocon's
``tests/deferred_resolution_fixtures.rs`` driver: sources build first (build
failures surface at the step that first uses the source), every build step
records its error so ``errorAt`` indexes stay aligned, and the artifact named
by the last step's ``as`` (default ``result``) is validated. Like the rs
driver, ``resolve``/``resolveWith`` default ``useSystemEnvironment`` to False
so ambient environment variables cannot leak into CI runs (every corpus step
sets it explicitly anyway).

Success trees are compared against the Lightbend-generated
``expected/deferred-resolution/<stem>-expected.json`` ground truth when present
(falling back to the in-YAML ``expect.json`` hint), using the same ``_norm``
canonicalization as ``tests/conformance/test_conformance.py`` (local copy —
importing across test modules is avoided).

py.hocon has zero runtime dependencies, so the scenarios are loaded with a
purpose-built mini-YAML reader instead of PyYAML. Supported subset (all the
corpus uses, verified by inspection; anything else raises ``_YamlSubsetError``):

- space-indented block mappings and block sequences (``- item``, one line each)
- full-line ``#`` comments and blank lines (outside block scalars)
- block scalars ``|`` / ``|-`` / ``>`` (folded lines joined with spaces)
- single-line flow collections ``{ k: v, ... }`` / ``[a, b]``, nestable
- double-quoted strings (minimal ``\\``-escape handling) and plain scalars
  typed as int / float / true / false / null / string

Error-category mapping for py.hocon (fixture README §"Error category mapping"):
``ParseError`` → ``hocon.ParseError``; ``ResolveError`` → ``hocon.ResolveError``;
``NotResolved`` → ``hocon.NotResolvedError``; ``TypeError`` → ``ResolveError``
or ``ConfigError`` (py raises concat type errors from the resolver, S10.13);
``CycleError`` → ``ResolveError`` (py has no dedicated cycle class — explicitly
allowed by the dr06/dr18 fixture notes).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

import hocon
from hocon import Config, ConfigError, NotResolvedError, ParseError, ResolveError

_HERE = Path(__file__).parent
_DR_YAML = _HERE / "conformance" / "testdata" / "hocon" / "deferred-resolution"
_DR_EXPECTED = _HERE / "conformance" / "testdata" / "expected" / "deferred-resolution"

pytestmark = pytest.mark.skipif(
    not _DR_YAML.is_dir(),
    reason="deferred-resolution corpus not synced — run `make testdata`",
)


# ─── mini-YAML reader (fixture-controlled subset; see module docstring) ────────


class _YamlSubsetError(ValueError):
    """Scenario file uses YAML outside the supported subset."""


_KEY_RE = re.compile(r"[A-Za-z0-9_.\-]+")
_INT_RE = re.compile(r"-?\d+")
_FLOAT_RE = re.compile(r"-?\d+\.\d+")


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_skippable(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith("#")


def _typed_scalar(tok: str) -> Any:
    if tok == "null":
        return None
    if tok == "true":
        return True
    if tok == "false":
        return False
    if _INT_RE.fullmatch(tok):
        return int(tok)
    if _FLOAT_RE.fullmatch(tok):
        return float(tok)
    return tok


def _skip_spaces(s: str, pos: int) -> int:
    while pos < len(s) and s[pos] == " ":
        pos += 1
    return pos


def _parse_quoted(s: str, pos: int) -> tuple[str, int]:
    # s[pos] == '"'; minimal escape handling (corpus uses none).
    pos += 1
    out: list[str] = []
    while pos < len(s):
        ch = s[pos]
        if ch == "\\" and pos + 1 < len(s):
            out.append(s[pos + 1])
            pos += 2
            continue
        if ch == '"':
            return "".join(out), pos + 1
        out.append(ch)
        pos += 1
    raise _YamlSubsetError(f"unterminated quoted string: {s!r}")


def _parse_flow_value(s: str, pos: int) -> tuple[Any, int]:
    pos = _skip_spaces(s, pos)
    if pos >= len(s):
        raise _YamlSubsetError(f"missing flow value: {s!r}")
    ch = s[pos]
    if ch == "{":
        return _parse_flow_map(s, pos)
    if ch == "[":
        return _parse_flow_list(s, pos)
    if ch == '"':
        return _parse_quoted(s, pos)
    end = pos
    while end < len(s) and s[end] not in ",}]":
        end += 1
    return _typed_scalar(s[pos:end].strip()), end


def _parse_flow_map(s: str, pos: int) -> tuple[dict[str, Any], int]:
    pos = _skip_spaces(s, pos + 1)  # past '{'
    out: dict[str, Any] = {}
    if pos < len(s) and s[pos] == "}":
        return out, pos + 1
    while True:
        pos = _skip_spaces(s, pos)
        colon = s.find(":", pos)
        if colon < 0:
            raise _YamlSubsetError(f"missing ':' in flow mapping: {s!r}")
        key = s[pos:colon].strip()
        if not _KEY_RE.fullmatch(key):
            raise _YamlSubsetError(f"bad flow mapping key {key!r} in {s!r}")
        out[key], pos = _parse_flow_value(s, colon + 1)
        pos = _skip_spaces(s, pos)
        if pos < len(s) and s[pos] == ",":
            pos += 1
            continue
        if pos < len(s) and s[pos] == "}":
            return out, pos + 1
        raise _YamlSubsetError(f"unterminated flow mapping: {s!r}")


def _parse_flow_list(s: str, pos: int) -> tuple[list[Any], int]:
    pos = _skip_spaces(s, pos + 1)  # past '['
    out: list[Any] = []
    if pos < len(s) and s[pos] == "]":
        return out, pos + 1
    while True:
        item, pos = _parse_flow_value(s, pos)
        out.append(item)
        pos = _skip_spaces(s, pos)
        if pos < len(s) and s[pos] == ",":
            pos = _skip_spaces(s, pos + 1)
            continue
        if pos < len(s) and s[pos] == "]":
            return out, pos + 1
        raise _YamlSubsetError(f"unterminated flow list: {s!r}")


def _parse_inline_value(rest: str, lineno: int) -> Any:
    """Value on the same line as its key / dash. Flow collections and quoted
    strings are delimiter-parsed; anything else is one whole plain scalar
    (plain block scalars may contain commas, colons, '#', etc.)."""
    if rest[0] in '{["':
        value, pos = _parse_flow_value(rest, 0)
        if rest[pos:].strip():
            raise _YamlSubsetError(f"trailing content at line {lineno}: {rest[pos:]!r}")
        return value
    return _typed_scalar(rest)


def _parse_block_scalar(
    lines: list[str], i: int, key_indent: int, style: str
) -> tuple[str, int]:
    collected: list[str] = []
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            collected.append("")
            i += 1
            continue
        if _indent_of(line) <= key_indent:
            break
        collected.append(line)
        i += 1
    non_blank = [ln for ln in collected if ln.strip()]
    if not non_blank:
        raise _YamlSubsetError(f"empty block scalar near line {i + 1}")
    base = min(_indent_of(ln) for ln in non_blank)
    body = [ln[base:] if ln.strip() else "" for ln in collected]
    while body and body[-1] == "":
        body.pop()
    if style == ">":
        return " ".join(body) + "\n", i
    if style == "|":
        return "\n".join(body) + "\n", i
    return "\n".join(body), i  # "|-"


def _parse_child(lines: list[str], i: int, parent_indent: int) -> tuple[Any, int]:
    while i < len(lines) and _is_skippable(lines[i]):
        i += 1
    if i >= len(lines) or _indent_of(lines[i]) <= parent_indent:
        raise _YamlSubsetError(f"expected nested block after line {i}")
    child_indent = _indent_of(lines[i])
    if lines[i][child_indent:].startswith("- "):
        return _parse_sequence(lines, i, child_indent)
    return _parse_mapping(lines, i, child_indent)


def _parse_sequence(lines: list[str], i: int, indent: int) -> tuple[list[Any], int]:
    out: list[Any] = []
    while i < len(lines):
        line = lines[i]
        if _is_skippable(line):
            i += 1
            continue
        ind = _indent_of(line)
        if ind < indent:
            break
        content = line[ind:]
        if ind > indent or not content.startswith("- "):
            raise _YamlSubsetError(f"unexpected sequence item at line {i + 1}: {line!r}")
        item = content[2:].strip()
        if not item:
            raise _YamlSubsetError(f"multi-line sequence item at line {i + 1} unsupported")
        out.append(_parse_inline_value(item, i + 1))
        i += 1
    return out, i


def _parse_mapping(lines: list[str], i: int, indent: int) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    while i < len(lines):
        line = lines[i]
        if _is_skippable(line):
            i += 1
            continue
        ind = _indent_of(line)
        if ind < indent:
            break
        content = line[ind:]
        if ind > indent or content.startswith("- "):
            raise _YamlSubsetError(f"unexpected line {i + 1} in mapping: {line!r}")
        key, sep, rest = content.partition(":")
        if not sep or not _KEY_RE.fullmatch(key):
            raise _YamlSubsetError(f"bad mapping entry at line {i + 1}: {line!r}")
        rest = rest.strip()
        i += 1
        if rest == "":
            out[key], i = _parse_child(lines, i, ind)
        elif rest in ("|", "|-", ">"):
            out[key], i = _parse_block_scalar(lines, i, ind, rest)
        else:
            out[key] = _parse_inline_value(rest, i)
    return out, i


def _load_scenario(path: Path) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8").split("\n")
    scenario, i = _parse_mapping(lines, 0, 0)
    while i < len(lines):
        if not _is_skippable(lines[i]):
            raise _YamlSubsetError(f"{path.name}: trailing content at line {i + 1}")
        i += 1
    for required in ("description", "sources", "build", "expect"):
        if required not in scenario:
            raise _YamlSubsetError(f"{path.name}: missing required key {required!r}")
    return scenario


# ─── scenario runner (mirrors rs.hocon tests/deferred_resolution_fixtures.rs) ──


class _HarnessError(Exception):
    """Runner-internal wiring failure — never matches an expected error category."""


def _build_source(spec: dict[str, Any]) -> Config:
    if "parseString" in spec:
        po = spec.get("parseOptions") or {}
        origin = po.get("originDescription") or spec.get("originDescription")
        # Runner contract: default resolveSubstitutions=false unless set true.
        return hocon.parse(
            spec["parseString"],
            resolve_substitutions=bool(po.get("resolveSubstitutions", False)),
            origin_description=origin,
        )
    if "fromMap" in spec:
        return hocon.from_map(spec["fromMap"], spec.get("originDescription"))
    return hocon.empty(spec.get("originDescription"))


def _lookup(
    name: str, artifacts: dict[str, Config], source_errors: dict[str, Exception]
) -> Config:
    if name in artifacts:
        return artifacts[name]
    if name in source_errors:
        raise source_errors[name]
    raise _HarnessError(f"artifact {name!r} not found")


def _execute_step(
    step: dict[str, Any],
    artifacts: dict[str, Config],
    source_errors: dict[str, Exception],
) -> Exception | None:
    op = step.get("op")
    try:
        if op == "take":
            artifacts[step["as"]] = _lookup(step["source"], artifacts, source_errors)
        elif op == "extract":
            this = _lookup(step["this"], artifacts, source_errors)
            artifacts[step["as"]] = this.get_config(step["path"])
        elif op == "withFallback":
            this = _lookup(step["this"], artifacts, source_errors)
            other = _lookup(step["other"], artifacts, source_errors)
            artifacts[step["as"]] = this.with_fallback(other)
        elif op == "resolve":
            this = _lookup(step["this"], artifacts, source_errors)
            artifacts[step["as"]] = this.resolve(
                allow_unresolved=bool(step.get("allowUnresolved", False)),
                use_system_environment=bool(step.get("useSystemEnvironment", False)),
            )
        elif op == "resolveWith":
            this = _lookup(step["this"], artifacts, source_errors)
            source = _lookup(step["source"], artifacts, source_errors)
            artifacts[step["as"]] = this.resolve_with(
                source,
                allow_unresolved=bool(step.get("allowUnresolved", False)),
                use_system_environment=bool(step.get("useSystemEnvironment", False)),
            )
        else:
            raise _HarnessError(f"unknown op {op!r}")
    except Exception as exc:  # noqa: BLE001 — every step error feeds errorAt matching
        return exc
    return None


def _run_scenario(
    scenario: dict[str, Any],
) -> tuple[dict[str, Config], list[Exception | None], str]:
    artifacts: dict[str, Config] = {}
    source_errors: dict[str, Exception] = {}
    for name, spec in scenario["sources"].items():
        try:
            artifacts[name] = _build_source(spec)
        except Exception as exc:  # noqa: BLE001 — surfaced at the step that uses the source
            source_errors[name] = exc
    step_errors: list[Exception | None] = []
    final_name = "result"
    for step in scenario["build"]:
        step_errors.append(_execute_step(step, artifacts, source_errors))
        if step.get("as"):
            final_name = step["as"]
    return artifacts, step_errors, final_name


# ─── expectation validation ────────────────────────────────────────────────────

_CATEGORY_TYPES: dict[str, tuple[type[BaseException], ...]] = {
    "ParseError": (ParseError,),
    "ResolveError": (ResolveError,),
    "NotResolved": (NotResolvedError,),
    "TypeError": (ResolveError, ConfigError),
    "CycleError": (ResolveError,),
}

_GETTER_KEYS = {"path", "expectString", "expectInt", "expectArray", "expectError"}


def _norm(v: Any) -> Any:
    """Canonicalize a JSON value for comparison (local copy of
    tests/conformance/test_conformance.py::_norm — same ecosystem-bench rules:
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


def _assert_getter(stem: str, cfg: Config, g: dict[str, Any]) -> None:
    unknown = set(g) - _GETTER_KEYS
    assert not unknown, f"{stem}: unsupported getter assertion keys {sorted(unknown)}"
    path = g["path"]
    if "expectError" in g:
        assert g["expectError"] == "NotResolved", (
            f"{stem}: unsupported expectError {g['expectError']!r}"
        )
        with pytest.raises(NotResolvedError):
            cfg.get_string(path)
        return
    if "expectString" in g:
        assert cfg.get_string(path) == g["expectString"], f"{stem}: getter {path!r}"
    if "expectInt" in g:
        assert cfg.get_number(path) == g["expectInt"], f"{stem}: getter {path!r}"
    if "expectArray" in g:
        assert cfg.get_list(path) == g["expectArray"], f"{stem}: getter {path!r}"


def _validate_success(
    stem: str,
    expect: dict[str, Any],
    artifacts: dict[str, Config],
    final_name: str,
    step_errors: list[Exception | None],
) -> None:
    for idx, err in enumerate(step_errors):
        assert err is None, f"{stem}: unexpected error at step {idx}: {err!r}"
    assert final_name in artifacts, f"{stem}: final artifact {final_name!r} not built"
    cfg = artifacts[final_name]
    if "isResolved" in expect:
        assert cfg.is_resolved() is expect["isResolved"], (
            f"{stem}: is_resolved() = {cfg.is_resolved()}, want {expect['isResolved']}"
        )
    if cfg.is_resolved():
        expected_file = _DR_EXPECTED / f"{stem}-expected.json"
        raw = (
            expected_file.read_text(encoding="utf-8")
            if expected_file.exists()
            else expect.get("json")
        )
        if raw is not None:
            got = json.loads(cfg._render_json_for_test())
            assert _norm(got) == _norm(json.loads(raw)), f"{stem}: JSON tree mismatch"
    for g in expect.get("getter", []):
        _assert_getter(stem, cfg, g)


def _validate_error(
    stem: str, expect: dict[str, Any], step_errors: list[Exception | None]
) -> None:
    first = next(((i, e) for i, e in enumerate(step_errors) if e is not None), None)
    assert first is not None, (
        f"{stem}: expected {expect.get('errorCategory')} error but all steps succeeded"
    )
    idx, err = first
    assert not isinstance(err, _HarnessError), f"{stem}: harness wiring error: {err}"
    if "errorAt" in expect:
        assert idx == expect["errorAt"], (
            f"{stem}: error at step {idx}, want {expect['errorAt']} (err={err!r})"
        )
    category = expect["errorCategory"]
    assert category in _CATEGORY_TYPES, f"{stem}: unknown errorCategory {category!r}"
    assert isinstance(err, _CATEGORY_TYPES[category]), (
        f"{stem}: expected {category} ({_CATEGORY_TYPES[category]}), "
        f"got {type(err).__name__}: {err}"
    )
    if "errorContains" in expect:
        assert expect["errorContains"] in str(err), (
            f"{stem}: message {str(err)!r} lacks substring {expect['errorContains']!r}"
        )


# ─── test parametrization ──────────────────────────────────────────────────────


def _params() -> list[Any]:
    if not _DR_YAML.is_dir():
        return []
    params: list[Any] = []
    for path in sorted(_DR_YAML.glob("*.yaml")):
        stem = path.stem  # e.g. "dr01-basic-fallback"
        params.append(pytest.param(stem, _load_scenario(path), id=stem))
    return params


_PARAMS = _params()


@pytest.mark.parametrize("stem,scenario", _PARAMS)
def test_scenario(stem: str, scenario: dict[str, Any]) -> None:
    artifacts, step_errors, final_name = _run_scenario(scenario)
    expect = scenario["expect"]
    outcome = expect.get("outcome")
    if outcome == "error":
        _validate_error(stem, expect, step_errors)
    elif outcome == "success":
        _validate_success(stem, expect, artifacts, final_name, step_errors)
    else:
        pytest.fail(f"{stem}: unknown expect.outcome {outcome!r}")


def test_corpus_complete() -> None:
    # Guard against a silently-missing corpus producing a green run.
    assert len(_PARAMS) >= 30, "deferred-resolution corpus looks too small — run `make testdata`"


# ─── programmatic companions the YAML schema cannot express (fixture README) ───


def test_dr19_resolve_idempotent_programmatic() -> None:
    """dr19 README note: ``c.resolve().resolve()`` yields a tree equivalent to
    ``c.resolve()`` (E12 §Idempotency) — not expressible in scenario YAML v1."""
    cfg = hocon.parse("a = ${b}\nb = 7\n", resolve_substitutions=False)
    once = cfg.resolve(use_system_environment=False)
    twice = once.resolve(use_system_environment=False)
    assert once.is_resolved() and twice.is_resolved()
    assert json.loads(once._render_json_for_test()) == json.loads(twice._render_json_for_test())


def test_dr29_empty_config_edges_programmatic() -> None:
    """dr29 README note: edges (a) ``empty().resolve()`` → ``{}`` and
    (b) ``empty().with_fallback(c)`` equivalent to ``c`` — YAML covers only
    ``c.with_fallback(empty())``."""
    assert hocon.empty().resolve(use_system_environment=False)._render_json_for_test() == "{}"
    cfg = hocon.parse("a = 1\n", resolve_substitutions=False)
    merged = hocon.empty().with_fallback(cfg).resolve(use_system_environment=False)
    assert json.loads(merged._render_json_for_test()) == {"a": 1}
