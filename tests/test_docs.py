"""Documentation consistency.

The README states facts that go stale on their own: the minimum Python version,
and "unreleased" markers left behind after the release that shipped the
behavior. Nothing else exercises them, so they only ever drift in one direction.
These tests recompute each from the artifact that actually decides it —
``docs/spec-compliance.md`` and ``pyproject.toml`` — and run in the release
workflow, so a stale README fails the cut.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Number of S-items in the shared spec checklist
# (xx.hocon/docs/spec-checklist.md). The compliance rates in the cross-impl
# matrix use it as the denominator, so a per-impl doc that drifted away from the
# checklist would silently change them.
SPEC_ITEM_TOTAL = 210

# An S-item heading: "- **S13a.10** Some rule — §Section (L123)". E-items
# (extra-spec conventions) use the same block shape but are not part of the
# checklist, so the heading pattern is what separates them.
_SPEC_ITEM_HEAD = re.compile(r"^\s*- \*\*(S[0-9A-Za-z._]+)\*\*")
_OTHER_HEAD = re.compile(r"^\s*- \*\*[0-9A-Za-z._]+\*\*")
_STATUS_LINE = re.compile(r"^\s*status:")

_GLYPHS = {"✅": "pass", "⚠️": "partial", "❌": "fail", "🤷": "unverified", "➖": "out_of_scope"}


def _read(relative: str) -> str:
    return (_REPO_ROOT / relative).read_text(encoding="utf-8")


def _find_one(text: str, pattern: re.Pattern[str], what: str) -> str:
    """Return the single capture group of ``pattern``.

    Fails the test when the pattern no longer matches — a doc rewrite that drops
    the claim must fail loudly rather than silently stop checking it.
    """
    matches = pattern.findall(text)
    if not matches:
        pytest.fail(
            f"{what} not found (pattern {pattern.pattern}); "
            "update the pattern if the doc was restructured"
        )
    if len(matches) > 1:
        # Two matches mean the doc states the claim twice, and this would
        # silently check whichever came first — so the pair can drift apart
        # while the test stays green. Make the ambiguity the failure.
        pytest.fail(
            f"{what} matched {len(matches)} times (pattern {pattern.pattern}); "
            f"the claim must appear once so there is one thing to pin: {matches}"
        )
    return matches[0]


def _count_compliance() -> dict[str, int]:
    """Tally the status glyph of every S-item block in docs/spec-compliance.md.

    Only the first ``status:`` line after an S-item heading counts: a block may
    carry sub-bullets, and the E-item blocks that follow the S-items must not be
    picked up.
    """
    counts = dict.fromkeys(_GLYPHS.values(), 0)
    in_spec_item = False

    for line in _read("docs/spec-compliance.md").splitlines():
        if _SPEC_ITEM_HEAD.match(line):
            in_spec_item = True
        elif _OTHER_HEAD.match(line):
            in_spec_item = False
        elif in_spec_item and _STATUS_LINE.match(line):
            in_spec_item = False
            for glyph, name in _GLYPHS.items():
                if glyph in line:
                    counts[name] += 1
                    break
            else:
                pytest.fail(f"status line carries no known glyph: {line.strip()}")
    return counts


def test_spec_compliance_covers_every_checklist_item() -> None:
    counts = _count_compliance()
    assert sum(counts.values()) == SPEC_ITEM_TOTAL, (
        "docs/spec-compliance.md item count — an item was added, dropped, "
        f"or its status line is malformed (tally: {counts})"
    )


def test_readme_python_version_matches_pyproject() -> None:
    required = _find_one(
        _read("pyproject.toml"), re.compile(r'requires-python = ">=(\d+\.\d+)"'), "requires-python"
    )
    claimed = _find_one(
        _read("README.md"), re.compile(r"Python (\d+\.\d+)\+"), "minimum Python version"
    )
    assert claimed == required, (
        f"README says Python {claimed}+, pyproject.toml requires >={required} — "
        "one of the two is wrong, and which way it hurts depends on the direction: "
        "a README claiming a lower minimum sends users to a version pip will refuse, "
        "and a README claiming a higher one turns away users who could install fine"
    )


def test_readme_marks_nothing_as_unreleased() -> None:
    offenders = [
        f"README.md:{n}: {line.strip()}"
        for n, line in enumerate(_read("README.md").splitlines(), start=1)
        if "(Unreleased)" in line
    ]
    assert offenders == [], "shipped behavior is still marked unreleased"
