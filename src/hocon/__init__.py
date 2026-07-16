"""py.hocon — full Lightbend HOCON specification-compliant parser for Python.

Sibling of o3co's go.hocon / ts.hocon / rs.hocon, sharing the same 3-stage
pipeline (Lexer → Parser → Resolver) and the same conformance corpus
(o3co/xx.hocon). The public surface mirrors ts.hocon ``src/index.ts`` with
rs.hocon's snake_case accessor naming.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .config import Config, Period
from .errors import (
    ConfigError,
    NotResolvedError,
    PackageLookupError,
    ParseError,
    ResolveError,
)
from .parse import parse, parse_file, parse_string
from .value import (
    HoconArray,
    HoconObject,
    HoconScalar,
    HoconValue,
    ScalarValueType,
    as_array,
    as_boolean,
    as_number,
    as_object,
    as_string,
    is_array,
    is_null,
    is_object,
    is_scalar,
)
from .value_factory import empty, from_map

# Derived from the installed distribution metadata (dist name `hocon-parser`,
# import name `hocon`) rather than hardcoded, so it tracks the tag-injected
# release version automatically. Falls back to "0.0.0" when running from an
# uninstalled source tree (e.g. PYTHONPATH=src).
try:
    __version__ = version("hocon-parser")
except PackageNotFoundError:  # pragma: no cover — uninstalled source tree
    __version__ = "0.0.0"

__all__ = [
    "Config",
    "ConfigError",
    "HoconArray",
    "HoconObject",
    "HoconScalar",
    "HoconValue",
    "NotResolvedError",
    "PackageLookupError",
    "ParseError",
    "Period",
    "ResolveError",
    "ScalarValueType",
    "__version__",
    "as_array",
    "as_boolean",
    "as_number",
    "as_object",
    "as_string",
    "empty",
    "from_map",
    "is_array",
    "is_null",
    "is_object",
    "is_scalar",
    "parse",
    "parse_file",
    "parse_string",
]
