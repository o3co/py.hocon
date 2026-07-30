"""Format adapters — the tree-level rules this package owns (F0/F1/F3/F4/F5)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

import hocon
from hocon.adapters import AdapterError, env, jsonc, properties, toml, yaml
from hocon.errors import ConfigError, ParseError

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
    # A control character in the name is escaped rather than sprayed into the
    # message: the quoted form is JSON string syntax, as HOCON's is.
    with pytest.raises(AdapterError, match=r'both map to "a\\nb"$'):
        env.load("APP_", {"APP_A\nB": "1", "APP_a\nb": "2"})
    with pytest.raises(AdapterError, match=r'both map to "a\\u0000b"$'):
        env.load("APP_", {"APP_A\x00B": "1", "APP_a\x00b": "2"})
    # A non-ASCII segment prints as itself (F1.3 leaves it unfolded, and
    # go.hocon's %q / rs.hocon's {:?} print it literally too).
    with pytest.raises(AdapterError, match=r'both map to "İa"$'):
        env.load("APP_", {"APP_İA": "1", "APP_İa": "2"})
    # The variable names are escaped for the same reason the path is: a name
    # holding a newline would otherwise split the message across log lines.
    with pytest.raises(AdapterError, match=r"'APP_A\\nB' and 'APP_a\\nb'"):
        env.load("APP_", {"APP_A\nB": "1", "APP_a\nb": "2"})


def test_env_collision_detection_is_exact_not_delimiter_based() -> None:
    """`load` takes any mapping, so a NUL in a name is type-legal; keying the
    detection on the segments themselves means it cannot fake a collision."""
    cfg = env.load("APP_", {"APP_A\x00B": "1", "APP_A__B": "2"})
    assert cfg.get_string('"a\x00b"') == "1"
    assert cfg.get_string("a.b") == "2"


def test_env_case_folding_is_ascii_only() -> None:
    """F1.3 — `str.lower` would map `İ` (U+0130) to `i` + U+0307 while Go's
    simple mapping yields `i`, which decides F1.6 collisions differently per
    language. ASCII-only folding leaves every non-ASCII codepoint alone."""
    cfg = env.load("APP_", {"APP_İ": "dotted", "APP_I": "ascii"})
    assert cfg.get_string('"İ"') == "dotted", "İ must survive unfolded"
    assert cfg.get_string("i") == "ascii"
    assert not cfg.has('"i̇"'), "no full-Unicode fold artifact"


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


def test_jsonc_line_comment_ends_at_a_carriage_return() -> None:
    """F3.2 — a CR ends a `//` comment, as it does in the dialect this adapter
    implements (node-jsonc-parser's isLineBreak is LF and CR).

    Scanning for LF alone made the comment swallow the next line; the trailing
    comma left behind was then stripped as well, so the document stayed valid
    JSON and the key simply vanished — no error, no diagnostic.
    """
    doc = '{\n  "port": 8080, // the port\r  "tlsRequired": true\n}\n'
    assert jsonc.parse(doc).to_object() == {"port": 8080, "tlsRequired": True}
    # The same document with the comment removed, as a control.
    assert jsonc.parse('{\n  "port": 8080,\r  "tlsRequired": true\n}\n').to_object() == {
        "port": 8080,
        "tlsRequired": True,
    }


def test_jsonc_line_comment_runs_through_u2028() -> None:
    """U+2028 / U+2029 are not line breaks in this dialect, so a comment
    continues through them — matching what VS Code reads, which is the point of
    implementing someone else's dialect rather than inventing one."""
    doc = '{\n  "port": 8080, // the port\u2028  "tls": true\n}\n'
    assert jsonc.parse(doc).to_object() == {"port": 8080}


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
@pytest.mark.parametrize(
    ("src", "key"),
    [
        ("1: a\n'1': b\n", "'1'"),
        ("'1': b\n1: a\n", "'1'"),
        ("1.0: a\n'1.0': b\n", "'1.0'"),
        ("~: a\n'null': b\n", "'null'"),
        ("0x10: a\n'16': b\n", "'16'"),
    ],
)
def test_yaml_refuses_sibling_keys_that_coincide(src: str, key: str) -> None:
    """F5.3 — two source keys with one string form used to be last-wins, and
    the loser's value was gone with nothing left to notice.

    Which forms coincide follows from ruamel's scalar resolution (F5.1) and is
    not aligned across implementations; what is pinned here is that a
    coincidence errors.
    """
    with pytest.raises(AdapterError, match="F5.3") as excinfo:
        yaml.parse(src)
    assert f"both give the key {key}" in str(excinfo.value)


@needs_ruamel
def test_yaml_collision_names_the_path() -> None:
    """The message says where it happened, not just what — and says
    ``document root`` rather than nothing when the collision is at the top, the
    way every other adapter error in this module words it."""
    with pytest.raises(AdapterError, match="at outer"):
        yaml.parse("outer:\n  1: a\n  '1': b\n")
    with pytest.raises(AdapterError, match="at document root"):
        yaml.parse("1: a\n'1': b\n")


@needs_ruamel
def test_yaml_collision_does_not_advise_quoting_when_that_cannot_help() -> None:
    """Quoting ``1`` gives ``'1'``, which is the same key again, so the message
    must not offer it as the fix. Renaming is what always works."""
    with pytest.raises(AdapterError, match="rename one of them"):
        yaml.parse("1: a\n'1': b\n")


@needs_ruamel
def test_yaml_stringifies_a_lone_non_string_key() -> None:
    """The other half of F5.3: no sibling, no collision, just a string form."""
    assert yaml.parse("1: a\n").to_object() == {"1": "a"}
    assert yaml.parse("~: a\n").to_object() == {"null": "a"}


@needs_ruamel
def test_yaml_merge_key_override_is_not_a_collision() -> None:
    """`<<: *defaults` bringing in a key the mapping overrides is YAML's own
    semantics, so the F5.3 check must not fire on it."""
    cfg = yaml.parse("base: &b\n  x: 1\nchild:\n  <<: *b\n  x: 2\n  y: 3\n")
    assert cfg.to_object()["child"] == {"x": 2, "y": 3}


def test_key_collision_check_leaves_the_string_keyed_formats_alone() -> None:
    """JSON and TOML keys are strings by construction, so the shared converter's
    F5.3 check can never fire for them."""
    assert jsonc.parse('{"a": {"b": 1}}').to_object() == {"a": {"b": 1}}
    assert toml.parse("a = 1\n[t]\nb = 2\n").to_object() == {"a": 1, "t": {"b": 2}}


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


def test_a_leading_bom_never_becomes_part_of_a_key(tmp_path: Path) -> None:
    """F0.9 — a Windows editor's BOM left in place lands inside the first key,
    so a lookup of `a` misses and the value is silently unreachable. Every
    file-reading entry point strips it."""
    bom = "﻿"
    cases = {
        "c.properties": (bom + "a = 1\n", properties.parse_file, "a", "1"),
        ".env": (bom + "FOO=1\n", env.parse_dotenv_file, "foo", "1"),
        "c.jsonc": (bom + '{"a": "1"}\n', jsonc.parse_file, "a", "1"),
        "c.toml": (bom + 'a = "1"\n', toml.parse_file, "a", "1"),
        "c.conf": (bom + 'a = "1"\n', hocon.parse_file, "a", "1"),
    }
    for name, (text, reader, key, want) in cases.items():
        p = tmp_path / name
        p.write_text(text, encoding="utf-8")
        cfg = reader(str(p))
        assert cfg.get_string(key) == want, f"{name}: BOM leaked into the key"
        assert cfg.keys() == [key], f"{name}: {cfg.keys()}"


def test_a_leading_bom_never_becomes_part_of_a_key_from_text() -> None:
    """F0.9 again, for the entry points that take an already-decoded str.

    `utf-8-sig` covers only the file readers. A caller who read the bytes
    themselves — or a fixture harness — hands the BOM straight through, and the
    two flat formats then admit it into the first key, which is the failure F0.9
    singles out: the document parses and the value is simply unreachable.
    """
    bom = "﻿"
    cases = [
        ("properties", properties.parse(bom + "a = 1\n"), "a", "1"),
        (".env", env.parse_dotenv(bom + "FOO=1\n"), "foo", "1"),
        ("jsonc", jsonc.parse(bom + '{"a": "1"}\n'), "a", "1"),
        ("toml", toml.parse(bom + 'a = "1"\n'), "a", "1"),
    ]
    for name, cfg, key, want in cases:
        assert cfg.keys() == [key], f"{name}: {cfg.keys()}"
        assert cfg.get_string(key) == want, f"{name}: BOM leaked into the key"

    # Only a *leading* BOM is a byte-order mark; elsewhere U+FEFF is data.
    assert properties.parse("a = x" + bom + "y\n").get_string("a") == "x" + bom + "y"


@needs_ruamel
def test_a_leading_bom_never_becomes_part_of_a_yaml_key(tmp_path: Path) -> None:
    """F0.9, for the adapter whose dependency is an extra."""
    p = tmp_path / "c.yaml"
    p.write_text('﻿a: "1"\n', encoding="utf-8")
    assert yaml.parse_file(str(p)).keys() == ["a"]
    assert yaml.parse('﻿a: "1"\n').keys() == ["a"]


def test_integers_outside_int64_are_refused(tmp_path: Path) -> None:
    """F0.5 — HOCON integers are int64. Python's int is unbounded and its JSON
    and TOML decoders hand back arbitrary precision, so the bound has to be
    checked or a document no sibling can hold would load here."""
    with pytest.raises(AdapterError, match="int64"):
        jsonc.parse('{"a":9223372036854775808}')
    with pytest.raises(AdapterError, match="int64"):
        jsonc.parse('{"a":-9223372036854775809}')
    with pytest.raises(hocon.ConfigError, match="int64"):
        hocon.from_map({"a": 2**63})
    # The bounds themselves are fine, and so is a float of any size.
    assert jsonc.parse('{"a":9223372036854775807}').get_int("a") == 2**63 - 1
    assert hocon.from_map({"a": -(2**63)}).get_int("a") == -(2**63)


def test_used_as_a_substitution_source_under_hocon() -> None:
    """The reason the adapters exist."""
    base = yaml.parse("services:\n  db:\n    image: postgres:16\n")
    cfg = hocon.parse("image = ${services.db.image}", resolve_substitutions=False)
    merged = cfg.with_fallback(base).resolve()
    assert merged.get_string("image") == "postgres:16"


# --- depth: nothing outside the documented error types escapes (#18) ---------
#
# Two mechanisms, because two different things can be too deep. A *name* that
# maps to a path is capped, because one name produces one arbitrarily deep
# chain and 1.5 kB of it used to exhaust the stack. A deeply nested *document*
# is not capped — refusing a 65-level JSON file would be a claim about the
# format — but the RecursionError it can still provoke is turned into the error
# type this library documents.


def test_env_refuses_a_name_deeper_than_the_segment_limit() -> None:
    """rs.hocon caps the same mapping at the same number (its version aborted
    the process rather than raising)."""
    assert env.load("APP_", {"APP_" + "__".join(["s"] * 64): "v"}).keys() == ["s"]
    with pytest.raises(AdapterError, match="over the limit of 64"):
        env.load("APP_", {"APP_" + "__".join(["s"] * 65): "v"})
    with pytest.raises(AdapterError, match="over the limit of 64"):
        env.load("APP_", {"APP_" + "__".join(["s"] * 497): "v"})


def test_dotenv_refuses_a_name_deeper_than_the_segment_limit() -> None:
    with pytest.raises(AdapterError, match="over the limit of 64"):
        env.parse_dotenv("__".join(["S"] * 65) + "=v\n")


def test_properties_refuses_a_key_deeper_than_the_segment_limit() -> None:
    assert properties.parse(".".join(["k"] * 64) + " = 1").keys() == ["k"]
    with pytest.raises(ParseError, match="over the limit of 64"):
        properties.parse(".".join(["k"] * 65) + " = 1")


def test_jsonc_reports_a_too_deep_document_as_an_adapter_error() -> None:
    """The stdlib decoder reaches its recursion limit before anything here
    does, so the guard has to wrap ``json.loads`` and not only the conversion
    after it."""
    assert jsonc.parse('{"a":' * 100 + "1" + "}" * 100).has("a")
    with pytest.raises(AdapterError, match="nested too deeply"):
        jsonc.parse('{"a":' * 2000 + "1" + "}" * 2000)


def test_from_value_reports_a_too_deep_tree_as_an_adapter_error() -> None:
    """``from_value`` skips the decoder entirely, so the shared converter needs
    its own guard rather than relying on ``from_map``'s."""
    with pytest.raises(AdapterError, match="nested too deeply"):
        yaml.from_value(_nested_dict(2000))


def test_from_map_reports_a_too_deep_tree_as_a_config_error() -> None:
    """Every adapter funnels through here, so this is the backstop."""
    with pytest.raises(ConfigError, match="nested too deeply"):
        hocon.from_map(_nested_dict(2000))


def _nested_dict(depth: int) -> dict[str, Any]:
    inner: Any = 1
    for _ in range(depth):
        inner = {"a": inner}
    assert isinstance(inner, dict)
    return inner


def test_parse_reports_a_too_deep_document_as_a_parse_error() -> None:
    with pytest.raises(ParseError, match="nested too deeply"):
        hocon.parse('{"a":' * 2000 + "1" + "}" * 2000)
