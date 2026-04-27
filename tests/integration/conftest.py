"""Fixtures for HCI+L2CAP integration tests using VirtualController."""
from __future__ import annotations

import pytest

from pybluehost.core.address import BDAddress
from pybluehost.core.trace import TraceSystem
from pybluehost.hci.virtual import VirtualController
from pybluehost.hci.controller import HCIController
from pybluehost.l2cap.manager import L2CAPManager


@pytest.fixture
async def vc_a() -> VirtualController:
    return VirtualController(address=BDAddress.from_string("AA:BB:CC:DD:EE:01"))


@pytest.fixture
async def vc_b() -> VirtualController:
    return VirtualController(address=BDAddress.from_string("AA:BB:CC:DD:EE:02"))


@pytest.fixture
async def hci_with_vc(vc_a: VirtualController) -> HCIController:
    """HCIController wired to a VirtualController host transport."""
    _vc, host_t = await VirtualController.create(address=vc_a._address)

    trace = TraceSystem()
    hci = HCIController(transport=host_t, trace=trace)
    await hci.initialize()
    return hci


@pytest.fixture
async def l2cap_with_hci(hci_with_vc: HCIController) -> L2CAPManager:
    """L2CAPManager connected to a real HCIController (via VC)."""
    l2cap = L2CAPManager(hci=hci_with_vc)
    return l2cap
