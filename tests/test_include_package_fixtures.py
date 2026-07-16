"""E11 ``include package(...)`` fixtures (include-package/ipk01–ipk14).

Consumes the fixture group that the main corpus runner holds out (no expected
JSON sidecars — scenarios need per-fixture registry setup). Scenario semantics
come from xx.hocon ``docs/extra-spec-conventions.md`` §E11 (decisions 1–8);
the drive mirrors rs.hocon ``tests/include_package_test.rs`` and ts.hocon
``tests/conformance/include-package.test.ts``.

py.hocon — like ts.hocon — has no explicit package registry: ``parse`` /
``parse_file`` accept a ``package_resolver`` hook mapping ``(identifier,
file)`` to a filesystem path. Each case therefore injects an in-memory
registry resolver keyed byte-exactly on ``(identifier, file)`` and pointing at
the real package-content files under ``_packages/``; a miss raises
``PackageLookupError`` (the same class the default resolver raises).

Expected error classes:

- parse-time rejection (one-arg form; decision 2) → ``ParseError`` (ipk02)
- file-argument validation (decision 6) → ``ParseError`` (ipk09–ipk12)
- registry miss, incl. ``required(...)`` and byte-exact case (decisions 4, 5,
  7) → ``PackageLookupError`` (ipk04–ipk07)
- include cycles (decision 8) → ``ResolveError`` with ``circular include``
  (ipk13, ipk14)

Per-impl override: ipk03 (registration-time collision, decision 3) is N/A —
py.hocon has no registration API to collide on, matching the documented
ts.hocon exemption (xx.hocon §E11 fixture list).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import hocon
from hocon import PackageLookupError, ParseError, ResolveError

_FIXTURE_DIR = Path(__file__).parent / "conformance" / "testdata" / "hocon" / "include-package"
_PACKAGES_DIR = _FIXTURE_DIR / "_packages"

pytestmark = pytest.mark.skipif(
    not _FIXTURE_DIR.is_dir() or not _PACKAGES_DIR.is_dir(),
    reason="include-package corpus not synced — run `make testdata`",
)

# (identifier, file) -> package-content path relative to _packages/
_Registry = dict[tuple[str, str], str]
_PackageResolver = Callable[[str, str, "str | None", "str | None"], str]


def _norm(v: Any) -> Any:
    """Canonicalize a JSON value for comparison (local copy of the corpus
    runner's normalization: key order ignored, numbers by value, null keys
    dropped)."""
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


def _make_resolver(registry: _Registry) -> _PackageResolver:
    """Byte-exact in-memory registry resolver (E11 decision 5). Returns the
    real fixture path under ``_packages/``; content is read by the loader."""

    def resolver(
        identifier: str, file: str, including_file: str | None, base_dir: str | None
    ) -> str:
        rel = registry.get((identifier, file))
        if rel is None:
            raise PackageLookupError(
                f'include package("{identifier}", "{file}"): not found in test registry',
                identifier,
                file,
                0,
                0,
            )
        path = _PACKAGES_DIR / rel
        assert path.is_file(), f"registered package content missing from corpus: {path}"
        return str(path)

    return resolver


@dataclass(frozen=True)
class _Case:
    fixture: str
    registry: _Registry = field(default_factory=dict)
    error: type[Exception] | None = None
    message_substr: str | None = None
    expected: dict[str, Any] | None = None
    skip_reason: str | None = None


_CASES: list[_Case] = [
    # decision 1/4 happy path: registered package merges into the document.
    _Case(
        fixture="ipk01-basic",
        registry={
            ("github.com/example/lib", "reference.conf"): (
                "github.com_example_lib/reference.conf"
            ),
        },
        expected={"host": "example.com", "port": 8080, "app": {"name": "lib"}},
    ),
    # decision 2: one-arg form is rejected at parse time.
    _Case(
        fixture="ipk02-one-arg-rejected",
        error=ParseError,
        message_substr="requires exactly two arguments",
    ),
    # decision 3: registration-time collision — N/A for py.hocon (no registry).
    _Case(
        fixture="ipk03-collision",
        skip_reason=(
            "N/A for py.hocon: no explicit registry / registration API to collide on "
            "(per-impl override, same exemption as ts.hocon — xx.hocon §E11 decision 3)"
        ),
    ),
    # decision 4: empty registry -> lookup miss.
    _Case(fixture="ipk04-lookup-miss", error=PackageLookupError),
    # decision 7: required(package(...)) with a miss always errors.
    _Case(fixture="ipk05-required-miss", error=PackageLookupError),
    # decision 5: identifier compared byte-exactly ("foo/bar" != "Foo/Bar").
    _Case(
        fixture="ipk06-byte-exact-id-case",
        registry={("Foo/Bar", "x.conf"): "github.com_example_lib_byte/Foo_Bar_x.conf"},
        error=PackageLookupError,
    ),
    # decision 5: file compared byte-exactly ("reference.conf" != "Reference.conf").
    _Case(
        fixture="ipk07-byte-exact-file-case",
        registry={
            ("github.com/example/lib", "Reference.conf"): (
                "github.com_example_lib_byte/github.com_example_lib_Reference.conf"
            ),
        },
        error=PackageLookupError,
    ),
    # decision 4 note: empty registered content is NOT a miss; contributes {}.
    _Case(
        fixture="ipk08-empty-content",
        registry={
            ("github.com/example/lib", "empty.conf"): "github.com_example_lib_empty/empty.conf",
        },
        expected={"app": "host"},
    ),
    # decision 6: file argument must be non-empty.
    _Case(fixture="ipk09-file-empty", error=ParseError, message_substr="must be non-empty"),
    # decision 6: no absolute paths in the file argument.
    _Case(
        fixture="ipk10-file-absolute",
        error=ParseError,
        message_substr="absolute path not allowed",
    ),
    # decision 6: no . / .. traversal segments in the file argument.
    _Case(
        fixture="ipk11-file-traversal",
        error=ParseError,
        message_substr="path traversal",
    ),
    # decision 6: no backslashes (validated after HOCON unescape).
    _Case(
        fixture="ipk12-file-backslash",
        error=ParseError,
        message_substr="backslash not allowed",
    ),
    # decision 8: self-include cycle detected via ("package", id, file) key.
    _Case(
        fixture="ipk13-cycle-self",
        registry={("foo", "self.conf"): "_cycle/ipk13-self.conf"},
        error=ResolveError,
        message_substr="circular include",
    ),
    # decision 8: mutual cycle a.conf <-> b.conf.
    _Case(
        fixture="ipk14-cycle-mutual",
        registry={
            ("foo", "a.conf"): "_cycle/ipk14-a.conf",
            ("foo", "b.conf"): "_cycle/ipk14-b.conf",
        },
        error=ResolveError,
        message_substr="circular include",
    ),
]


def _params() -> list[Any]:
    params: list[Any] = []
    for case in _CASES:
        marks = [pytest.mark.skip(reason=case.skip_reason)] if case.skip_reason else []
        params.append(pytest.param(case, id=case.fixture, marks=marks))
    return params


@pytest.mark.parametrize("case", _params())
def test_include_package_fixture(case: _Case) -> None:
    conf = _FIXTURE_DIR / f"{case.fixture}.conf"
    assert conf.is_file(), f"fixture missing from corpus: {conf}"
    resolver = _make_resolver(case.registry)

    if case.error is not None:
        with pytest.raises(case.error) as excinfo:
            hocon.parse_file(str(conf), env={}, package_resolver=resolver)
        if case.message_substr is not None:
            assert case.message_substr in str(excinfo.value), (
                f"{case.fixture}: expected error message containing "
                f"{case.message_substr!r}, got: {excinfo.value}"
            )
        return

    cfg = hocon.parse_file(str(conf), env={}, package_resolver=resolver)
    got = json.loads(cfg._render_json_for_test())
    assert _norm(got) == _norm(case.expected), (
        f"{case.fixture}: output mismatch\n"
        f"  got:      {json.dumps(got, sort_keys=True)}\n"
        f"  expected: {json.dumps(case.expected, sort_keys=True)}"
    )


def test_group_complete() -> None:
    """Guard: the case table and the on-disk fixture group must agree exactly
    (top-level ``ipk*.conf`` only; ``_packages/`` holds content, not fixtures)."""
    on_disk = {p.stem for p in _FIXTURE_DIR.glob("ipk*.conf")}
    in_table = {case.fixture for case in _CASES}
    assert on_disk == in_table, (
        f"fixture drift — on disk only: {sorted(on_disk - in_table)}; "
        f"in table only: {sorted(in_table - on_disk)}"
    )
