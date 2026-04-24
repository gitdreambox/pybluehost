"""Fixtures for HCI+L2CAP integration tests using VirtualController."""
from __future__ import annotations

import pytest

from pybluehost.core.address import BDAddress
from pybluehost.core.trace import TraceSystem
from pybluehost.hci.virtual import VirtualController
from pybluehost.hci.controller import HCIController
from pybluehost.l2cap.manager import L2CAPManager
from pybluehost.transport.loopback import LoopbackTransport


@pytest.fixture
async def vc_a() -> VirtualController:
    return VirtualController(address=BDAddress.from_string("AA:BB:CC:DD:EE:01"))


@pytest.fixture
async def vc_b() -> VirtualController:
    return VirtualController(address=BDAddress.from_string("AA:BB:CC:DD:EE:02"))


@pytest.fixture
async def hci_with_vc(vc_a: VirtualController) -> HCIController:
    """HCIController wired to a VirtualController via LoopbackTransport."""
    host_t, ctrl_t = LoopbackTransport.pair()

    class _VCSink:
        async def on_transport_data(self, data: bytes) -> None:
            response = await vc_a.process(data)
            if response is not None and host_t._sink is not None:
                await host_t._sink.on_transport_data(response)

    ctrl_t.set_sink(_VCSink())
    await host_t.open()
    await ctrl_t.open()

    trace = TraceSystem()
    hci = HCIController(transport=host_t, trace=trace)
    await hci.initialize()
    return hci


@pytest.fixture
async def l2cap_with_hci(hci_with_vc: HCIController) -> L2CAPManager:
    """L2CAPManager connected to a real HCIController (via VC)."""
    l2cap = L2CAPManager(hci=hci_with_vc)
    return l2cap
