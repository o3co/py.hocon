"""The json5 adapter — a port of go.hocon's ``adapters/json5`` test battery
(F3.3, with the F0.5/F0.6/F3.5/F0.7 strictness rules)."""

from __future__ import annotations

from pathlib import Path

import pytest

import hocon
from hocon.adapters import AdapterError, json5


def _parse(src: str) -> hocon.Config:
    return json5.parse(src, "test.json5")


def _parse_err(src: str, want: str) -> None:
    """Assert that parsing ``src`` fails with an error containing ``want`` —
    the same substring contract go.hocon's parseErr helper checks."""
    with pytest.raises(AdapterError) as excinfo:
        json5.parse(src, "test.json5")
    assert want in str(excinfo.value), f"{src!r}: {excinfo.value}"


# ---------------------------------------------------------------------------
# The json5.org front-page example, minus Infinity/NaN (spec F0.6 rejects
# those — pinned separately below).
# ---------------------------------------------------------------------------


def test_front_page_example() -> None:
    cfg = _parse(r"""{
  // comments
  unquoted: 'and you can quote me on that',
  singleQuotes: 'I can use "double quotes" here',
  lineBreaks: "Look, Mom! \
No \\n's!",
  hexadecimal: 0xdecaf,
  leadingDecimalPoint: .8675309, andTrailing: 8675309.,
  positiveSign: +1,
  trailingComma: 'in objects', andIn: ['arrays',],
  "backwardsCompatible": "with JSON",
}""")

    assert cfg.get_string("unquoted") == "and you can quote me on that"
    assert cfg.get_string("singleQuotes") == 'I can use "double quotes" here'
    assert cfg.get_string("lineBreaks") == "Look, Mom! No \\n's!"
    assert cfg.get_string("trailingComma") == "in objects"
    assert cfg.get_string("backwardsCompatible") == "with JSON"
    assert cfg.get_int("hexadecimal") == 0xDECAF
    assert cfg.get_float("leadingDecimalPoint") == 0.8675309
    assert cfg.get_float("andTrailing") == 8675309.0
    assert cfg.get_int("positiveSign") == 1
    assert cfg.get_list("andIn") == ["arrays"]


# ---------------------------------------------------------------------------
# Identifier keys (ES5 IdentifierName)
# ---------------------------------------------------------------------------


def test_identifier_keys() -> None:
    cfg = _parse("{a: 1, $b: 2, _c: 3, é: 4, a1: 5}")
    for path, want in {"a": 1, "$b": 2, "_c": 3, "é": 4, "a1": 5}.items():
        assert cfg.get_int(path) == want, path


def test_identifier_key_unicode_escape() -> None:
    r"""\u0061 = 'a'; ES5 allows \u escapes inside IdentifierName."""
    cfg = _parse(r"{\u0061\u0062: 7}")
    assert cfg.get_int("ab") == 7


def test_identifier_key_errors() -> None:
    _parse_err("{1a: 1}", "expected an object key")
    # \u0031 = '1' — a legal escape, but not a legal identifier START.
    _parse_err(r"{\u0031x: 1}", "not a valid identifier character")
    _parse_err(r"{\x61: 1}", r"only \uXXXX escapes")


# ---------------------------------------------------------------------------
# Strings
# ---------------------------------------------------------------------------


def test_string_escapes() -> None:
    cfg = _parse(r"""{
  hex: "\x41\x42",
  vtab: "a\vb",
  nul: "a\0b",
  self: "\q\'\"",
  astral: "\uD83D\uDE00",
}""")
    assert cfg.get_string("hex") == "AB"
    assert cfg.get_string("vtab") == "a\vb"
    assert cfg.get_string("nul") == "a\x00b"
    assert cfg.get_string("self") == "q'\""
    assert cfg.get_string("astral") == "\U0001f600"


def test_string_line_continuations() -> None:
    """LF, CRLF, and LS continuations all contribute nothing."""
    cfg = _parse("{a: 'x\\\ny', b: 'x\\\r\ny', c: 'x\\\u2028y'}")
    for path in ("a", "b", "c"):
        assert cfg.get_string(path) == "xy", path


def test_string_unescaped_separators_allowed() -> None:
    """LS/PS are legal unescaped inside JSON5 strings (the ES5 quirk)."""
    cfg = _parse("{a: 'x\u2028y'}")
    assert cfg.get_string("a") == "x\u2028y"


def test_string_errors() -> None:
    _parse_err("{a: 'x\ny'}", "unescaped line terminator")
    _parse_err("{a: 'oops}", "unterminated string")
    _parse_err(r"{a: '\01'}", "octal escape")
    _parse_err(r"{a: '\7'}", "digits cannot be escaped")
    # F3.5: a lone surrogate is an error, high or low, paired-wrong or alone.
    _parse_err(r'{a: "\uD800"}', "spec F3.5")
    _parse_err(r'{a: "\uD800\u0041"}', "spec F3.5")
    _parse_err(r'{a: "\uDE00"}', "spec F3.5")


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------


def test_numbers() -> None:
    cfg = _parse("""{
  hex: 0xFF, hexneg: -0x10, hexplus: +0xA,
  min: -0x8000000000000000, max: 0x7FFFFFFFFFFFFFFF,
  lead: .5, trail: 5., plus: +5, exp: 1e3, negzero: -0,
}""")
    assert cfg.get_int("hex") == 255
    assert cfg.get_int("hexneg") == -16
    assert cfg.get_int("hexplus") == 10
    assert cfg.get_int("min") == -(2**63)
    assert cfg.get_int("max") == 2**63 - 1
    assert cfg.get_float("lead") == 0.5
    assert cfg.get_float("trail") == 5.0
    assert cfg.get_int("plus") == 5
    assert cfg.get_float("exp") == 1000.0
    assert cfg.get_int("negzero") == 0


def test_number_errors() -> None:
    # F0.5: integers that do not fit in int64 are errors, not silent floats.
    _parse_err("{a: 0x10000000000000000}", "spec F0.5")
    _parse_err("{a: -0x8000000000000001}", "spec F0.5")
    _parse_err("{a: 9223372036854775808}", "spec F0.5")
    _parse_err("{a: 0x}", "hex literal needs at least one digit")
    # F0.6: Infinity and NaN in every spelling.
    for lit in ("Infinity", "-Infinity", "+Infinity", "NaN", "-NaN", "+NaN"):
        _parse_err("{a: " + lit + "}", "spec F0.6")
    # A longer identifier that merely STARTS with those spellings is not the
    # F0.6 case — it errors as an unexpected token / malformed number.
    _parse_err("{a: Infinityx}", "unexpected character")
    _parse_err("{a: NaNx}", "unexpected character")
    _parse_err("{a: -Infinityx}", "malformed number")


# ---------------------------------------------------------------------------
# Comments, whitespace, structure
# ---------------------------------------------------------------------------


def test_comments_and_whitespace() -> None:
    """A U+2028 ends a ``//`` comment (deliberately unlike jsonc, whose
    dialect owner ends comments at LF/CR only), and NBSP / EM SPACE are
    whitespace."""
    cfg = _parse(
        "{\n  // line comment\u2028 a: 1,\n  /* block\n comment */ b: 2,\u00a0c:\u20033\n}"
    )
    for path, want in {"a": 1, "b": 2, "c": 3}.items():
        assert cfg.get_int(path) == want, path


def test_comment_and_structure_errors() -> None:
    _parse_err("{a: 1} /* open", "unterminated /* comment")
    _parse_err("{a: 1} }", "unexpected content after top-level value")
    _parse_err("{a: 1", "unterminated object")
    _parse_err("[1, 2", "unterminated array")
    _parse_err("[,1]", "unexpected character")
    _parse_err("[1,,2]", "unexpected character")
    _parse_err("{a 1}", "expected ':'")
    # F0.3: the root must be an object.
    _parse_err("[1, 2]", "spec F0.3")
    _parse_err('"just a string"', "spec F0.3")


def test_trailing_trivia_accepted() -> None:
    """Trailing whitespace and comments after the value are fine (only
    content is an error)."""
    cfg = _parse("{a: 1} // done\n/* and a block */\n\n")
    assert cfg.get_int("a") == 1


# ---------------------------------------------------------------------------
# Duplicate keys (spec F0.7)
# ---------------------------------------------------------------------------


def test_duplicate_keys_follow_hocon_semantics() -> None:
    # Two objects merge…
    cfg = _parse("{a: {x: 1, shared: {p: 1}}, a: {y: 2, shared: {q: 2}}}")
    assert cfg.get_int("a.x") == 1
    assert cfg.get_int("a.y") == 2
    assert cfg.get_int("a.shared.p") == 1
    assert cfg.get_int("a.shared.q") == 2

    # …anything else is last-wins.
    assert _parse("{a: 1, a: 2}").get_int("a") == 2
    assert _parse("{a: {x: 1}, a: 2}").get_int("a") == 2


# ---------------------------------------------------------------------------
# BOM and encoding (spec F0.9, S1.1 posture)
# ---------------------------------------------------------------------------


def test_bom() -> None:
    """A leading BOM is stripped (F0.9); an interior U+FEFF is whitespace,
    which JSON5's WhiteSpace production names explicitly."""
    cfg = _parse("\ufeff{a: \ufeff1}")
    assert cfg.get_int("a") == 1


def test_lone_surrogate_in_source_rejected() -> None:
    """The py analogue of go's invalid-UTF-8 rejection: a Python str can hold
    a lone surrogate (``surrogateescape`` decoding produces one), but the
    source was then never valid UTF-8, so it is refused wherever it hides —
    string literals and the bodies of both comment forms included (F3.5)."""
    for name, src in {
        "string": '{a: "\ud800"}',
        "line-comment": "{a: 1} // c\udfffc",
        "block-comment": "{a: /* c\ud800c */ 1}",
    }.items():
        with pytest.raises(AdapterError, match="F3.5") as excinfo:
            json5.parse(src, "test.json5")
        assert "surrogate" in str(excinfo.value), name


# ---------------------------------------------------------------------------
# Depth (the repo-wide guarantee: never a bare RecursionError)
# ---------------------------------------------------------------------------


def test_a_too_deep_document_is_an_adapter_error() -> None:
    """The recursive-descent parser recurses per nesting level, so the
    recursion guard has to wrap the parse — same contract as jsonc."""
    assert json5.parse("{a:" * 100 + "1" + "}" * 100).has("a")
    with pytest.raises(AdapterError, match="nested too deeply"):
        json5.parse("{a:" * 2000 + "1" + "}" * 2000)


# ---------------------------------------------------------------------------
# Merge with a HOCON document (the adapter's purpose)
# ---------------------------------------------------------------------------


def test_with_fallback_merge() -> None:
    base = json5.parse("{db: {host: 'localhost', port: 5432}}", "base.json5")
    cfg = hocon.parse(
        "db { host = db.example.com }\nurl = ${db.host}",
        resolve_substitutions=False,
    )
    merged = cfg.with_fallback(base).resolve()
    assert merged.get_string("db.host") == "db.example.com"
    assert merged.get_int("db.port") == 5432
    assert merged.get_string("url") == "db.example.com"


def test_parse_file_uses_path_as_origin(tmp_path: Path) -> None:
    p = tmp_path / "conf.json5"
    p.write_text("{a: [}", encoding="utf-8")
    with pytest.raises(AdapterError, match=r"conf\.json5"):
        json5.parse_file(p)
