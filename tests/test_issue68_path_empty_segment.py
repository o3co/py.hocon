r"""S11.7 empty path segments in KEY position + S8.1 backtick reservation
([xx.hocon#68](https://github.com/o3co/xx.hocon/issues/68)).

Two independent spec gaps, both confirmed against the reference implementation:

- **S11.7 (HOCON.md L515-519)** — "If a path element is an empty string, it must
  always be quoted. That is, ``a."".b`` is a valid path with three elements, and
  the middle element is an empty string. But ``a..b`` is invalid and should
  generate an error. Following the same rule, a path that starts or ends with a
  ``.`` is invalid and should generate an error." The **substitution** path
  lexer already enforced this (``${a..b}`` → "empty segment in path"); the
  **key** path parser silently dropped empty segments, so ``a..b: 3`` collapsed
  to ``{"a": {"b": 3}}``. A *quoted* empty segment (``a."".b``) stays legal.

- **S8.1 (HOCON.md L245-247)** — the forbidden-character set for unquoted
  strings is ``$ " { } [ ] : = , + # ` ^ ? ! @ * & \``. Every member was
  rejected except the backtick, which leaked into both key and value position
  (```a = `t` ``` parsed as the string ``` `t` ```). Note ``(`` / ``)`` are
  deliberately NOT in the set (xx.hocon#34); a backtick *inside quotes* is
  ordinary content.

Pinning fixtures (auto-discovered by the error-fixture harness once
``make testdata`` syncs them): ``path-empty-segment/pe01–pe08`` and
``unquoted-forbidden/uf01–uf04``. This file pins the same behaviour inline,
plus the E13 path-whitespace cases that must NOT regress.
"""

from __future__ import annotations

import pytest

import hocon
from hocon import ParseError


class TestKeyPathEmptySegment:
    """S11.7 — the gap: empty segments accepted in key position."""

    @pytest.mark.parametrize(
        ("label", "src"),
        [
            ("pe01-adjacent-dots", "a..b: 3"),
            ("pe02-leading-dot", ".a: 3"),
            ("pe04-triple-dots", "a...c: 4"),
            ("pe05-adjacent-dots-nested", "o { a..b: 3 }"),
            ("pe06-triple-dots-quoted-empty", 'a...c."": 4'),
            # Not fixtures, but the same rule: a leading dot after a quoted
            # segment, and adjacent dots before one.
            ("leading-dots-only", "..b: 1"),
            ("quoted-then-adjacent-dots", '""..b: 3'),
            ("adjacent-dots-then-quoted", 'a.."".b: 3'),
        ],
    )
    def test_rejected(self, label: str, src: str) -> None:
        with pytest.raises(ParseError) as excinfo:
            hocon.parse(src)
        assert "empty key segment not allowed" in str(excinfo.value), label

    def test_pe07_quoted_empty_segment_is_legal(self) -> None:
        """S11.6 — the escape hatch the spec names explicitly."""
        assert hocon.parse('a."".b: 3').to_object() == {"a": {"": {"b": 3}}}

    def test_pe03_trailing_dot_still_rejected(self) -> None:
        """Regression guard — already correct before the fix."""
        with pytest.raises(ParseError):
            hocon.parse("a.: 3")

    @pytest.mark.parametrize(
        ("label", "src"),
        [
            ("pe08-adjacent-dots", "x = 1\ny = ${?a..b}"),
            ("leading-dot", "y = ${?.a}"),
            ("trailing-dot", "y = ${?a.}"),
        ],
    )
    def test_substitution_paths_still_rejected(self, label: str, src: str) -> None:
        """Regression guard — the substitution path lexer already enforced S11.7."""
        with pytest.raises(ParseError) as excinfo:
            hocon.parse(src)
        assert "empty segment in path" in str(excinfo.value), label

    @pytest.mark.parametrize(
        ("label", "src", "expected"),
        [
            # E13 / S10.8: whitespace around a dot separator is significant and
            # becomes part of (or its own) path segment — never an empty one.
            ("pw01-space-after-dot", "a b. c = 1", {"a b": {" c": 1}}),
            ("pw02-space-both-sides", "a . b = 1", {"a ": {" b": 1}}),
            ("pw03-space-before-dot", "a .b = 1", {"a ": {"b": 1}}),
            ("pw04-space-concat-both", "a b.c d = 1", {"a b": {"c d": 1}}),
            ("pw05-multi-ws-both-sides", "a b . c = 1", {"a b ": {" c": 1}}),
            ("pw07-tab-after-dot", "a b.\tc = 1", {"a b": {"\tc": 1}}),
            ("dot-ws-dot", "a. .b = 1", {"a": {" ": {"b": 1}}}),
            ("plain-nested", "a.b.c = 1", {"a": {"b": {"c": 1}}}),
        ],
    )
    def test_path_whitespace_unaffected(
        self, label: str, src: str, expected: dict[str, object]
    ) -> None:
        assert hocon.parse(src).to_object() == expected, label


class TestUnquotedBacktick:
    """S8.1 — backtick is a reserved character outside quotes."""

    @pytest.mark.parametrize(
        ("label", "src"),
        [
            ("uf01-value", "a = `t`"),
            ("uf02-key", "`k` = 1"),
            ("uf03-mid-token", "a = x`y"),
        ],
    )
    def test_rejected(self, label: str, src: str) -> None:
        with pytest.raises(ParseError) as excinfo:
            hocon.parse(src)
        assert "`" in str(excinfo.value), label

    @pytest.mark.parametrize(
        ("label", "src", "expected"),
        [
            ("uf04-quoted", 'a = "x`y"', {"a": "x`y"}),
            ("triple-quoted", 'a = """x`y"""', {"a": "x`y"}),
            ("quoted-key", '"`k`" = 1', {"`k`": 1}),
            ("comment", "# `c`\na = 1", {"a": 1}),
        ],
    )
    def test_backtick_in_quotes_is_content(
        self, label: str, src: str, expected: dict[str, object]
    ) -> None:
        assert hocon.parse(src).to_object() == expected, label

    @pytest.mark.parametrize(
        ("label", "src", "expected"),
        [
            # xx.hocon#34: '(' and ')' are deliberately NOT reserved.
            ("paren-value", "a = (x)", {"a": "(x)"}),
            ("paren-key", "k(1) = 2", {"k(1)": 2}),
        ],
    )
    def test_parens_still_unreserved(
        self, label: str, src: str, expected: dict[str, object]
    ) -> None:
        assert hocon.parse(src).to_object() == expected, label
