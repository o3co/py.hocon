"""Spec verification wave — include items (S14a.7/S14a.8/S14a.9/S14a.10,
S14b.3/S14b.4, S14c.2, S14d.2/S14d.3, S14e.1/S14e.2/S14e.3, S14f.4).

Ports the sibling pins for rows this repo carried as 🤷: ts.hocon
``tests/resolver.test.ts`` / ``tests/parser.test.ts``, go.hocon
``spec_phase5_test.go``, and rs.hocon ``tests/include_test.rs``.
"""

from pathlib import Path

import pytest

from hocon import ParseError, ResolveError, parse, parse_file

_D = chr(36)  # '$'


class TestS14aIncludeSyntax:
    """S14a.7–S14a.10 — the include statement's argument syntax."""

    def test_s14a_7_newline_between_include_and_name(self, tmp_path: Path) -> None:
        (tmp_path / "inc.conf").write_text("x = 42\n", encoding="utf-8")
        cfg = parse('include\n"inc.conf"', base_dir=str(tmp_path))
        assert cfg.get_int("x") == 42

    def test_s14a_7_multiple_spaces_between_include_and_name(self, tmp_path: Path) -> None:
        (tmp_path / "inc.conf").write_text("y = 7\n", encoding="utf-8")
        cfg = parse('include   "inc.conf"', base_dir=str(tmp_path))
        assert cfg.get_int("y") == 7

    def test_s14a_8_no_concatenation_on_include_argument(self) -> None:
        with pytest.raises(ParseError):
            parse('include "a.conf" "b.conf"')

    def test_s14a_9_no_substitution_in_include_argument(self) -> None:
        with pytest.raises(ParseError):
            parse("include " + _D + "{path}")

    def test_s14a_10_unquoted_include_argument_rejected(self) -> None:
        with pytest.raises(ParseError):
            parse("include unquoted-file")

    def test_s14a_10_quoted_include_argument_accepted(self, tmp_path: Path) -> None:
        (tmp_path / "exists.conf").write_text("x = 1\n", encoding="utf-8")
        cfg = parse('include "exists.conf"', base_dir=str(tmp_path))
        assert cfg.get_int("x") == 1


class TestS14bIncludeMergeOrder:
    """S14b.3 / S14b.4 — included fields merge with the including file's
    fields by position: later assignment wins either way."""

    def test_s14b_3_included_overrides_earlier_including_value(self, tmp_path: Path) -> None:
        (tmp_path / "inc.conf").write_text("a = from-include\nonly-inc = 1\n", encoding="utf-8")
        cfg = parse('a = before\ninclude "inc.conf"', base_dir=str(tmp_path))
        assert cfg.get_string("a") == "from-include"
        assert cfg.get_int("only-inc") == 1

    def test_s14b_3_object_fields_merge_across_include(self, tmp_path: Path) -> None:
        (tmp_path / "inc.conf").write_text("o { q = 2 }\n", encoding="utf-8")
        cfg = parse('o { p = 1 }\ninclude "inc.conf"', base_dir=str(tmp_path))
        assert cfg.get("o") == {"p": 1, "q": 2}

    def test_s14b_4_later_including_value_overrides_included(self, tmp_path: Path) -> None:
        (tmp_path / "inc.conf").write_text("a = from-include\n", encoding="utf-8")
        cfg = parse('include "inc.conf"\na = after', base_dir=str(tmp_path))
        assert cfg.get_string("a") == "after"


class TestS14c2OriginalPathFallback:
    """S14c.2 — a substitution inside an included file first tries the
    relativized path, then falls back to the original path against the root."""

    def test_relativized_miss_falls_back_to_root(self, tmp_path: Path) -> None:
        (tmp_path / "inner.conf").write_text("ref = " + _D + "{bar}\n", encoding="utf-8")
        cfg = parse(
            'outer { include "inner.conf" }\nbar = "root value"',
            base_dir=str(tmp_path),
        )
        assert cfg.get_string("outer.ref") == "root value"

    def test_relativized_hit_wins_over_root(self, tmp_path: Path) -> None:
        (tmp_path / "inner.conf").write_text(
            "local = here\nref = " + _D + "{local}\n", encoding="utf-8"
        )
        cfg = parse(
            'outer { include "inner.conf" }\nlocal = root',
            base_dir=str(tmp_path),
        )
        # ${local} relativizes to outer.local, which exists → root not consulted.
        assert cfg.get_string("outer.ref") == "here"


class TestS14dRequiredInclude:
    """S14d.2 / S14d.3 — required() include misses error; non-missing IO
    errors are never swallowed."""

    def test_s14d_2_required_missing_include_errors(self, tmp_path: Path) -> None:
        with pytest.raises(ResolveError):
            parse('include required("missing.conf")', base_dir=str(tmp_path))

    def test_s14d_2_plain_missing_include_is_silent(self, tmp_path: Path) -> None:
        cfg = parse('include "missing.conf"\nx = 1', base_dir=str(tmp_path))
        assert cfg.get_int("x") == 1

    def test_s14d_3_non_missing_io_error_propagates(self, tmp_path: Path) -> None:
        # A directory with the include's name is an IO error, not a miss —
        # it must propagate rather than be swallowed like a missing file.
        (tmp_path / "adir.conf").mkdir()
        with pytest.raises(OSError):
            parse('include "adir.conf"\nx = 1', base_dir=str(tmp_path))


class TestS14eExtensionlessInclude:
    """S14e.1–S14e.3 — an extensionless include basename probes
    .properties / .json / .conf, loads every match, and merges them in
    that order (later wins)."""

    def test_s14e_1_single_extension_found(self, tmp_path: Path) -> None:
        (tmp_path / "base.conf").write_text("x = conf\n", encoding="utf-8")
        cfg = parse('include "base"', base_dir=str(tmp_path))
        assert cfg.get_string("x") == "conf"

    def test_s14e_2_all_matching_extensions_loaded(self, tmp_path: Path) -> None:
        (tmp_path / "base.properties").write_text("p=1\n", encoding="utf-8")
        (tmp_path / "base.json").write_text('{"j": 2}\n', encoding="utf-8")
        (tmp_path / "base.conf").write_text("c = 3\n", encoding="utf-8")
        cfg = parse('include "base"', base_dir=str(tmp_path))
        assert (cfg.get("p"), cfg.get_int("j"), cfg.get_int("c")) == ("1", 2, 3)

    def test_s14e_3_load_order_conf_wins_over_json_over_properties(self, tmp_path: Path) -> None:
        (tmp_path / "base.properties").write_text("x=props\nshared=props\n", encoding="utf-8")
        (tmp_path / "base.json").write_text('{"x": "json"}\n', encoding="utf-8")
        (tmp_path / "base.conf").write_text("x = conf\n", encoding="utf-8")
        cfg = parse('include "base"', base_dir=str(tmp_path))
        # .properties → .json → .conf, last wins per key.
        assert cfg.get_string("x") == "conf"
        assert cfg.get_string("shared") == "props"

    def test_s14e_3_json_wins_over_properties(self, tmp_path: Path) -> None:
        (tmp_path / "base.properties").write_text("x=props\n", encoding="utf-8")
        (tmp_path / "base.json").write_text('{"x": "json"}\n', encoding="utf-8")
        cfg = parse('include "base"', base_dir=str(tmp_path))
        assert cfg.get_string("x") == "json"


class TestS14f4AbsolutePath:
    """S14f.4 — file("...") / bare include with an absolute path loads the
    file directly, regardless of the including file's directory."""

    def test_absolute_path_include(self, tmp_path: Path) -> None:
        other = tmp_path / "elsewhere"
        other.mkdir()
        (other / "abs.conf").write_text("x = 9\n", encoding="utf-8")
        base = tmp_path / "base"
        base.mkdir()
        abs_path = (other / "abs.conf").as_posix()
        cfg = parse(f'include "{abs_path}"', base_dir=str(base))
        assert cfg.get_int("x") == 9

    def test_absolute_path_include_from_file(self, tmp_path: Path) -> None:
        other = tmp_path / "elsewhere"
        other.mkdir()
        (other / "abs.conf").write_text("y = 11\n", encoding="utf-8")
        main = tmp_path / "main.conf"
        main.write_text(f'include "{(other / "abs.conf").as_posix()}"\n', encoding="utf-8")
        assert parse_file(str(main)).get_int("y") == 11
