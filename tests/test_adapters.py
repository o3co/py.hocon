"""Format adapters — the tree-level rules this package owns (F0/F1/F3/F4/F5)."""

from __future__ import annotations

import importlib.util

import pytest

import hocon
from hocon.adapters import AdapterError, env, jsonc, properties, toml, yaml

# The yaml adapter's dependency is an extra, so a checkout installed without it
# can still run everything else.
_HAS_RUAMEL = importlib.util.find_spec("ruamel.yaml") is not None
needs_ruamel = pytest.mark.skipif(not _HAS_RUAMEL, reason="needs `pip install hocon-parser[yaml]`")


def test_properties_nests_and_shares_the_include_syntax_layer() -> None:
    cfg = properties.parse("db.host = db.internal\na = one\\\ntwo\n")
    assert cfg.get_string("db.host") == "db.internal"
    assert cfg.get_string("a") == "onetwo"


def test_properties_leaves_substitution_syntax_literal() -> None:
    """F0.2 — the file belongs to another program, so ${...} is data."""
    assert properties.parse("a = ${foo.bar}").get_string("a") == "${foo.bar}"


def test_properties_keeps_prototype_pollution_names_as_ordinary_keys() -> None:
    """F2.9 — no key denylist. Python dicts have no prototype to pollute, and
    silently dropping a key is data loss."""
    cfg = properties.parse(
        "__proto__ = a\n"
        "constructor = b\n"
        "prototype = c\n"
        "x.__proto__ = d\n"
        "deep.constructor.leaf = e\n"
    )
    assert cfg.get_string("__proto__") == "a"
    assert cfg.get_string("constructor") == "b"
    assert cfg.get_string("prototype") == "c"
    assert cfg.get_string("x.__proto__") == "d"
    assert cfg.get_string("deep.constructor.leaf") == "e"


def test_properties_leaves_no_phantom_parent_behind() -> None:
    """The old denylist dropped the key after creating its parents, leaving a
    phantom empty object where the document defined a value."""
    cfg = properties.parse("x.__proto__ = f\n")
    assert cfg.get_config("x").keys() == ["__proto__"], "x must not be an empty object"
    assert cfg.get_string("x.__proto__") == "f"
    # The case where the phantom was the whole result: this parsed to {} before.
    nested = properties.parse("__proto__.a = 1\n")
    assert nested.get_string("__proto__.a") == "1"


def test_env_mounts_a_prefixed_namespace() -> None:
    """F1.2/F1.3 — `__` separates, a single `_` does not, segments lowercase."""
    cfg = env.load(
        "APP_",
        {
            "APP_DB__HOST": "db.internal",
            "APP_DB__MAX_CONN": "10",
            "APP_NAME": "svc",
            "PATH": "/usr/bin",
        },
    )
    assert cfg.get_string("db.host") == "db.internal"
    assert cfg.get_string("db.max_conn") == "10"
    assert cfg.get_string("name") == "svc"
    assert not cfg.has("path")


def test_env_requires_a_prefix() -> None:
    """F1.1 — mounting everything would pull in unrelated secrets."""
    with pytest.raises(AdapterError, match="F1.1"):
        env.load("", {})


def test_env_refuses_a_collision() -> None:
    """F1.6 — the environment has no order to break a tie with."""
    with pytest.raises(AdapterError, match=r"both map to a\.b$"):
        env.load("APP_", {"APP_A__B": "1", "APP_a__b": "2"})
    # A literal-dot pair genuinely reaching one path is still a collision, and
    # the message spells the path as HOCON would, so the single quoted segment
    # is not mistaken for the two-segment `__` spelling.
    with pytest.raises(AdapterError, match=r'both map to "foo\.bar"$'):
        env.load("APP_", {"APP_FOO.BAR": "1", "APP_foo.bar": "2"})


def test_env_collision_detection_is_exact_not_delimiter_based() -> None:
    """`load` takes any mapping, so a NUL in a name is type-legal; keying the
    detection on the segments themselves means it cannot fake a collision."""
    cfg = env.load("APP_", {"APP_A\x00B": "1", "APP_A__B": "2"})
    assert cfg.get_string('"a\x00b"') == "1"
    assert cfg.get_string("a.b") == "2"


def test_env_keeps_a_literal_dot_as_key_text() -> None:
    """F1.2 — only `__` creates hierarchy; a `.` in the name is key text, so
    the value lands under one top-level key, addressable by quoting."""
    cfg = env.load("APP_", {"APP_FOO.BAR": "v"})
    assert cfg.get_string('"foo.bar"') == "v"
    assert not cfg.has("foo"), "must not nest — no phantom foo object"


def test_env_literal_dot_coexists_with_the_separated_path() -> None:
    """F1.2/F1.6 — `APP_FOO.BAR` and `APP_FOO__BAR` are different paths and
    must not be reported as a collision."""
    cfg = env.load("APP_", {"APP_FOO.BAR": "1", "APP_FOO__BAR": "2"})
    assert cfg.get_string('"foo.bar"') == "1"
    assert cfg.get_string("foo.bar") == "2"


def test_dotenv_reads_the_small_dialect() -> None:
    """F1.7 — a deliberately small dialect."""
    cfg = env.parse_dotenv(
        "\n".join(
            [
                "# comment",
                "export FOO=bar",
                "DB__HOST=db.internal",
                'QUOTED="a\\nb"',
                "SINGLE='raw ${x} #hash'",
                "HASH=#fff",
            ]
        )
    )
    assert cfg.get_string("foo") == "bar"
    assert cfg.get_string("db.host") == "db.internal"
    assert cfg.get_string("quoted") == "a\nb"
    assert cfg.get_string("single") == "raw ${x} #hash"
    assert cfg.get_string("hash") == "#fff"


def test_dotenv_keeps_a_literal_dot_as_key_text() -> None:
    """F1.2 applies to the .env path too — same mapping, same rule."""
    cfg = env.parse_dotenv("FOO.BAR=v\n")
    assert cfg.get_string('"foo.bar"') == "v"
    assert not cfg.has("foo"), "must not nest — no phantom foo object"


def test_dotenv_is_last_wins_on_a_repeated_name() -> None:
    """F0.7 — a file has a definite line order, so the last line wins where the
    environment would raise. Pins that `_nest`'s sort stays stable now that its
    key is a segment list rather than a string."""
    assert env.parse_dotenv("A=1\nA=2\n").get_string("a") == "2"
    assert env.parse_dotenv("A.B=1\nA.B=2\n").get_string('"a.b"') == "2"
    assert env.parse_dotenv("A__B=1\nA__B=2\n").get_string("a.b") == "2"


def test_dotenv_refuses_an_ambiguous_trailing_hash() -> None:
    with pytest.raises(AdapterError, match="quote the value"):
        env.parse_dotenv("FOO=bar # comment")


def test_jsonc_accepts_comments_and_trailing_commas() -> None:
    cfg = jsonc.parse(
        """{
          // line
          "a": 1, /* block */
          "b": [1, 2,],
          "c": { "d": true, },
        }"""
    )
    assert cfg.get_int("a") == 1
    assert cfg.get_boolean("c.d") is True


def test_jsonc_leaves_comment_markers_inside_strings() -> None:
    cfg = jsonc.parse('{"url": "https://example.com/a//b", "note": "a /* b */ c"}')
    assert cfg.get_string("url") == "https://example.com/a//b"
    assert cfg.get_string("note") == "a /* b */ c"


def test_jsonc_comment_removal_separates_tokens() -> None:
    """F3.2 — a comment is replaced by whitespace, never the empty string, so
    the tokens around it cannot fuse into one valid token."""
    with pytest.raises(AdapterError, match="Expecting ',' delimiter"):
        jsonc.parse('{"a":1/*x*/2}')
    with pytest.raises(AdapterError, match="Expecting value"):
        jsonc.parse('{"b": tr/*x*/ue}')


def test_jsonc_refuses_a_non_object_root() -> None:
    """F0.3 — a config root has to be an object."""
    with pytest.raises(AdapterError, match="F0.3"):
        jsonc.parse("[1, 2]")


def test_toml_maps_tables_and_arrays_of_tables() -> None:
    cfg = toml.parse(
        'name = "svc"\nport = 8080\n[db]\nhost = "localhost"\n'
        "[[db.replicas]]\nid = 1\n[[db.replicas]]\nid = 2\n"
    )
    assert cfg.get_string("name") == "svc"
    assert cfg.get_int("port") == 8080
    assert cfg.get_string("db.host") == "localhost"


def test_toml_renders_datetimes_as_strings() -> None:
    """F4.2 — HOCON has no datetime, so dates are their ISO text."""
    cfg = toml.parse("a = 1979-05-27T07:32:00Z\nb = 1979-05-27\nc = 07:32:00\n")
    assert cfg.get_string("a").startswith("1979-05-27T07:32:00")
    assert cfg.get_string("b") == "1979-05-27"
    assert cfg.get_string("c") == "07:32:00"


def test_toml_refuses_infinity() -> None:
    with pytest.raises(AdapterError, match="F0.6"):
        toml.parse("a = inf")


@needs_ruamel
def test_yaml_maps_scalars_mappings_and_sequences() -> None:
    cfg = yaml.parse("name: svc\nport: 8080\ntags: [a, b]\ndb:\n  host: localhost\n")
    assert cfg.get_string("name") == "svc"
    assert cfg.get_int("port") == 8080
    assert cfg.get_string("db.host") == "localhost"


@needs_ruamel
def test_yaml_keeps_norway_a_string() -> None:
    """The default library reads YAML 1.2, so `no` is not False.

    Not a portability contract — scalar resolution belongs to the library
    (spec F5 "Scope") — but it is why PyYAML is not the default.
    """
    cfg = yaml.parse("no: no\nyes: yes\nreal: true\n")
    assert cfg.get_string('"no"') == "no"
    assert cfg.get_string('"yes"') == "yes"
    assert cfg.get_boolean("real") is True


@needs_ruamel
def test_yaml_resolves_merge_keys_and_aliases() -> None:
    """F5.2 — no aliases or `<<` may survive into the config."""
    cfg = yaml.parse("d: &d\n  host: h\n  port: 1\np:\n  <<: *d\n  port: 2\ncopy: *d\n")
    assert cfg.get_string("p.host") == "h"
    assert cfg.get_int("p.port") == 2, "explicit key must win"
    assert cfg.get_int("copy.port") == 1
    assert not cfg.has("p.<<")


@needs_ruamel
def test_yaml_refuses_a_multi_document_stream() -> None:
    """F5.7 — decoding one and dropping the rest would be silent loss."""
    with pytest.raises(AdapterError, match="F5.7"):
        yaml.parse("a: 1\n---\nb: 2\n")


@needs_ruamel
def test_yaml_empty_document_is_the_empty_object() -> None:
    """F5.9 — as an empty HOCON document is (S3.1)."""
    assert yaml.parse("").keys() == []


@needs_ruamel
def test_yaml_refuses_nan_and_a_sequence_root() -> None:
    with pytest.raises(AdapterError, match="F0.6"):
        yaml.parse("a: .nan")
    with pytest.raises(AdapterError, match="F0.3"):
        yaml.parse("- 1\n- 2")


@needs_ruamel
def test_yaml_from_value_accepts_an_externally_decoded_tree() -> None:
    """The tree-level entry point: the caller picks the library, the rules stay."""
    cfg = yaml.from_value({"db": {"host": "h", "port": 5432}}, "via-caller")
    assert cfg.get_string("db.host") == "h"
    assert cfg.get_int("db.port") == 5432

    with pytest.raises(AdapterError, match="F0.6"):
        yaml.from_value({"a": float("nan")})
    with pytest.raises(AdapterError, match="F0.3"):
        yaml.from_value([1, 2])


def test_used_as_a_substitution_source_under_hocon() -> None:
    """The reason the adapters exist."""
    base = yaml.parse("services:\n  db:\n    image: postgres:16\n")
    cfg = hocon.parse("image = ${services.db.image}", resolve_substitutions=False)
    merged = cfg.with_fallback(base).resolve()
    assert merged.get_string("image") == "postgres:16"
