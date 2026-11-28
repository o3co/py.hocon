"""Error types raised by the parser, resolver, and Config accessors.

Mirrors ts.hocon ``src/errors.ts``. The hierarchy is intentionally split in
two: ``ParseError`` / ``ResolveError`` belong to the parse/resolve pipeline,
while ``ConfigError`` covers accessor-time failures on a ``Config``. They do
not share a common base beyond ``Exception``.
"""

from __future__ import annotations

__all__ = [
    "ConfigError",
    "NotResolvedError",
    "PackageLookupError",
    "ParseError",
    "ResolutionLimitError",
    "ResolveError",
]


class ParseError(Exception):
    def __init__(self, message: str, line: int, col: int, file: str | None = None) -> None:
        super().__init__(message)
        self.line = line
        self.col = col
        self.file = file


class ResolveError(Exception):
    def __init__(
        self, message: str, path: str, line: int, col: int, file: str | None = None
    ) -> None:
        super().__init__(message)
        self.path = path
        self.line = line
        self.col = col
        self.file = file


class ResolutionLimitError(ResolveError):
    """Raised when a resolve keeps working after a cycle break past the limits
    of xx.hocon resolution-model §10.3 (E24): more than 100,000 lookups, or
    more than 10,000 weight units per document value built, in the region of
    an optional cycle break. A subclass of ``ResolveError``, so
    ``except ResolveError`` still catches it; no optional substitution does.
    The message starts with "resolution limit exceeded after a cycle break".
    """


class PackageLookupError(ResolveError):
    """Raised when ``include package("id", "file")`` resolution fails because the
    package cannot be located.

    Extends ``ResolveError`` so callers who catch ``ResolveError`` still handle
    it, while callers who need to distinguish a missing-package error can use
    ``isinstance(err, PackageLookupError)``.
    """

    def __init__(
        self, message: str, identifier: str, package_file: str, line: int, col: int
    ) -> None:
        super().__init__(message, f"{identifier}/{package_file}", line, col)
        self.identifier = identifier
        self.package_file = package_file


class ConfigError(Exception):
    """Type-mismatch / access error at the Config boundary: raised by value
    accessors, and by ``parse`` / ``parse_file`` for an array-root document
    (S3.5 — the Lightbend ``WrongType`` analog; ``path`` is empty there)."""

    def __init__(self, message: str, path: str) -> None:
        super().__init__(message)
        self.path = path


class NotResolvedError(ConfigError):
    """Raised when a getter is called on a Config whose value (or any transitive
    parent) contains an unresolved substitution placeholder. E12 decision 12.

    Detect with ``isinstance(err, NotResolvedError)``; it also passes
    ``isinstance(err, ConfigError)``.
    """

    def __init__(self, path: str) -> None:
        super().__init__(f'value at path "{path}" is not resolved (call resolve() first)', path)
