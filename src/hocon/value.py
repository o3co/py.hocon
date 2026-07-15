"""Value model for parsed/resolved HOCON trees.

Mirrors ts.hocon ``src/value.ts`` (``HoconValue`` and the ``as_*`` / ``is_*``
helpers). TODO(port): define the value model first — it is the contract
between all three pipeline stages and the ``Config`` accessors.
"""

from __future__ import annotations
