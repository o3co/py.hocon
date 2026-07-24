"""YAML documents as HOCON config.

This is a HOCON library, not a YAML implementation, and the API keeps that
boundary. What this module owns is the decoded-tree -> HOCON step, exposed
directly as :func:`from_value`: root must be a mapping, ``${...}`` stays
literal, NaN and infinity are refused, a multi-document stream is refused. How
YAML *text* becomes a tree — whether ``010`` is 8 or 10, whether ``no`` is a
boolean — is the YAML library's answer, not a contract here.

:func:`parse` is a convenience front on ``ruamel.yaml``, which reads YAML 1.2
and so leaves ``no`` a string. PyYAML is YAML 1.1 and resolves ``no`` to
``False`` — the Norway problem — which is why it is not the default; a caller
who wants it decodes with it and hands the tree to :func:`from_value`::

    import yaml as pyyaml
    cfg = from_value(pyyaml.safe_load(src), "their-file.yml")

Needs ``pip install py.hocon[yaml]``.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from ..config import Config
from ..value_factory import from_map
from . import AdapterError
from ._tree import common_scalar, object_root

__all__ = ["parse", "parse_file", "from_value"]


def _loader() -> Any:
    try:
        from ruamel.yaml import YAML
    except ModuleNotFoundError:  # pragma: no cover - exercised by packaging, not tests
        raise AdapterError(
            "yaml: ruamel.yaml is not installed — `pip install py.hocon[yaml]`, "
            "or decode with your own library and call hocon.adapters.yaml.from_value"
        ) from None
    loader = YAML(typ="safe", pure=True)
    # Declared rather than defaulted: the same library returns 8 for `010` under
    # 1.1 and 10 under 1.2, and resolves `no` to False under 1.1.
    loader.version = (1, 2)
    return loader


def parse(input_text: str, origin_description: str | None = None) -> Config:
    """Read YAML text with this module's default library."""
    try:
        docs = list(_loader().load_all(io.StringIO(input_text)))
    except AdapterError:
        raise
    except Exception as e:
        raise AdapterError(f"yaml: {e}") from None

    if len(docs) > 1:
        raise AdapterError(
            "yaml: multi-document streams are not supported (spec F5.7); "
            "a config is one document"
        )
    return from_value(docs[0] if docs else None, origin_description)


def parse_file(path: str | Path) -> Config:
    """Read a YAML file, using its path as the origin description."""
    p = Path(path)
    return parse(p.read_text(encoding="utf-8"), str(p))


def from_value(doc: Any, origin_description: str | None = None) -> Config:
    """Build a Config from an already-decoded YAML tree, produced by whatever
    library and settings the caller chose. This is the tree-level boundary this
    module owns; :func:`parse` is just a default decoder in front of it.
    """
    # An empty document is the empty object, as an empty HOCON document is
    # (S3.1), rather than a root-type failure (spec F5.9).
    if doc is None:
        return from_map({}, origin_description)
    return from_map(object_root(doc, "yaml", _scalar), origin_description)


def _scalar(v: Any, at: str) -> Any:
    return common_scalar(v, at, "yaml")
