"""§10.3 limits after a cycle break (xx.hocon resolution-model, E24).

The shapes are those of xx.hocon ``generate/reference-model/limit_probes.py``
that run quickly; each must have the same outcome as in the reference model.
The ``o3co-limit`` fixtures (rv140, rv142, rv147) are asserted here to fail
with ``ResolutionLimitError`` itself, as the runner contract asks; the
conformance harness only checks that they error.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

import hocon
from hocon import ResolutionLimitError, ResolveError


def _dense(k: int) -> str:  # k keys, each reading all k, written twice
    refs = "".join(f"${{?k{j}}}" for j in range(1, k + 1))
    return "".join(f"k{i} = {refs}\n" for i in range(1, k + 1)) * 2


def _ring(n: int, body: str) -> str:  # a_i = body(a_(i+1)), written twice
    return "".join(f"a{i} = " + body.replace("%", str((i + 1) % n)) + "\n" for i in range(n)) * 2


def _wide(w: int) -> str:  # a two-key cycle, each value reading the other key w times
    return ("a = " + "${?b}" * w + "\nb = " + "${?a}" * w + "\n") * 2


def _cyclic_chain(n: int) -> str:  # output weight n^2 / 2, inside one region
    links = "".join(f"c{i} = {{ v = ${{?c{i - 1}}} }}\n" for i in range(1, n + 1))
    return f"c0 = ${{?c{n}}}\n" + links


_SHAPES: list[tuple[str, Callable[[], str], str]] = [
    ("dense4", lambda: _dense(4), "loads"),
    ("dense5", lambda: _dense(5), "limit"),
    ("wide8", lambda: _wide(8), "loads"),
    ("ring_str16", lambda: _ring(16, "${?a%}${?a%}x"), "limit"),
    ("ring_arr16", lambda: _ring(16, "[${?a%}, ${?a%}]"), "loads"),
    ("ring_obj16", lambda: _ring(16, "{ x = ${?a%}, y = ${?a%} }"), "limit"),
    # The probe table has n = 500 and 2,000, which load once the interpreter's
    # recursion limit is raised (as the probe runners do): at the default
    # limit py stops this shape near n = 200 with its nesting ParseError, a
    # bound older than §10.3. The test stays below it.
    ("cyclic_chain_n150", lambda: _cyclic_chain(150), "loads"),
]


@pytest.mark.parametrize(("name", "build", "want"), _SHAPES, ids=[s[0] for s in _SHAPES])
def test_limit_probe_outcome(name: str, build: Callable[[], str], want: str) -> None:
    try:
        hocon.parse(build(), env={}).to_object()
        got = "loads"
    except ResolutionLimitError as e:
        assert str(e).startswith("resolution limit exceeded after a cycle break: ")
        got = "limit"
    assert got == want


def test_self_reentry_and_env_overrides_do_not_arm() -> None:
    # `x = ${?x}` meets only itself and `${?PORT}` is an ordinary look-back:
    # neither opens a region, so a large acyclic doubling read after them is
    # uncharged and loads, though it builds far more than B for this document.
    s = 'x = ${?x}\nport = 8080\nport = ${?PORT}\ns = "' + "x" * 100 + '"\n'
    s += "s = ${s}${s}\n" * 14  # about 410,000 units, above B for this document
    assert hocon.parse(s, env={}).get_int("port") == 8080


def test_limit_error_is_a_resolve_error_no_optional_catches() -> None:
    assert issubclass(ResolutionLimitError, ResolveError)
    # The runaway sits under an optional reference: it still aborts.
    with pytest.raises(ResolutionLimitError):
        hocon.parse("r = ${?k1}\n" + _dense(5), env={})


_FIXTURES = Path(__file__).parent / "conformance" / "testdata" / "hocon" / "resolution-model"


@pytest.mark.parametrize(
    "name",
    [
        "rv140-limit-dense5",
        "rv142-limit-budget-40-values",
        "rv147-limit-budget-61-values-edge-cases",
    ],
)
def test_o3co_limit_fixture_fails_with_the_limit(name: str) -> None:
    conf = _FIXTURES / f"{name}.conf"
    if not conf.exists():
        pytest.skip("fixture not in the synced corpus yet (xx.hocon#143)")
    with pytest.raises(ResolutionLimitError):
        hocon.parse_file(str(conf), env={})


# --- arming and region, in py's own suite (rv143–rv145 inline) ---
# Each reads a 405,531-unit string chain from a document of about 35 values
# (B about 350,000): any extra arming, or a region that lasts too long, fails.

_CHAIN = 's = "' + "x" * 99 + '"\n' + "s = ${s}${s}\n" * 14 + "s = {}\n"


def test_self_reentry_inside_the_frame_does_not_arm() -> None:
    # rv143: ${?z} meets only itself; the chain is read inside ${z}'s frame.
    got = hocon.parse("y = ${z}\nz = [${?z}, ${s}]\n" + _CHAIN, env={}).to_object()
    assert got == {"s": {}, "y": [{}], "z": [{}]}


def test_own_path_exception_does_not_arm() -> None:
    # rv144: ${?z} in z's bottom entry reaches EMPTY on its own path (§4.4).
    got = hocon.parse("y = ${z}\nz = ${?z} [${s}]\nz = {}\n" + _CHAIN, env={}).to_object()
    assert got == {"s": {}, "y": {}, "z": {}}


def test_region_ends_with_the_outermost_frame() -> None:
    # rv145: the r/t break's region ends with ${?t}; u reads the chain after.
    got = hocon.parse("r = ${?t}\nt = [${?r}]\nu = [${s}]\n" + _CHAIN, env={}).to_object()
    assert got == {"r": [], "s": {}, "t": [], "u": [{}]}


def test_region_charges_the_chain_when_armed() -> None:
    # The control: the same chain read inside the r/t region (rv142's shape)
    # is charged and fails.
    with pytest.raises(ResolutionLimitError, match="weight units"):
        hocon.parse("r = ${?t}\nt = [${?r}, ${s}]\n" + _CHAIN, env={})


def test_escaped_surrogates_are_weighed_without_error() -> None:
    # A JSON-escaped emoji is kept as a surrogate pair; weighing it inside a
    # region must not raise UnicodeEncodeError.
    src = 'r = ${?t}\nt = [${?r}, ${s}]\ns = "\\ud83d\\ude00"\nl = "\\ud800"\nq = [${?r}, ${l}]\n'
    assert hocon.parse(src, env={}).to_object()["t"] == ["\ud83d\ude00"]
