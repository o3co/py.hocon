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
from ._internal.parser.ast import AstArray
from ._internal.parser.parser import parse_tokens
from ._internal.resolver.resolver import build_tree, contains_placeholders, resolve
from ._internal.resolver.types import PackageResolver, ResolveOptions
from .config import Config
from .errors import ConfigError
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
    array_root_origin: str | None = None,
) -> tuple[object, ResolveOptions]:
    tokens = tokenize(text)
    # S3.1 — HOCON.md L134-136: a document that does not begin with `[` or `{`
    # is parsed as if enclosed in `{}`, so an empty / whitespace-only /
    # comment-only document parses to the empty object. (L130-132 is the JSON
    # baseline, not HOCON-normative — see xx.hocon E10, corrected 2026-07-23.)
    ast = parse_tokens(tokens)
    # S3.5 — HOCON.md L989-991: an array-root document is valid syntax, but the
    # object-rooted Config API rejects it at the Config boundary with a TYPE
    # error, matching Lightbend's Parseable.forceParsedToObject
    # (ConfigException.WrongType "has type LIST rather than object at file
    # root"). The message carries the origin + the opening bracket's position.
    if isinstance(ast, AstArray):
        origin = origin_description or array_root_origin or "input"
        raise ConfigError(
            f"{origin}: {ast.pos.line}:{ast.pos.col}: document has type array "
            "rather than object at file root (HOCON.md L989-991); "
            "the Config API requires an object root",
            "",
        )
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
    return _parse_text(
        text,
        base_dir=base_dir,
        env=env,
        read_file=read_file,
        resolve_substitutions=resolve_substitutions,
        origin_description=origin_description,
        resolve_from=resolve_from,
        package_resolver=package_resolver,
        array_root_origin=None,
    )


def _parse_text(
    text: str,
    *,
    base_dir: str | None,
    env: dict[str, str] | None,
    read_file: _ReadFile | None,
    resolve_substitutions: bool,
    origin_description: str | None,
    resolve_from: _ResolveFrom,
    package_resolver: PackageResolver | None,
    array_root_origin: str | None,
) -> Config:
    """Internal worker behind ``parse`` / ``parse_file``.

    ``array_root_origin`` is a fallback origin used ONLY by the S3.5
    array-at-file-root diagnostic — ``parse_file`` passes its path here so
    that error names the file, without globally re-attributing resolver
    errors (which may originate inside included files) to the top-level file.
    """
    ast, opts = _build_resolve_context(
        text,
        base_dir,
        env,
        read_file,
        origin_description,
        resolve_from,
        package_resolver,
        array_root_origin,
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
    return _parse_text(
        text,
        base_dir=base_dir if base_dir is not None else os.path.dirname(resolved_path),
        env=env,
        read_file=reader,
        resolve_substitutions=resolve_substitutions,
        origin_description=origin_description,
        resolve_from=resolve_from,
        package_resolver=package_resolver,
        # S3.5-only origin fallback: the array-at-file-root diagnostic names
        # this file. Deliberately NOT a global origin_description default -
        # that would mis-attribute resolver errors originating inside
        # included files to the top-level file (Codex review, py.hocon).
        array_root_origin=resolved_path,
    )
