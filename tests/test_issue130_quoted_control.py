r"""S1.2.4 raw C0 controls inside quoted strings
([xx.hocon#130](https://github.com/o3co/xx.hocon/issues/130)).

A raw control character (U+0000–U+001F) inside a double-quoted string is a
parse error, as in JSON and Lightbend 1.4.9. The lexer rejected only LF; tab,
CR, U+0001, U+001F and NUL were accepted in value, key, substitution-path and
include position. Triple-quoted (S9.1) and unquoted (S8.8) strings keep
controls verbatim, and DEL / C1 are legal.

The emitter half (E18 decision 5): ``render_hocon`` must escape every C0
control it writes inside double quotes, or its own output stops re-parsing.

Pinning fixtures (auto-discovered by the conformance harnesses once
``make testdata`` syncs them): ``quoted-control/qc01–qc12``, plus ``rt11`` in
the E18 corpus.
"""

from __future__ import annotations

import json

import pytest

import hocon
from hocon import ParseError, from_map

_C0_EXCEPT_LF = [chr(c) for c in range(0x20) if c != 0x0A]


class TestRawControlInQuotedStringRejected:
    @pytest.mark.parametrize("ch", _C0_EXCEPT_LF, ids=lambda c: f"U+{ord(c):04X}")
    def test_value_position_full_c0_sweep(self, ch: str) -> None:
        with pytest.raises(ParseError, match=f"control character U\\+{ord(ch):04X}"):
            hocon.parse_string(f'a = "x{ch}y"\n', env={})

    @pytest.mark.parametrize(
        ("label", "src"),
        [
            ("key", '"a\tb" = 1\n'),
            ("dotted-key-segment", 'a."b\x01" = 1\n'),
            ("quoted-dotted-key", '"a"."b\tc" = 1\n'),
            ("space-joined-key", 'a "b\tc" = 1\n'),
            ("adjacent-key", 'a"b\tc" = 1\n'),
            ("numeric-tail-key", '123abc."x\t= 1\n'),
            ("nested-key", 'o { "a\tb" = 1 }\n'),
            ("array-element", 'a = ["x\x00"]\n'),
            # The key exists (escaped tab), so only the lexer can fail.
            ("subst-path", '"x\\t" = 1\na = ${"x\t"}\n'),
            ("optional-subst", 'a = ${?"x\x1f"}\n'),
            ("concat", 'a = foo "x\x01" bar\n'),
            ("append", 'a = [1]\na += "x\ty"\n'),
            ("include", 'include "x\ty"\n'),
            ("include-required", 'include required("x\ty")\n'),
            ("include-file", 'include file("x\ty")\n'),
            ("include-package-id", 'include package("p\tq", "f.conf")\n'),
            ("include-package-file", 'include package("p", "f\td.conf")\n'),
            ("include-nested", 'a { include "x\ty" }\n'),
        ],
    )
    def test_other_positions(self, label: str, src: str) -> None:
        with pytest.raises(ParseError, match=r"control character U\+00(09|01|00|1F)"):
            hocon.parse_string(src, env={})

    def test_error_points_at_the_character(self) -> None:
        with pytest.raises(ParseError) as exc:
            hocon.parse_string('k = 1\na = "xy\tz"\n', env={})
        assert (exc.value.line, exc.value.col) == (2, 8)
        assert "use a backslash escape (\\u0009)" in str(exc.value)

    def test_lf_keeps_unterminated_error(self) -> None:
        with pytest.raises(ParseError, match="unterminated string"):
            hocon.parse_string('a = "x\ny"\n', env={})


class TestControlCharsLegalOutsideQuotedStrings:
    """The boundary the rejection must not cross."""

    @pytest.mark.parametrize(
        ("label", "src", "want"),
        [
            ("escaped", 'a = "x\\u0000\\u0001\\t\\u001fy"\n', "x\x00\x01\t\x1fy"),
            ("del-c1", 'a = "x\x7f\u0085\u009fy"\n', "x\x7f\u0085\u009fy"),
            ("triple-quoted", 'a = """x\x00\x01\t\r\x1fy"""\n', "x\x00\x01\t\r\x1fy"),
            ("unquoted", "a = x\x01y\x00z\n", "x\x01y\x00z"),
        ],
    )
    def test_accepted(self, label: str, src: str, want: str) -> None:
        assert hocon.parse_string(src, env={}).get_string("a") == want

    def test_escaped_control_in_substitution_path(self) -> None:
        cfg = hocon.parse_string('x { "a\\u0001" = 5 }\nb = ${x."a\\u0001"}\n', env={})
        assert cfg.get_int("b") == 5


class TestRenderHoconEscapesControlChars:
    """E18 decision 5: every C0 control round-trips in values and keys, and
    none is written raw inside double quotes."""

    _TREE = {
        "all-c0": "".join(chr(c) for c in range(0x20)),
        "bare-but-control": "abc\x01def",
        "k\x01ey": "key quotes only because of the control",
        "\x00": "nul key",
        "multi\nline key": "LF key",
        "multi-ctrl": "line1\x01\nline2\x00",
        "multi-tab": "col1\tcol2\nrow2",
        "del-c1": "x\x7f\u0085y",
    }

    def _render(self) -> str:
        return from_map(self._TREE, "test").render_hocon()

    def test_round_trip(self) -> None:
        cfg = from_map(self._TREE, "test")
        text = cfg.render_hocon()
        reparsed = hocon.parse_string(text, env={})
        assert json.dumps(reparsed.to_object(), sort_keys=True) == json.dumps(
            cfg.to_object(), sort_keys=True
        ), text

    def test_no_raw_control_except_lf_tab(self) -> None:
        text = self._render()
        raw = [f"U+{ord(ch):04X}" for ch in text if ch < " " and ch not in "\n\t"]
        assert raw == [], text

    def test_escape_forms(self) -> None:
        text = self._render()
        for want in ("\\b", "\\f", "\\u0000", "\\u0001", "\\u001f"):
            assert want in text, text

    def test_lf_tab_string_stays_triple_quoted(self) -> None:
        assert '"""col1\tcol2\nrow2"""' in self._render()

    def test_del_c1_verbatim(self) -> None:
        assert "x\x7f\u0085y" in self._render()

    def test_lf_key_takes_escaped_form(self) -> None:
        # Keys never triple-quote (E18 decision 3): this parser rejects a
        # triple-quoted key, so the LF is written as an escape.
        assert '"multi\\nline key"' in self._render()
