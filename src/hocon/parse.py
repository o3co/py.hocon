"""Public parse entry points.

Mirrors ts.hocon ``src/parse.ts`` (``parse`` / ``parseFile`` / ``parseString``
and the deferred ``resolveSubstitutions=False`` path). Python has no sync/async
split at this layer, so the ``*Async`` variants have no counterpart. Options are
keyword arguments rather than a TS options object.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from ._internal.lexer.lexer import tokenize
from ._internal.parser.empty_check import assert_non_empty_document
from ._internal.parser.parser import parse_tokens
from ._internal.resolver.resolver import build_tree, contains_placeholders, resolve
from ._internal.resolver.types import PackageResolver, ResolveOptions
from .config import Config
from .value import HoconObject

__all__ = ["parse", "parse_file", "parse_string"]

_ReadFile = Callable[[str], str]
_ResolveFrom = str | list[str] | None


def _default_read_file_sync(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _get_env(env: dict[str, str] | None) -> dict[str, str]:
    return env if env is not None else dict(os.environ)


def _build_resolve_context(
    text: str,
    base_dir: str | None,
    env: dict[str, str] | None,
    read_file: _ReadFile | None,
    origin_description: str | None,
    resolve_from: _ResolveFrom,
    package_resolver: PackageResolver | None,
) -> tuple[object, ResolveOptions]:
    tokens = tokenize(text)
    # S3.1 — HOCON.md L130: empty / whitespace-only / comment-only files are invalid.
    assert_non_empty_document(tokens, "input")
    ast = parse_tokens(tokens)
    opts = ResolveOptions(
        env=_get_env(env),
        base_dir=base_dir,
        read_file_sync=read_file or _default_read_file_sync,
        resolve_from=resolve_from,
        package_resolver=package_resolver,
        origin_description=origin_description,
    )
    return ast, opts


def parse(
    text: str,
    *,
    base_dir: str | None = None,
    env: dict[str, str] | None = None,
    read_file: _ReadFile | None = None,
    resolve_substitutions: bool = True,
    origin_description: str | None = None,
    resolve_from: _ResolveFrom = None,
    package_resolver: PackageResolver | None = None,
) -> Config:
    """Parse HOCON source text. Fully resolves by default; pass
    ``resolve_substitutions=False`` to return an unresolved Config with
    substitution placeholders intact (complete later with ``Config.resolve``)."""
    ast, opts = _build_resolve_context(
        text, base_dir, env, read_file, origin_description, resolve_from, package_resolver
    )
    if resolve_substitutions:
        value = resolve(ast, opts)  # type: ignore[arg-type]
        if not isinstance(value, HoconObject):
            raise RuntimeError("resolved value is not an object")
        return Config._from_resolved_value(value, origin_description)
    tree = build_tree(ast, opts)  # type: ignore[arg-type]
    has_placeholders = contains_placeholders(tree)
    return Config._from_unresolved_res_obj(
        tree,
        parse_base_dir=base_dir,
        origin_description=origin_description,
        resolved=not has_placeholders,
        resolve_opts=opts,
    )


# Lightbend-aligned alias for parse(). Produces a fully resolved Config.
parse_string = parse


def parse_file(
    path: str,
    *,
    base_dir: str | None = None,
    env: dict[str, str] | None = None,
    read_file: _ReadFile | None = None,
    resolve_substitutions: bool = True,
    origin_description: str | None = None,
    resolve_from: _ResolveFrom = None,
    package_resolver: PackageResolver | None = None,
) -> Config:
    """Parse a HOCON file, resolving relative includes against its directory."""
    resolved_path = os.path.abspath(path)
    reader = read_file or _default_read_file_sync
    text = reader(resolved_path)
    return parse(
        text,
        base_dir=base_dir if base_dir is not None else os.path.dirname(resolved_path),
        env=env,
        read_file=reader,
        resolve_substitutions=resolve_substitutions,
        origin_description=origin_description,
        resolve_from=resolve_from,
        package_resolver=package_resolver,
    )
