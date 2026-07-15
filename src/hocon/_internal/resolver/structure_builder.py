"""Pass 1: builds a ResObj tree from AST nodes.

Mirrors ts.hocon ``src/internal/resolver/structure-builder.ts`` (sync path only;
py.hocon has no async parse variant). Encapsulates structure building, include
loading, and substitution-path relativization for nested includes.
"""

from __future__ import annotations

from ...errors import ResolveError
from ...value import HoconArray, HoconScalar
from ..lexer.token import Segment
from ..parser.ast import (
    AstArray,
    AstConcat,
    AstField,
    AstInclude,
    AstNode,
    AstObject,
    AstScalar,
    AstSubst,
)
from .fold_self_ref import (
    contains_self_ref,
    fold_nested_self_refs,
    fold_or_skip_prior,
    string_segments_to_key,
)
from .include_loader import IncludeLoader
from .types import (
    ConcatPlaceholder,
    ResObj,
    ResolveOptions,
    ResolverValue,
    SubstPlaceholder,
    is_concat,
    is_res_obj,
    is_subst,
    make_res_obj,
    separator_values,
)
from .utils import deep_merge_res_obj_into

__all__ = ["StructureBuilder"]


class StructureBuilder:
    def __init__(self, opts: ResolveOptions) -> None:
        self.loader = IncludeLoader(opts)
        self.loader.on_build_res_obj = lambda a, o: StructureBuilder(o).build(a)

    def build(self, ast: AstNode, path_prefix: list[str] | None = None) -> ResObj:
        if path_prefix is None:
            path_prefix = []
        if not isinstance(ast, AstObject):
            raise ResolveError("root AST must be an object", "", ast.pos.line, ast.pos.col)
        obj = make_res_obj()
        for fld in ast.fields:
            self._apply_field(obj, fld, path_prefix)
        return obj

    def _apply_field(self, obj: ResObj, field: AstField, path_prefix: list[str]) -> None:
        # include directive: key empty, value is include node.
        if len(field.key) == 0 and isinstance(field.value, AstInclude):
            qualifier = field.value.qualifier
            path = field.value.path
            required = field.value.required
            if qualifier.kind == "package":
                included = self.loader.load_package(qualifier.identifier, path, required)
            else:
                included = self.loader.load(path, required, qualifier.kind == "file")
            if len(path_prefix) > 0:
                self._relativize_res_obj(included, path_prefix)
            deep_merge_res_obj_into(obj, included, path_prefix)
            return

        if len(field.key) == 0:
            return
        head, tail = field.key[0], field.key[1:]

        if len(tail) > 0:
            # Nested key: server.host = "x" → synthetic object AST.
            synthetic_ast = AstObject(
                [AstField(tail, field.value, field.append, field.pos)], field.pos
            )
            self._apply_field(
                obj, AstField([head], synthetic_ast, False, field.pos), path_prefix
            )
            return

        child_prefix = [*path_prefix, head]
        full_key = string_segments_to_key(child_prefix)

        if field.append:
            # S13b.2: `a += b` ≡ `a = ${?a} [b]` (HOCON.md L732). Desugar and
            # re-dispatch so += flows through the chained-self-ref machinery.
            synthetic = self._desugar_append(field, child_prefix)
            self._apply_field(obj, synthetic, path_prefix)
            return

        existing = obj.fields.get(head)
        new_val = self._ast_to_resolver_value(field.value, child_prefix)

        # go.hocon#134: a non-self-referential assignment is a *reset*.
        if not contains_self_ref(new_val, full_key):
            obj.reset_keys.add(head)

        # Save prior value for self-referential substitution resolution.
        if existing is not None:
            old_prior = obj.prior_values.get(head)
            prior_input = (
                fold_nested_self_refs(existing, child_prefix)
                if is_res_obj(existing)
                else existing
            )
            prior = fold_or_skip_prior(prior_input, full_key, old_prior)
            if prior is not None:
                obj.prior_values[head] = prior

        # Deep merge if both are ResObj.
        if existing is not None and is_res_obj(existing) and is_res_obj(new_val):
            deep_merge_res_obj_into(existing, new_val, child_prefix)
            return

        obj.fields[head] = new_val

    def _desugar_append(self, field: AstField, child_prefix: list[str]) -> AstField:
        """Build the ``key = ${?fullkey} [value]`` field that ``key += value``
        desugars to (S13b.2, HOCON.md L732)."""
        segments = [Segment(text, field.pos.line, field.pos.col) for text in child_prefix]
        subst = AstSubst(segments, True, False, field.pos)
        elem_array = AstArray([field.value], field.pos)
        synthetic = AstConcat([subst, elem_array], field.pos)
        return AstField(field.key, synthetic, False, field.pos)

    def _ast_to_resolver_value(self, ast: AstNode, path_prefix: list[str]) -> ResolverValue:
        if isinstance(ast, AstScalar):
            sv = HoconScalar(ast.raw, ast.value_type)
            if ast.separator:
                separator_values.add(sv)
            return sv
        if isinstance(ast, AstArray):
            return HoconArray(
                [self._ast_to_resolver_value(i, path_prefix) for i in ast.items]  # type: ignore[misc]
            )
        if isinstance(ast, AstObject):
            return self.build(ast, path_prefix)
        if isinstance(ast, AstSubst):
            return SubstPlaceholder(
                ast.segments, ast.optional, False, ast.list_suffix, ast.pos.line, ast.pos.col, 0
            )
        if isinstance(ast, AstConcat):
            return ConcatPlaceholder(
                [self._ast_to_resolver_value(n, path_prefix) for n in ast.nodes],
                ast.pos.line,
                ast.pos.col,
            )
        # AstInclude — handled by _apply_field; should not reach here.
        return HoconScalar("null", "null")

    # ---- Relativize substitution paths for nested includes ----

    def _relativize_subst_paths(self, val: ResolverValue, prefix_segments: list[str]) -> None:
        if is_subst(val):
            prefix_as_segments = [Segment(text, 0, 0) for text in prefix_segments]
            val.segments = [*prefix_as_segments, *val.segments]
            val.prefix_len += len(prefix_segments)
            return
        if is_concat(val):
            for node in val.nodes:
                self._relativize_subst_paths(node, prefix_segments)
            return
        if is_res_obj(val):
            self._relativize_res_obj(val, prefix_segments)
            return
        if isinstance(val, HoconArray):
            for item in val.items:
                self._relativize_subst_paths(item, prefix_segments)

    def _relativize_res_obj(self, obj: ResObj, prefix_segments: list[str]) -> None:
        for val in obj.fields.values():
            self._relativize_subst_paths(val, prefix_segments)
        for val in obj.prior_values.values():
            self._relativize_subst_paths(val, prefix_segments)
