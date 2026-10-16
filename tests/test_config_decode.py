"""Config.decode — typed decoding into dataclasses (and Pydantic delegation).

Behavioural contract mirrors go.hocon Unmarshal / UnmarshalPath: required
fields error when absent, defaults apply, extra keys are ignored, int fields
accept whole-number floats with wholeness derived from the decimal text
(xx.hocon#56), numerically-keyed objects act as sequences (S15), and null
never decodes into a non-optional type (S17.6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import EJECT, Enum, IntEnum, IntFlag
from typing import Any, Optional

import pytest

from hocon import Config, ConfigError, NotResolvedError, ParseError, Period, parse_string


@dataclass
class Server:
    host: str
    port: int


class Level(Enum):
    """Module-level (like real config enums): string annotations resolve
    against module globals under ``from __future__ import annotations``."""

    LOW = "low"
    HIGH = "high"


class Port(IntEnum):
    HTTP = 80
    ALT = 8080


class Code(Enum):
    """String values that read as numbers / booleans in HOCON text."""

    FIVE = "5"
    YES = "true"


class Clash(Enum):
    """Values and names that collide, to pin the lookup order."""

    INT = 5
    STR = "5"
    A = "B"  # value "B" is also the name of the next member
    B = "b"
    on = "enabled"  # a name that is also a boolean spelling
    FLAG = True


@dataclass
class Database:
    url: str
    pool_size: int  # matches HOCON key `pool-size` via kebab-case
    timeout: timedelta = timedelta(seconds=30)


@dataclass
class App:
    server: Server
    database: Database
    debug: bool = False


def test_flat_dataclass() -> None:
    cfg = parse_string("host = localhost, port = 8080")
    s = cfg.decode(Server)
    assert s == Server(host="localhost", port=8080)


def test_nested_dataclass_with_kebab_and_default() -> None:
    cfg = parse_string(
        """
        server { host = localhost, port = 8080 }
        database { url = "jdbc:x", pool-size = 10 }
        """
    )
    app = cfg.decode(App)
    assert app.server.port == 8080
    assert app.database.pool_size == 10
    assert app.database.timeout == timedelta(seconds=30)  # default applied
    assert app.debug is False


def test_decode_at_path() -> None:
    cfg = parse_string("app { server { host = h, port = 1 } }")
    assert cfg.decode(Server, path="app.server") == Server(host="h", port=1)


def test_decode_list_target_at_path() -> None:
    cfg = parse_string('servers = [{ host = a, port = 1 }, { host = b, port = 2 }]')
    servers = cfg.decode(list[Server], path="servers")
    assert servers == [Server("a", 1), Server("b", 2)]


def test_camel_case_key_matches() -> None:
    @dataclass
    class C:
        pool_size: int

    assert parse_string("poolSize = 5").decode(C).pool_size == 5


def test_exact_name_wins_over_kebab() -> None:
    @dataclass
    class C:
        pool_size: int

    cfg = parse_string("pool_size = 1, pool-size = 2")
    assert cfg.decode(C).pool_size == 1


def test_metadata_alias() -> None:
    @dataclass
    class C:
        size: int = field(metadata={"hocon": "max-heap"})

    assert parse_string("max-heap = 64").decode(C).size == 64


def test_metadata_alias_is_exclusive() -> None:
    @dataclass
    class C:
        size: int = field(metadata={"hocon": "max-heap"})

    # the field name is NOT consulted when an alias is present (go tag /
    # serde rename semantics); the error names the key that was looked up
    with pytest.raises(ConfigError, match="max-heap"):
        parse_string("size = 1").decode(C)


def test_metadata_skip_without_default_errors() -> None:
    @dataclass
    class C:
        secret: str = field(metadata={"hocon": "-"})

    with pytest.raises(ConfigError, match="secret"):
        parse_string("x = 1").decode(C)


def test_metadata_skip_alias() -> None:
    @dataclass
    class C:
        host: str
        secret: str = field(default="unset", metadata={"hocon": "-"})

    cfg = parse_string("host = h, secret = leaked")
    assert cfg.decode(C).secret == "unset"


def test_missing_required_field_errors_with_path() -> None:
    cfg = parse_string("server { host = h }")
    with pytest.raises(ConfigError, match="server.port"):
        cfg.decode(App)


def test_extra_keys_ignored() -> None:
    cfg = parse_string("host = h, port = 1, unknown = whatever")
    assert cfg.decode(Server) == Server("h", 1)


def test_optional_null_and_missing_default() -> None:
    @dataclass
    class C:
        # deliberately the typing.Optional spelling: decode must handle the
        # typing.Union origin as well as `str | None`'s types.UnionType (b)
        a: Optional[str]  # noqa: UP045
        b: str | None = None

    got = parse_string("a = null").decode(C)
    assert got.a is None  # explicit null into Optional
    assert got.b is None  # missing key falls back to the default


def test_null_into_non_optional_errors() -> None:
    with pytest.raises(ConfigError, match="null"):
        parse_string("host = null, port = 1").decode(Server)


def test_non_optional_union_unsupported() -> None:
    @dataclass
    class C:
        v: int | str

    with pytest.raises(ConfigError, match="union"):
        parse_string("v = 1").decode(C)


def test_int_accepts_whole_float_rejects_fractional() -> None:
    @dataclass
    class C:
        n: int

    assert parse_string("n = 3.0").decode(C).n == 3
    assert parse_string('n = "1e2"').decode(C).n == 100
    with pytest.raises(ConfigError, match="int"):
        parse_string("n = 2.5").decode(C)


def test_int_wholeness_is_textual_not_float64() -> None:
    @dataclass
    class C:
        n: int

    # both are indistinguishable from whole numbers after a float64 round-trip
    assert parse_string("n = 9007199254740993.0").decode(C).n == 9007199254740993
    with pytest.raises(ConfigError):
        parse_string("n = 9007199254740992.5").decode(C)


def test_int_exponent_bomb_rejected() -> None:
    @dataclass
    class C:
        n: int

    # E19 (xx.hocon#97): the overflowing literal is now rejected at parse
    # time (ParseError), before decode ever sees the value. The decode-layer
    # guard this test originally exercised remains as defense in depth for
    # values injected through non-parse paths.
    with pytest.raises(ParseError):
        parse_string("n = 1e999999").decode(C)


def test_int_wide_finite_exponent_rejected_at_decode() -> None:
    @dataclass
    class C:
        n: int

    # Keeps the decode-layer digit-width guard covered now that the 1e999999
    # bomb above dies at parse time: 1e25 is finite (parses fine) but its
    # whole value exceeds the siblings' ~i64 digit width, so decode rejects
    # it without materializing a huge int.
    with pytest.raises(ConfigError):
        parse_string("n = 1e25").decode(C)


def test_str_accepts_number_scalar_raw() -> None:
    @dataclass
    class C:
        v: str

    assert parse_string("v = 8080").decode(C).v == "8080"


def test_bool_accepts_yes_no() -> None:
    @dataclass
    class C:
        v: bool

    assert parse_string("v = yes").decode(C).v is True
    with pytest.raises(ConfigError, match="bool"):
        parse_string("v = 2").decode(C)


def test_timedelta_and_period() -> None:
    @dataclass
    class C:
        d: timedelta
        p: Period

    got = parse_string('d = "10s", p = "3m"').decode(C)
    assert got.d == timedelta(seconds=10)
    assert got.p == Period(years=0, months=3, days=0)


def test_timedelta_overflow_is_a_config_error_with_the_path() -> None:
    @dataclass
    class C:
        d: timedelta

    # Past timedelta's range: used to escape as a bare OverflowError.
    with pytest.raises(ConfigError, match="duration overflows .* at d") as e:
        parse_string("d = 1000000000000 days").decode(C)
    assert e.value.path == "d"


def test_dict_and_any_fields() -> None:
    @dataclass
    class C:
        labels: dict[str, str]
        extra: Any

    got = parse_string("labels { a = x, b = y }, extra = [1, 2]").decode(C)
    assert got.labels == {"a": "x", "b": "y"}
    assert got.extra == [1, 2]


def test_config_typed_field_stays_dynamic() -> None:
    @dataclass
    class C:
        rest: Config

    got = parse_string("rest { a = 1 }").decode(C)
    assert isinstance(got.rest, Config)
    assert got.rest.get_int("a") == 1


def test_enum_by_value_and_by_name() -> None:
    @dataclass
    class C:
        level: Level

    assert parse_string("level = low").decode(C).level is Level.LOW
    assert parse_string("level = HIGH").decode(C).level is Level.HIGH
    with pytest.raises(ConfigError, match="Level"):
        parse_string("level = nope").decode(C)


@dataclass
class HasPort:
    port: Port


def test_int_enum_from_number_string_and_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PY_HOCON_TEST_PORT", "8080")
    assert parse_string("port = 8080").decode(HasPort).port is Port.ALT
    # a string — quoted, or an env var — is read as a number, as get_int does
    assert parse_string('port = "8080"').decode(HasPort).port is Port.ALT
    assert parse_string("port = ${PY_HOCON_TEST_PORT}").decode(HasPort).port is Port.ALT
    assert parse_string("port = 80.0").decode(HasPort).port is Port.HTTP
    assert parse_string("port = HTTP").decode(HasPort).port is Port.HTTP
    with pytest.raises(ConfigError, match=r"invalid Port at port: '81'"):
        parse_string('port = "81"').decode(HasPort)


def test_str_enum_from_number_and_boolean_literals() -> None:
    # the literal's raw text matches a member whose value is that text
    assert parse_string("a = 5").decode(Code, path="a") is Code.FIVE
    assert parse_string("a = true").decode(Code, path="a") is Code.YES


def test_enum_coerced_reading_keeps_bool_and_number_apart() -> None:
    # get_int rejects "yes" and get_boolean rejects "1"; so does an enum
    with pytest.raises(ConfigError, match="invalid Port"):
        parse_string('a = "yes"').decode(Port, path="a")
    with pytest.raises(ConfigError, match="invalid Clash"):
        parse_string('a = "1"').decode(Clash, path="a")
    assert parse_string('a = "yes"').decode(Clash, path="a") is Clash.FLAG


class Mode(Enum):
    """A `_missing_` hook written for strings, as such hooks usually are."""

    FAST = "fast"
    SAFE = "safe"

    @classmethod
    def _missing_(cls, value: object) -> Mode | None:
        return cls.__members__.get(str(value).upper()) if isinstance(value, str) else None


class Perm(IntFlag):
    READ = 1
    WRITE = 2


class EjectPerm(IntFlag, boundary=EJECT):
    """Gives a plain int, not a member, for a value outside its mask."""

    READ = 1
    WRITE = 2


def test_enum_coerced_reading_only_of_a_kind_the_enum_holds() -> None:
    # Mode holds only strings: "5" / yes never reach _missing_ as 5 / True
    for src in ('a = "5"', "a = yes", 'a = "yes"'):
        with pytest.raises(ConfigError, match="invalid Mode"):
            parse_string(src).decode(Mode, path="a")
    assert parse_string("a = FAST").decode(Mode, path="a") is Mode.FAST
    assert parse_string("a = Safe").decode(Mode, path="a") is Mode.SAFE  # via _missing_
    # IntFlag(True) builds a pseudo-member valued True; "yes" is not a flag value
    with pytest.raises(ConfigError, match="invalid Perm"):
        parse_string("a = yes").decode(Perm, path="a")
    assert parse_string('a = "2"').decode(Perm, path="a") is Perm.WRITE


def test_enum_coerced_reading_failures_are_config_errors() -> None:
    # past Python's int digit limit: no number reading, for any Enum
    huge = '"' + "9" * 5000 + '"'
    for enum in (Mode, Port):
        with pytest.raises(ConfigError, match=f"invalid {enum.__name__}"):
            parse_string(f"a = {huge}").decode(enum, path="a")
    # an EJECT flag's plain int for an out-of-mask value is not a member
    with pytest.raises(ConfigError, match="invalid EjectPerm"):
        parse_string('a = "4"').decode(EjectPerm, path="a")
    assert parse_string('a = "2"').decode(EjectPerm, path="a") is EjectPerm.WRITE


def test_enum_lookup_order() -> None:
    def dec(src: str) -> Clash:
        return parse_string(src).decode(Clash, path="a")

    # 1. by value as written: the number 5 and the string "5" are different values
    assert dec("a = 5") is Clash.INT
    assert dec('a = "5"') is Clash.STR
    # 1 before 2: "B" is a member's value and another member's name
    assert dec("a = B") is Clash.A
    # 2. by name
    assert dec("a = INT") is Clash.INT
    # 2 before 3: "on" is a member's name and a boolean spelling of FLAG's value
    assert dec("a = on") is Clash.on
    # 3. by a coerced reading
    assert dec("a = yes") is Clash.FLAG


def test_numeric_keyed_object_as_list() -> None:
    @dataclass
    class C:
        xs: list[int]

    # S15: {"0": …, "1": …} acts as an array in sequence context
    assert parse_string('xs { "0" = 10, "1" = 20 }').decode(C).xs == [10, 20]


def test_missing_path_errors() -> None:
    with pytest.raises(ConfigError, match="path not found"):
        parse_string("a = 1").decode(Server, path="nope")


def test_unresolved_config_raises_not_resolved() -> None:
    cfg = parse_string("host = ${missing}, port = 1", resolve_substitutions=False)
    with pytest.raises(NotResolvedError):
        cfg.decode(Server)


def test_pydantic_duck_typed_delegation() -> None:
    class FakeModel:
        """Stands in for pydantic.BaseModel: only model_validate is required."""

        captured: Any = None

        @classmethod
        def model_validate(cls, obj: Any) -> FakeModel:
            inst = cls()
            inst.captured = obj
            return inst

    got = parse_string("a = 1, b { c = x }").decode(FakeModel)
    assert got.captured == {"a": 1, "b": {"c": "x"}}


def test_error_paths_are_dotted() -> None:
    cfg = parse_string("server { host = h, port = nope }")

    @dataclass
    class C:
        server: Server

    with pytest.raises(ConfigError, match="server.port"):
        cfg.decode(C)
