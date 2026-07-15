"""Typed coercions for Config accessors: duration units, byte-size units, etc.

Mirrors ts.hocon ``src/coerce.ts``. Duration unit names are case-sensitive
(S19.8). Period coercion (S20.1–S20.4) follows rs.hocon, the only sibling
that implements it.
"""

from __future__ import annotations
