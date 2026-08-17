"""Config as a collections.abc.Mapping — indexing, iteration, membership,
value-based equality, and the ``default`` parameter of ``get``.

The contract under test: iteration / ``len`` / ``dict(config)`` cover the
top-level fields; ``config[path]`` / ``path in config`` additionally accept
dotted path expressions, with a literal top-level key winning over path
traversal so iteration → indexing always round-trips.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from hocon import Config, parse_string


@pytest.fixture
def cfg() -> Config:
    return parse_string(
        """
        server { host = localhost, port = 8080 }
        debug = true
        empty-marker = null
        "dotted.key" = literal
        """
    )


def test_is_mapping_instance(cfg: Config) -> None:
    assert isinstance(cfg, Mapping)


def test_getitem_top_level(cfg: Config) -> None:
    assert cfg["debug"] is True
    assert cfg["server"] == {"host": "localhost", "port": 8080}


def test_getitem_dotted_path(cfg: Config) -> None:
    assert cfg["server.host"] == "localhost"
    assert cfg["server.port"] == 8080


def test_getitem_quoted_segment(cfg: Config) -> None:
    assert cfg['"dotted.key"'] == "literal"


def test_getitem_missing_raises_keyerror(cfg: Config) -> None:
    with pytest.raises(KeyError):
        cfg["nope"]
    with pytest.raises(KeyError):
        cfg["server.nope"]


def test_getitem_explicit_null_is_present(cfg: Config) -> None:
    assert cfg["empty-marker"] is None


def test_literal_key_wins_over_path() -> None:
    c = parse_string('a { b = nested }\n"a.b" = literal')
    assert c["a.b"] == "literal"
    assert c["a"]["b"] == "nested"


def test_iteration_round_trips_every_key(cfg: Config) -> None:
    for k in cfg:
        cfg[k]  # must not raise, including the literal dotted key
    assert set(cfg) == {"server", "debug", "empty-marker", "dotted.key"}


def test_len_and_bool(cfg: Config) -> None:
    assert len(cfg) == 4
    assert cfg
    assert not parse_string("")


def test_dict_conversion_matches_to_object(cfg: Config) -> None:
    assert dict(cfg) == cfg.to_object()


def test_star_star_unpacking(cfg: Config) -> None:
    merged = {**cfg, "extra": 1}
    assert merged["debug"] is True
    assert merged["extra"] == 1


def test_contains(cfg: Config) -> None:
    assert "debug" in cfg
    assert "server.host" in cfg
    assert '"dotted.key"' in cfg
    assert "dotted.key" in cfg  # literal branch
    assert "nope" not in cfg
    assert 42 not in cfg  # non-str never raises


def test_items_and_values_mixins(cfg: Config) -> None:
    assert dict(cfg.items()) == cfg.to_object()
    assert sorted(str(v) for v in cfg.values()) == sorted(
        str(v) for v in cfg.to_object().values()
    )


def test_keys_still_returns_list(cfg: Config) -> None:
    ks = cfg.keys()
    assert isinstance(ks, list)
    assert ks[0] == "server"  # list indexing keeps working


def test_equality_is_value_based() -> None:
    a = parse_string("a = 1, b { c = x }")
    b = parse_string("a = 1, b { c = x }")
    assert a == b
    assert a == {"a": 1, "b": {"c": "x"}}
    assert a != parse_string("a = 2")


def test_unhashable_like_dict(cfg: Config) -> None:
    with pytest.raises(TypeError):
        hash(cfg)


def test_get_default_on_missing(cfg: Config) -> None:
    assert cfg.get("nope") is None
    assert cfg.get("nope", 7) == 7
    assert cfg.get("server.nope", "fallback") == "fallback"


def test_get_default_not_used_for_explicit_null(cfg: Config) -> None:
    assert cfg.get("empty-marker", "fallback") is None


def test_get_present_value_ignores_default(cfg: Config) -> None:
    assert cfg.get("server.port", 1) == 8080


def test_subconfig_is_mapping_too(cfg: Config) -> None:
    sub = cfg.get_config("server")
    assert isinstance(sub, Mapping)
    assert dict(sub) == {"host": "localhost", "port": 8080}
    assert sub["host"] == "localhost"
