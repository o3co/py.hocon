"""Empty/comment-only document rejection (S3.1, E10).

Mirrors ts.hocon ``src/internal/parser/empty-check.ts``. HOCON.md L130: empty
files are invalid documents.
"""

from __future__ import annotations

from ...errors import ParseError
from ..lexer.token import Token

__all__ = ["assert_non_empty_document", "has_content_tokens"]


def has_content_tokens(tokens: list[Token]) -> bool:
    """True iff the stream has at least one token that is not eof/newline. The
    lexer consumes whitespace and comments inline, so an eof/newline-only stream
    came from an empty, whitespace-only, or comment-only document."""
    return any(t.kind != "eof" and t.kind != "newline" for t in tokens)


def assert_non_empty_document(tokens: list[Token], source_descriptor: str) -> None:
    """Raise :class:`ParseError` if the stream has no content tokens."""
    if not has_content_tokens(tokens):
        raise ParseError(
            f"empty file is not a valid HOCON document (HOCON.md L130): {source_descriptor}",
            1,
            1,
        )
