"""SBC ETSI byte-exact reference vector validation.

DEFERRED in Plan A.1 — requires bit-exact ETSI test vectors (a2dp-tests/
golden frames) that are not yet vendored into the repo. Currently this module
is a scaffold: the sentinel test asserts that the fixtures path is missing,
making it obvious in CI when fixtures get added (the sentinel will fail,
forcing this file to be updated with real byte-exact comparisons).

Once fixtures land under tests/unit/audio/codec/fixtures/sbc/ (PCM input +
expected SBC frame bytes), expand this file to:
1. Load each (PCM, expected) pair.
2. Run SBCEncoder with the matching config from a sidecar JSON.
3. assert frame == expected (byte-exact).
"""
from __future__ import annotations

from pathlib import Path

import pytest

_FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "sbc"


@pytest.mark.skipif(
    not _FIXTURES_ROOT.exists(),
    reason="ETSI byte-exact fixtures not yet vendored (Plan A.1 Task 7 deferred)",
)
def test_etsi_byte_exact_placeholder():
    # When fixtures appear, this test will run instead of skipping; expand
    # to load pairs and run SBCEncoder per the docstring above.
    pytest.fail("ETSI fixtures present — expand this test to compare bytes")


def test_sentinel_fixtures_not_yet_present():
    """Sentinel: confirms we are still in the 'deferred' state.
    Delete this test and implement test_etsi_byte_exact_placeholder once
    real ETSI vectors are added under tests/unit/audio/codec/fixtures/sbc/."""
    assert not _FIXTURES_ROOT.exists(), (
        "ETSI fixtures directory appeared — Plan A.1 Task 7 is now unblocked. "
        "Replace the placeholder test with real byte-exact comparisons and "
        "delete this sentinel."
    )
