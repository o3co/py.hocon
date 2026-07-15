"""py.hocon — full Lightbend HOCON specification-compliant parser for Python.

Sibling of o3co's go.hocon / ts.hocon / rs.hocon, sharing the same 3-stage
pipeline (Lexer → Parser → Resolver) and the same conformance corpus
(o3co/xx.hocon). The public surface mirrors ts.hocon ``src/index.ts`` with
rs.hocon's snake_case accessor naming.
"""

from __future__ import annotations

from .config import Config
from .errors import (
    ConfigError,
    NotResolvedError,
    PackageLookupError,
    ParseError,
    ResolveError,
)
from .parse import parse, parse_file, parse_string

__version__ = "0.0.0"

__all__ = [
    "Config",
    "ConfigError",
    "NotResolvedError",
    "PackageLookupError",
    "ParseError",
    "ResolveError",
    "__version__",
    "parse",
    "parse_file",
    "parse_string",
]
