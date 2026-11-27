"""xx.hocon error-fixture conformance harness.

Discovers every fixture the canonical corpus marks as *must error* (synced by
``make testdata``) and asserts py.hocon rejects it. xx.hocon marks error
fixtures two ways (see xx.hocon ``docs/fixture-conventions.md``):

- **legacy JSON sidecar** — ``testdata/expected/<base>-expected-error.json``
  (``cycle.conf`` circular include, ``test13-reference-bad-substitutions``
  S13.10, ``subst-tokenize/st-err01–11`` S1.2.2–S1.2.5 / S11.7 / S13.19);
- **plain-text ``.error`` sidecar** — ``testdata/expected/<group>/<name>.error``
  (``SIDECAR_ERROR_CONFS`` / ``ENV_VAR_LIST_ERROR_CONFS``): concat-errors
  S10.4 / S10.13 / S10.19, include-reservation S12.5, self-ref-lookback sr05
  S13a.3, env-var-list ev03 S13c.3 / ev12a S13c.5, path-expr-whitespace pw06
  S11.7 (trailing dot), unquoted-starts us15 S8.6/E8.

Three fixtures carry NO sidecar because Lightbend silently accepts them, yet
the o3co strict-spec posture requires rejection; each sibling pins them via a
per-impl override list (``IMPL_OVERRIDE_ERRORS`` in ts, ``KNOWN_LIGHTBEND_QUIRKS``
in rs) and this harness mirrors that with ``_IMPL_OVERRIDE_ERRORS``:
ce05-object-plus-scalar (E5, S10.13) and ir03/ir04 (E9, S12.5).

Error-class strictness mirrors ts.hocon's per-family pinning (rs.hocon has a
single error type and asserts bare failure): concat-errors / env-var-list /
self-ref-lookback pin ``ResolveError``; include-reservation pins ``ParseError``;
every other family accepts any of ``(ParseError, ResolveError, ConfigError)``,
matching the siblings' bare ``toThrow()`` / ``is_err()`` posture.

Held out of this harness:

- **deferred-resolution dr*** — ``<name>-expected.error`` sidecars belong to the
  E12 scenario-YAML lifecycle (parse-with-options → withFallback → resolve);
  they are not single-``.conf`` fixtures and cannot be driven by ``parse_file``.

us15-incomplete-exp (``a = 1e+x``) was a strict-xfail known gap until the lexer
reserved ``+`` inside unquoted runs (E8 step 4 / S8.1); it is now an ordinary
error fixture.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import hocon
from hocon import ConfigError, ParseError, ResolveError

_HERE = Path(__file__).parent
_TESTDATA = _HERE / "testdata"
_EXPECTED = _TESTDATA / "expected"
_CONF = _TESTDATA / "hocon"

pytestmark = pytest.mark.skipif(
    not _EXPECTED.is_dir() or not _CONF.is_dir(),
    reason="conformance corpus not synced — run `make testdata`",
)

_ANY_ERROR: tuple[type[Exception], ...] = (ParseError, ResolveError, ConfigError)

# Per-family expected error class, keyed by the fixture group directory.
# Families absent from this map assert the broad _ANY_ERROR tuple (siblings
# assert bare failure there). Mirrors ts.hocon: concat-errors.test.ts /
# env-var-list.test.ts / s13a13-self-ref-lookback.test.ts pin ResolveError;
# include-reservation.test.ts pins ParseError.
_FAMILY_ERROR: dict[str, tuple[type[Exception], ...]] = {
    # S3.5/S14b.1: ar01/ar02 are top-level array roots (ConfigError at the
    # Config boundary); ar03 is the include variant (ResolveError naming the
    # included file). Never a ParseError — the documents are valid syntax.
    "array-root": (ConfigError, ResolveError),
    "concat-errors": (ResolveError,),
    "env-var-list": (ResolveError,),
    "include-reservation": (ParseError,),
    # S1.2.4: a raw control in a quoted string must fail in the lexer, not
    # later (qc07's key exists, so only the lexer can reject it).
    "quoted-control": (ParseError,),
    "self-ref-lookback": (ResolveError,),
}

# E5 / E9 Lightbend-silent-accept quirks: no sidecar on disk, rejection is
# still normative (xx.hocon docs/fixture-conventions.md §Lightbend quirks).
_IMPL_OVERRIDE_ERRORS = (
    "concat-errors/ce05-object-plus-scalar",  # E5 — `a = { b: 1 } x` (S10.13)
    "include-reservation/ir03-include-dot-foo-equals",  # E9 — `include.foo = 1` (S12.5)
    "include-reservation/ir04-include-nested-object",  # E9 — `a = { include.bar = 1 }` (S12.5)
)

# Known gaps: the sidecar demands an error, but py.hocon accepts the input.
# Each is a strict xfail, so an XPASS (the gap closed) fails the run for
# triage; an entry whose fixture is not on disk has no effect. (us15 closed by
# the E8 `+` reservation.)
_XX123 = (
    "o3co/xx.hocon#123: a required substitution of a field removed by an "
    "undefined optional is silently dropped instead of raising (S13.10)"
)
_XX115 = (
    "o3co/xx.hocon#115: the including file's a = ${missing} under an included "
    "object is not live (E16), so the unresolved required reference is not seen"
)
_KNOWN_GAPS: dict[str, str] = {
    "include-optional-prior/io19-live-prior-required-missing": _XX115,
    **{
        f"subst-removed-target/{name}": _XX123
        for name in (
            "rq01-required-to-removed-field",
            "rq02-forward-ref",
            "rq03-both-optionals-undefined",
            "rq04-array-element",
            "rq05-string-concat",
            "rq06-object-concat",
            "rq07-array-concat",
            "rq08-nested-path",
            "rq09-optional-cycle",
            "rq10-optional-self-ref",
            "rq11-optional-closes-cycle",
            "rq12-include-fixed-up-path",
            "rq13-include-both-paths-removed",
            "rq14-include-original-path-removed",
            "rq15-merged-not-hidden",
            "rq16-kept-prior-is-required-ref",
            "rq29-include-fixed-up-removed-original-set",
        )
    },
    # a.n = ${?a} closes a cycle over a prior object: py invents o from it.
    "subst-removed-target/rq40-optional-closes-cycle-over-prior-object-window": (
        "o3co/xx.hocon#123 (moved into the #67 window): an optional cycle over a "
        "prior object is not removed, so the required ${a.n} resolves to an "
        "invented value instead of raising"
    ),
}

# On-disk error-fixture census at the time of writing (guard floor):
#   13 legacy -expected-error.json  (cycle, test13, st-err01–11)
# + 22 .error sidecars             (ce×12, ev×2, ir×5, pw×1, sr×1, us×1)
# +  3 per-impl overrides          (ce05, ir03, ir04)
# quoted-control qc01–qc08 (xx.hocon#130) add 8 more once xx main carries
# them; the floor stays at the pre-#130 census so CI keeps passing until then.
_ERROR_FIXTURE_FLOOR = 38


def _discover() -> list[str]:
    """Return sorted fixture bases (posix-relative, no extension) that must error."""
    bases: set[str] = set()
    if not _EXPECTED.is_dir():
        return []
    for root, _dirs, files in os.walk(_EXPECTED):
        for f in files:
            rel = Path(root, f).relative_to(_EXPECTED).as_posix()
            if rel.startswith("deferred-resolution/"):
                continue  # E12 scenario YAMLs — see module docstring.
            if f.endswith("-expected-error.json"):
                bases.add(rel[: -len("-expected-error.json")])
            elif f.endswith(".error") and not f.endswith("-expected.error"):
                # `-expected.error` is the E12 scenario naming — excluded above,
                # filtered again here so a future group reusing it stays out.
                bases.add(rel[: -len(".error")])
    for base in _IMPL_OVERRIDE_ERRORS:
        bases.add(base)
    return sorted(base for base in bases if (_CONF / (base + ".conf")).exists())


def _load_env_sidecar(conf: Path) -> dict[str, str]:
    """Env for a fixture = its ``.env`` sidecar only (ambient os.environ is NOT
    included, keeping the run deterministic). Same convention as
    ``test_conformance.py``."""
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
    for base in _discover():
        conf = _CONF / (base + ".conf")
        family = base.rsplit("/", 1)[0] if "/" in base else ""
        excs = _FAMILY_ERROR.get(family, _ANY_ERROR)
        marks = []
        if base in _KNOWN_GAPS:
            # Only "DID NOT RAISE" is the known gap: any other exception (an
            # error of the wrong class, a crash) still fails the run.
            marks.append(
                pytest.mark.xfail(
                    strict=True, raises=pytest.fail.Exception, reason=_KNOWN_GAPS[base]
                )
            )
        params.append(pytest.param(base, conf, excs, id=base, marks=marks))
    return params


_PARAMS = _params()


@pytest.mark.parametrize("base,conf,excs", _PARAMS)
def test_error_fixture(base: str, conf: Path, excs: tuple[type[Exception], ...]) -> None:
    env = _load_env_sidecar(conf)
    with pytest.raises(excs):
        hocon.parse_file(str(conf), env=env)


def test_error_corpus_non_empty() -> None:
    # Guard against a silently-missing corpus (or a sync regression dropping
    # sidecars) producing a green run.
    assert len(_PARAMS) >= _ERROR_FIXTURE_FLOOR, (
        f"error-fixture corpus looks too small ({len(_PARAMS)} < {_ERROR_FIXTURE_FLOOR}) — "
        "run `make testdata`"
    )
