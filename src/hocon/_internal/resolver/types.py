"""Resolver options shared by the build and resolve phases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

__all__ = ["PackageResolver", "ResolveOptions"]

PackageResolver = Callable[[str, str, str | None, str | None], str]


def _no_files(_path: str) -> str:
    raise RuntimeError("no file reader configured")


@dataclass
class ResolveOptions:
    env: dict[str, str] = field(default_factory=dict)
    base_dir: str | None = None
    read_file_sync: Callable[[str], str] = _no_files
    include_stack: list[str] = field(default_factory=list)
    # Override the starting dir(s) for the default package resolver.
    resolve_from: str | list[str] | None = None
    package_resolver: PackageResolver | None = None
    # When False, environment variables are not consulted (§7.2 step 3).
    use_system_environment: bool | None = None
    # When True, an undefined required substitution stays unresolved (§8.2).
    allow_unresolved: bool | None = None
    # Human-readable origin for error messages.
    origin_description: str | None = None
