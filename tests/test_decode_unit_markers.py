"""Unit markers in typed decoding (o3co/xx.hocon#102).

``Annotated[int, hocon.Bytes()]`` / ``Annotated[float, hocon.Duration("s")]``
read HOCON unit values with the getters' rules, in both decode paths
(dataclasses and Pydantic v2). The parity tables run every input through the
getter and both decode paths and require the same outcome.

No ``from __future__ import annotations`` here: several models are defined
inside a test and annotate with a local (``Bytes(unit)``), which a deferred
string annotation could not resolve.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, Any

import pydantic
import pytest

import hocon
from hocon import Bytes, ConfigError, Duration, parse_string

# --- parity: getter == dataclass decode == Pydantic decode -------------------

_BYTES_CASES = [
    ("64KiB", "B"),
    ("64KiB", "KiB"),
    ("1kB", "B"),
    ("512MiB", "MiB"),
    ("1.5K", "B"),
    ("0.5KiB", "B"),
    ("10", "B"),
    ("10.9", "B"),  # a bare number truncates
    ("512B", "KiB"),  # fractional in the requested unit
    ("1 b", "B"),
    ("1KB", "B"),  # case-sensitive: invalid
    ("64 kb", "B"),
    ("-1k", "B"),  # negative
    ("10PB", "B"),  # overflow
    ("lots", "B"),
]


def _outcome(fn: Any) -> Any:
    try:
        return ("ok", fn())
    except (ConfigError, pydantic.ValidationError) as e:
        return ("error", type(e).__name__)


@pytest.mark.parametrize(("text", "unit"), _BYTES_CASES)
def test_bytes_parity_with_get_bytes(text: str, unit: str) -> None:
    cfg = parse_string(f'v = "{text}"')

    @dataclass
    class D:
        v: Annotated[float, Bytes(unit)]

    class P(pydantic.BaseModel):
        v: Annotated[float, Bytes(unit)]

    getter = _outcome(lambda: cfg.get_bytes("v", unit))
    via_dataclass = _outcome(lambda: cfg.decode(D).v)
    via_pydantic = _outcome(lambda: cfg.decode(P).v)
    assert getter[0] == via_dataclass[0] == via_pydantic[0]
    if getter[0] == "ok":
        assert getter[1] == via_dataclass[1] == via_pydantic[1]


_DURATION_CASES = [
    ("30m", "ms"),
    ("30m", "s"),
    ("1.5h", "m"),
    ("250", "ms"),  # a bare number is ms
    ("250", "s"),
    ("10 seconds", "s"),
    ("-5s", "ms"),  # durations may be negative
    ("1 S", "ms"),  # case-sensitive: invalid
    ("5 parsecs", "ms"),
]


@pytest.mark.parametrize(("text", "unit"), _DURATION_CASES)
def test_duration_parity_with_get_duration(text: str, unit: str) -> None:
    cfg = parse_string(f'v = "{text}"')

    @dataclass
    class D:
        v: Annotated[float, Duration(unit)]

    class P(pydantic.BaseModel):
        v: Annotated[float, Duration(unit)]

    getter = _outcome(lambda: cfg.get_duration("v", unit))
    via_dataclass = _outcome(lambda: cfg.decode(D).v)
    via_pydantic = _outcome(lambda: cfg.decode(P).v)
    assert getter[0] == via_dataclass[0] == via_pydantic[0]
    if getter[0] == "ok":
        assert getter[1] == pytest.approx(via_dataclass[1]) == pytest.approx(via_pydantic[1])


def test_unquoted_number_reads_like_the_getter() -> None:
    cfg = parse_string("b = 65536, d = 1500")

    @dataclass
    class D:
        b: Annotated[int, Bytes()]
        d: Annotated[float, Duration("s")]

    class P(pydantic.BaseModel):
        b: Annotated[int, Bytes()]
        d: Annotated[float, Duration("s")]

    assert cfg.decode(D) == D(b=cfg.get_bytes("b"), d=cfg.get_duration("d", "s"))
    assert cfg.decode(P) == P(b=65536, d=1.5)


# --- dataclass path ----------------------------------------------------------


@dataclass
class Server:
    max_body: Annotated[int, Bytes()]
    cache: Annotated[float, Bytes("MiB")]
    timeout: Annotated[timedelta, Duration()]
    retry_ms: Annotated[int, Duration()]


def test_dataclass_reads_markers() -> None:
    cfg = parse_string("max-body = 64KiB, cache = 512KiB, timeout = 30m, retry-ms = 2s")
    assert cfg.decode(Server) == Server(
        max_body=65536, cache=0.5, timeout=timedelta(minutes=30), retry_ms=2000
    )
    assert isinstance(cfg.decode(Server).max_body, int)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('"64KB"', r"invalid byte size at server\.max-body: '64KB'"),
        ('"-1k"', r"byte size must be non-negative at server\.max-body: '-1k'"),
        ("10PB", r"byte size overflows .* at server\.max-body: '10PB'"),
        ("true", r"expected byte size at server\.max-body, got boolean"),
        ("[1]", r"expected scalar .* at server\.max-body, got array"),
    ],
)
def test_dataclass_errors_carry_the_path(text: str, message: str) -> None:
    @dataclass
    class C:
        server: Server

    cfg = parse_string(
        f"server {{ max-body = {text}, cache = 1MiB, timeout = 1s, retry-ms = 1 }}"
    )
    with pytest.raises(ConfigError, match=message) as e:
        cfg.decode(C)
    assert e.value.path == "server.max-body"


@pytest.mark.parametrize(
    ("text", "marker", "expected"),
    [
        ("1.001s", Duration(), 1001),
        ("0.3s", Duration(), 300),
        ("1.1MB", Bytes("KB"), 1100),
        ("1.1MB", Bytes(), 1_100_000),
    ],
)
def test_int_target_accepts_a_decimally_exact_result(
    text: str, marker: Any, expected: int
) -> None:
    # Unit conversion is exact in decimal: 1.001s is 1001 ms, not
    # 1000.9999999999999, in the getter and in both decode paths.
    @dataclass
    class D:
        v: Annotated[int, marker]

    class P(pydantic.BaseModel):
        v: Annotated[int, marker]

    cfg = parse_string(f'v = "{text}"')
    getter = (
        cfg.get_duration("v", marker.unit)
        if isinstance(marker, Duration)
        else cfg.get_bytes("v", marker.unit)
    )
    assert getter == expected
    assert cfg.decode(D).v == expected
    assert cfg.decode(P).v == expected


def test_int_target_rejects_a_fractional_result() -> None:
    @dataclass
    class C:
        v: Annotated[int, Bytes("KiB")]

    with pytest.raises(ConfigError, match=r"expected int at v, got 0\.5 from '512B'"):
        parse_string("v = 512B").decode(C)
    assert parse_string("v = 2048B").decode(C) == C(v=2)


def test_optional_and_containers() -> None:
    @dataclass
    class C:
        a: Annotated[int, Bytes()] | None
        b: Annotated[int | None, Bytes()]
        sizes: list[Annotated[int, Bytes()]]
        limits: dict[str, Annotated[int, Bytes("KiB")]]
        c: Annotated[int, Bytes()] | None = None

    cfg = parse_string("a = null, b = null, sizes = [1k, 2k], limits { x = 4MiB }")
    assert cfg.decode(C) == C(a=None, b=None, sizes=[1024, 2048], limits={"x": 4096})
    assert parse_string("v = 1k").decode(Annotated[int, Bytes()], path="v") == 1024


def test_null_into_a_non_optional_marked_field_errors() -> None:
    @dataclass
    class C:
        v: Annotated[int, Bytes()]

    with pytest.raises(ConfigError, match="null cannot decode into int at v"):
        parse_string("v = null").decode(C)


def test_annotated_without_a_marker_decodes_the_base_type() -> None:
    @dataclass
    class C:
        v: Annotated[int, "some other metadata"]

    assert parse_string("v = 3").decode(C) == C(v=3)
    with pytest.raises(ConfigError, match="expected int at v"):
        parse_string("v = 3KiB").decode(C)


def test_unsupported_marker_target_errors() -> None:
    @dataclass
    class C:
        v: Annotated[str, Bytes()]

    with pytest.raises(ConfigError, match=r"decodes into int / float, not <class 'str'> at v"):
        parse_string("v = 1k").decode(C)


def test_two_markers_error() -> None:
    @dataclass
    class C:
        v: Annotated[int, Bytes(), Duration()]

    with pytest.raises(ConfigError, match="more than one unit marker"):
        parse_string("v = 1").decode(C)


def test_unknown_unit_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="unknown byte unit 'kb'"):
        Bytes("kb")
    with pytest.raises(ValueError, match="unknown duration unit 'sec'"):
        Duration("sec")


def test_exported_from_the_package() -> None:
    assert hocon.Bytes is Bytes
    assert hocon.Duration is Duration
    assert Bytes() == Bytes("B")
    assert hash(Duration("s")) == hash(Duration("s"))


# --- Pydantic path -----------------------------------------------------------


class Limits(pydantic.BaseModel):
    max_body: Annotated[int, Bytes(), pydantic.Field(gt=1024)]
    timeout: Annotated[timedelta, Duration()]
    ttl_s: Annotated[float, Duration("s")]
    sizes: list[Annotated[int, Bytes()]] = []
    spare: Annotated[int | None, Bytes()] = None


def test_pydantic_reads_markers() -> None:
    cfg = parse_string("max_body = 64KiB, timeout = 30m, ttl_s = 1.5m, sizes = [1k, 2k]")
    got = cfg.decode(Limits)
    assert got.model_dump() == {
        "max_body": 65536,
        "timeout": timedelta(minutes=30),
        "ttl_s": 90.0,
        "sizes": [1024, 2048],
        "spare": None,
    }


def test_pydantic_errors_carry_the_location() -> None:
    cfg = parse_string("max_body = 64KB, timeout = 1s, ttl_s = 1, sizes = [1k, -2k]")
    with pytest.raises(pydantic.ValidationError) as e:
        cfg.decode(Limits)
    errors = {err["loc"]: err["msg"] for err in e.value.errors()}
    assert errors == {
        ("max_body",): "Value error, invalid byte size: '64KB'",
        ("sizes", 1): "Value error, byte size must be non-negative: '-2k'",
    }


def test_pydantic_constraints_stay_in_the_schema() -> None:
    with pytest.raises(pydantic.ValidationError, match="greater than 1024"):
        parse_string("max_body = 1k, timeout = 1s, ttl_s = 1").decode(Limits)

    class P(pydantic.BaseModel):
        v: Annotated[int, Bytes("KiB")]

    with pytest.raises(pydantic.ValidationError, match="fractional part"):
        parse_string("v = 512B").decode(P)


def test_pydantic_unsupported_target_fails_at_class_definition() -> None:
    with pytest.raises(TypeError, match="decodes into int / float"):

        class P(pydantic.BaseModel):
            v: Annotated[str, Bytes()]


def test_pydantic_plain_timedelta_keeps_pydantics_own_rules() -> None:
    # Without the marker Pydantic parses timedelta itself (ISO 8601 / seconds);
    # Duration() opts the field into HOCON durations.
    class Plain(pydantic.BaseModel):
        d: timedelta

    class Marked(pydantic.BaseModel):
        d: Annotated[timedelta, Duration()]

    cfg = parse_string("d = 1000")
    assert cfg.decode(Plain).d == timedelta(seconds=1000)
    assert cfg.decode(Marked).d == timedelta(milliseconds=1000)
    assert parse_string("d = 30m").decode(Marked).d == timedelta(minutes=30)


def test_pydantic_markers_act_only_inside_decode() -> None:
    # Constructing a model, or validating its own dump, must not re-read the
    # values as HOCON (90.0 would otherwise become 90 ms = 0.09 s).
    class P(pydantic.BaseModel):
        ttl: Annotated[float, Duration("s")]
        cache: Annotated[float, Bytes("MiB")]
        timeout: Annotated[timedelta, Duration()]

    got = parse_string("ttl = 1.5m, cache = 512KiB, timeout = 30m").decode(P)
    assert P(ttl=90.0, cache=0.5, timeout=timedelta(minutes=30)) == got
    assert P.model_validate(got.model_dump()) == got
    assert P.model_validate_json(got.model_dump_json()) == got
    # Outside decode the field is its plain type: a unit string is not read.
    with pytest.raises(pydantic.ValidationError):
        P.model_validate({"ttl": "1.5m", "cache": 1, "timeout": 1})


def test_pydantic_values_built_in_python_during_decode_are_left_alone() -> None:
    # Only the values decode hands to Pydantic are HOCON values; a model a
    # default_factory or a validator builds during decode is plain Python.
    class Inner(pydantic.BaseModel):
        ttl: Annotated[float, Duration("s")]
        t: Annotated[timedelta, Duration()]

    class Outer(pydantic.BaseModel):
        inner: Inner = pydantic.Field(
            default_factory=lambda: Inner(ttl=90.0, t=timedelta(seconds=5))
        )
        size: Annotated[int, Bytes()]
        echo: Annotated[float, Duration("s")] = 0.0

        @pydantic.model_validator(mode="after")
        def _rebuild(self) -> "Outer":
            Inner(ttl=2.0, t=timedelta(seconds=1))  # must not be re-read
            return self

    got = parse_string("size = 1k").decode(Outer)
    assert got.inner == Inner(ttl=90.0, t=timedelta(seconds=5))
    assert (got.size, got.echo) == (1024, 0.0)


def test_pydantic_validate_default_reads_the_default_as_hocon() -> None:
    # validate_default makes the default part of decode's validation, so it is
    # read like a HOCON value: write it in HOCON form (documented).
    class P(pydantic.BaseModel):
        model_config = pydantic.ConfigDict(validate_default=True)
        ttl: Annotated[float, Duration("s")] = "1.5m"  # type: ignore[assignment]
        t: Annotated[timedelta, Duration()] = timedelta(seconds=5)

    got = parse_string("{}").decode(P)
    assert (got.ttl, got.t) == (90.0, timedelta(seconds=5))


def test_pydantic_custom_init_does_not_receive_the_context() -> None:
    # Pydantic does not pass the validation context to an overridden __init__,
    # so markers inside such a model do not act (documented limitation). Pin
    # it so a Pydantic change that lifts the limitation is noticed.
    class P(pydantic.BaseModel):
        ttl: Annotated[float, Duration("s")]

        def __init__(self, **data: Any) -> None:
            super().__init__(**data)

    assert parse_string("ttl = 1500").decode(P).ttl == 1500.0


def test_pydantic_lazy_iterable_reads_under_the_decode_context() -> None:
    from collections.abc import Iterable

    class P(pydantic.BaseModel):
        sizes: Iterable[Annotated[int, Bytes()]]

    assert list(parse_string("sizes = [1k, 2k]").decode(P).sizes) == [1024, 2048]


def test_pydantic_dataclass_converts_once() -> None:
    @pydantic.dataclasses.dataclass
    class PD:
        ttl: Annotated[float, Duration("s")]
        cache: Annotated[float, Bytes("MiB")]

    assert parse_string("ttl = 1500, cache = 512KiB").decode(PD) == PD(ttl=1.5, cache=0.5)


def test_marker_on_an_optional_constrained_type() -> None:
    class P(pydantic.BaseModel):
        v: Annotated[pydantic.PositiveInt | None, Bytes()] = None

    @dataclass
    class D:
        v: Annotated[pydantic.PositiveInt | None, Bytes()]

    assert parse_string("v = 1k").decode(P).v == 1024
    assert parse_string("v = null").decode(P).v is None
    assert parse_string("v = 1k").decode(D).v == 1024
    with pytest.raises(pydantic.ValidationError, match="greater than 0"):
        parse_string("v = 0").decode(P)


def test_pydantic_rejects_two_markers() -> None:
    with pytest.raises(TypeError, match="nested unit markers"):

        class P(pydantic.BaseModel):
            v: Annotated[int, Bytes(), Duration()]


def test_dataclass_rejects_two_markers_through_optional() -> None:
    @dataclass
    class C:
        v: Annotated[Annotated[int, Bytes()] | None, Duration()]

    with pytest.raises(ConfigError, match="more than one unit marker"):
        parse_string("v = 1k").decode(C)


def test_pydantic_boolean_message_matches_the_getter() -> None:
    class P(pydantic.BaseModel):
        v: Annotated[int, Bytes()]

    with pytest.raises(pydantic.ValidationError, match="expected byte size, got boolean"):
        parse_string("v = true").decode(P)


def test_pydantic_timedelta_overflow_is_a_validation_error() -> None:
    class P(pydantic.BaseModel):
        t: Annotated[timedelta, Duration()]

    with pytest.raises(pydantic.ValidationError, match="duration overflows"):
        parse_string("t = 1000000000000 days").decode(P)


def test_duration_past_the_float_range_is_an_error_in_both_paths() -> None:
    # E21: never inf, whether the field is read by the dataclass path or by
    # Pydantic, in the default unit or a finer one.
    huge = '"1' + "0" * 400 + '.5d"'

    @dataclass
    class D:
        v: Annotated[float, Duration()]

    @dataclass
    class DI:
        v: Annotated[int, Duration("s")]

    class P(pydantic.BaseModel):
        v: Annotated[float, Duration("ns")]

    cfg = parse_string(f"v = {huge}")
    with pytest.raises(ConfigError, match="duration overflows .* at v"):
        cfg.decode(D)
    with pytest.raises(ConfigError, match="duration overflows .* at v"):
        cfg.decode(DI)
    with pytest.raises(pydantic.ValidationError, match="duration overflows"):
        cfg.decode(P)


@pytest.mark.parametrize("text", ["v = 1e3", 'v = "1e3"', 'v = "1e0kB"'])
def test_exponent_form_reads_the_same_in_every_path(text: str) -> None:
    # E20 exponent forms (xx.hocon#111): the getters read `1e3` too, so the
    # dataclass and Pydantic paths agree with them.
    @dataclass
    class D:
        v: Annotated[int, Bytes()]

    class P(pydantic.BaseModel):
        v: Annotated[int, Bytes()]

    cfg = parse_string(text)
    assert cfg.get_bytes("v") == cfg.decode(D).v == cfg.decode(P).v == 1000
