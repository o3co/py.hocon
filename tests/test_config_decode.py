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
from enum import Enum
from typing import Any, Optional

import pytest

from hocon import Config, ConfigError, NotResolvedError, Period, parse_string


@dataclass
class Server:
    host: str
    port: int


class Level(Enum):
    """Module-level (like real config enums): string annotations resolve
    against module globals under ``from __future__ import annotations``."""

    LOW = "low"
    HIGH = "high"


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

    with pytest.raises(ConfigError):
        parse_string("n = 1e999999").decode(C)


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
