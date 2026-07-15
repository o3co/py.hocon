"""xx.hocon conformance harness (placeholder).

Once the parser lands, this module drives every fixture under
``tests/conformance/testdata/hocon/<group>/`` (synced by ``make testdata``)
through ``hocon.parse_file`` and compares the resolved tree against the
fixture's Lightbend-generated ``-expected.json``, using the ecosystem-bench
normalization rules (key order ignored, numbers by value, null keys dropped,
``.env`` sidecars loaded).
"""

import pytest

pytest.skip("parser not implemented yet — harness lands with stage 1", allow_module_level=True)
