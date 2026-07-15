"""Include loading (file / package). Mirrors ts.hocon ``src/internal/resolver/include-loader.ts``.

URL and classpath includes are unsupported by design across all siblings
(S14a.2 etc.). Node's ``require.resolve`` has no Python analogue, so
``include package("id", "file")`` resolves via a filesystem convention (search
``resolve_from`` / ``base_dir`` / CWD for ``<base>/id/file``) or a caller-supplied
``package_resolver`` hook. Sync path only (py.hocon has no async parse variant).
"""

from __future__ import annotations

import dataclasses
import os
import re
from collections.abc import Callable

from ...errors import PackageLookupError, ParseError, ResolveError
from ..lexer.lexer import tokenize
from ..parser.ast import AstNode
from ..parser.empty_check import assert_non_empty_document, has_content_tokens
from ..parser.parser import parse_tokens
from ..properties.properties import properties_to_hocon_value
from .types import PackageResolver, ResObj, ResolveOptions, make_res_obj
from .utils import (
    deep_merge_res_obj_into,
    hocon_value_to_res_obj,
    is_file_not_found_error,
)

__all__ = ["IncludeLoader"]


def _validate_package_file(file: str, identifier: str) -> None:
    """Validate the file argument of ``package("id", "file")`` per E11 decision 6."""
    if len(file) == 0:
        raise ParseError(
            f'include package("{identifier}", ...): file argument must be non-empty', 0, 0
        )
    if "\\" in file:
        raise ParseError(
            f'include package("{identifier}", "{file}"): backslash not allowed in file '
            f"argument (use forward slash)",
            0,
            0,
        )
    if file.startswith("/"):
        raise ParseError(
            f'include package("{identifier}", "{file}"): absolute path not allowed '
            f"in file argument",
            0,
            0,
        )
    if re.search(r"(?:^|/)\.\.?(?:/|$)", file):
        raise ParseError(
            f'include package("{identifier}", "{file}"): path traversal (. or ..) not '
            f"allowed in file argument",
            0,
            0,
        )
    if "//" in file:
        raise ParseError(
            f'include package("{identifier}", "{file}"): consecutive slashes not allowed '
            f"in file argument",
            0,
            0,
        )


def _validate_package_identifier(identifier: str) -> None:
    if len(identifier) == 0:
        raise ParseError("include package: identifier argument must be non-empty", 0, 0)


def _default_package_resolver(
    identifier: str,
    file: str,
    including_file: str | None,
    base_dir: str | None,
    resolve_from: object,
) -> str:
    """Filesystem-convention resolver: search candidate bases for ``id/file``.

    Node's module resolution is not available in Python, so this looks for
    ``<base>/<identifier>/<file>`` under, in priority order: ``resolve_from`` >
    ``base_dir`` > dir of ``including_file`` > CWD. Raises PackageLookupError on
    miss. Callers needing package-manager semantics pass a custom resolver.
    """
    if resolve_from:
        bases = (
            list(resolve_from)
            if isinstance(resolve_from, (list, tuple))
            else [str(resolve_from)]
        )
    elif base_dir:
        bases = [base_dir]
    elif including_file:
        bases = [os.path.dirname(including_file)]
    else:
        bases = [os.getcwd()]

    for base in bases:
        candidate = os.path.join(base, identifier, file)
        if os.path.isfile(candidate):
            # E11 decision 5: case-sensitive basename check.
            expected_basename = file.split("/")[-1]
            if os.path.basename(candidate) != expected_basename:
                raise PackageLookupError(
                    f'include package("{identifier}", "{file}"): case mismatch',
                    identifier,
                    file,
                    0,
                    0,
                )
            return candidate

    raise PackageLookupError(
        f'include package("{identifier}", "{file}"): module not found '
        f"(searched: {', '.join(bases)})",
        identifier,
        file,
        0,
        0,
    )


def _unset_build(_ast: AstNode, _opts: ResolveOptions) -> ResObj:  # pragma: no cover
    raise RuntimeError("IncludeLoader.on_build_res_obj was not set by StructureBuilder")


class IncludeLoader:
    def __init__(self, opts: ResolveOptions) -> None:
        self.opts = opts
        # Set by StructureBuilder to delegate back to build() (avoids a cycle).
        self.on_build_res_obj: Callable[[AstNode, ResolveOptions], ResObj] = _unset_build

    def _resolve_include_path(
        self, include_path: str, base_dir: str | None, is_file: bool
    ) -> str:
        if is_file:
            return os.path.abspath(include_path)
        if base_dir:
            return os.path.abspath(os.path.join(base_dir, include_path))
        return os.path.abspath(include_path)

    def load(self, include_path: str, required: bool, is_file: bool = False) -> ResObj:
        base_dir = self.opts.base_dir
        include_stack = self.opts.include_stack
        abs_path = self._resolve_include_path(include_path, base_dir, is_file)

        if abs_path in include_stack:
            raise ResolveError(f"circular include: {abs_path}", abs_path, 0, 0)
        if len(include_stack) >= 50:
            raise ResolveError("include depth limit exceeded (max 50)", include_path, 0, 0)

        has_explicit_ext = abs_path.endswith((".conf", ".json", ".properties"))

        if has_explicit_ext:
            result = self._load_single(abs_path)
            if result is not None:
                return result
            if required:
                raise ResolveError(
                    f"required include file not found: {include_path}", include_path, 0, 0
                )
            return make_res_obj()

        # No extension: merge all found extensions (.properties, .json, .conf; last wins).
        merged = make_res_obj()
        found_any = False
        for ext in (".properties", ".json", ".conf"):
            obj = self._load_single(f"{abs_path}{ext}")
            if obj is not None:
                deep_merge_res_obj_into(merged, obj, [])
                found_any = True

        if not found_any and required:
            raise ResolveError(
                f"required include file not found: {include_path}", include_path, 0, 0
            )
        return merged

    def load_package(self, identifier: str, file: str, _required: bool) -> ResObj:
        _validate_package_identifier(identifier)
        _validate_package_file(file, identifier)

        include_stack = self.opts.include_stack
        cycle_key = f'package\x00{identifier}\x00{file}'

        if cycle_key in include_stack:
            raise ResolveError(
                f'circular include: package("{identifier}", "{file}")',
                f"{identifier}/{file}",
                0,
                0,
            )
        if len(include_stack) >= 50:
            raise ResolveError(
                "include depth limit exceeded (max 50)", f"{identifier}/{file}", 0, 0
            )

        resolver: PackageResolver = self.opts.package_resolver or (
            lambda id_, f, including_file, b_dir: _default_package_resolver(
                id_, f, including_file, b_dir, self.opts.resolve_from
            )
        )
        resolved_path = resolver(identifier, file, None, self.opts.base_dir)

        content = self.opts.read_file_sync(resolved_path)
        # Empty content (zero bytes) is valid for package includes (ipk08) → {}.
        if len(content) == 0:
            return make_res_obj()

        tokens = tokenize(content)
        assert_non_empty_document(tokens, resolved_path)
        ast = parse_tokens(tokens)
        return self.on_build_res_obj(
            ast,
            dataclasses.replace(
                self.opts,
                base_dir=os.path.dirname(resolved_path),
                include_stack=[*include_stack, cycle_key],
            ),
        )

    def _load_single(self, candidate: str) -> ResObj | None:
        include_stack = self.opts.include_stack
        if candidate in include_stack:
            raise ResolveError(f"circular include: {candidate}", candidate, 0, 0)

        try:
            content = self.opts.read_file_sync(candidate)
        except Exception as e:
            if is_file_not_found_error(e):
                return None
            raise

        if candidate.endswith(".properties"):
            return hocon_value_to_res_obj(properties_to_hocon_value(content))

        tokens = tokenize(content)
        # Lightbend-compat carve-out (#105): empty/comment-only included file → {}.
        if not has_content_tokens(tokens):
            return make_res_obj()
        ast = parse_tokens(tokens)
        return self.on_build_res_obj(
            ast,
            dataclasses.replace(
                self.opts,
                base_dir=os.path.dirname(candidate),
                include_stack=[*include_stack, candidate],
            ),
        )
