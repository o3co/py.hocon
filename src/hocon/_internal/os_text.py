"""Recognizing text the OS handed over undecoded (spec F1.9).

Python does not fail when a process-environment entry is not valid UTF-8: it
decodes with the ``surrogateescape`` handler, so each undecodable byte survives
as a lone surrogate in U+DC80–U+DCFF. That keeps iteration alive — an entry the
config never mentions can never abort a parse, which is what F1.9 asks for
first — but the resulting ``str`` is not text. Encoding it back to UTF-8 raises
``UnicodeEncodeError``, typically in some serializer far away from the parser
that admitted it, which is exactly the fail-at-a-distance outcome F1.9 exists
to prevent.

So the bytes are detectable, and what to do about them depends on whether the
caller asked for that variable: a substitution lookup treats it as absent
(F1.9a), while a bulk mount of a prefix that matches it is an error (F1.9b).
"""

from __future__ import annotations

__all__ = ["is_undecodable"]

_SURROGATEESCAPE_LO = 0xDC80
_SURROGATEESCAPE_HI = 0xDCFF


def is_undecodable(s: str) -> bool:
    """True when ``s`` carries a byte ``surrogateescape`` could not decode."""
    return any(_SURROGATEESCAPE_LO <= ord(ch) <= _SURROGATEESCAPE_HI for ch in s)
