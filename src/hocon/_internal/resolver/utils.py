"""Small helpers shared by the resolver modules."""

from __future__ import annotations

import errno
import re

__all__ = ["is_file_not_found_error", "path_to_key"]

_NON_BARE_KEY = re.compile(r"[^a-zA-Z0-9\-_]")


def path_to_key(path: tuple[str, ...]) -> str:
    """A path as HOCON path text, for error messages: a segment that is empty
    or not a bare key is quoted."""
    parts = []
    for t in path:
        if t == "" or _NON_BARE_KEY.search(t):
            parts.append('"' + t.replace("\\", "\\\\").replace('"', '\\"') + '"')
        else:
            parts.append(t)
    return ".".join(parts)


def is_file_not_found_error(e: BaseException) -> bool:
    if isinstance(e, FileNotFoundError):
        return True
    if isinstance(e, OSError) and e.errno == errno.ENOENT:
        return True
    msg = str(e).lower()
    return "not found" in msg or "no such file" in msg or "enoent" in msg
