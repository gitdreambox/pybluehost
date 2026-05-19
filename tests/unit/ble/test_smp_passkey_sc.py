"""Tests for SMP SC Passkey Entry (Sub-Plan 3b-2)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pybluehost.ble.smp import SMPState
from pybluehost.core.address import BDAddress


def test_smp_state_passkey_sc_round_exists():
    assert SMPState.PASSKEY_SC_ROUND == 12
