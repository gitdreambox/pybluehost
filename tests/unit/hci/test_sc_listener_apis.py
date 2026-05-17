"""HCIController listener APIs for SC HCI events."""
from __future__ import annotations

import asyncio

from pybluehost.hci.constants import EventCode
from pybluehost.hci.controller import HCIController
from pybluehost.hci.packets import HCIEvent
from pybluehost.hci.virtual import VirtualController


async def test_on_io_capability_request_fires():
    vc, host_t = await VirtualController.create()
    hci = HCIController(transport=host_t, trace=None, command_timeout=2.0)
    seen: list = []
    hci.on_io_capability_request(lambda addr: seen.append(addr))
    try:
        await hci.initialize()
        # BT wire = little-endian; we test with LSB-first byte order
        params = b"\x06\x05\x04\x03\x02\x01"
        evt = HCIEvent(event_code=int(EventCode.IO_CAPABILITY_REQUEST), parameters=params)
        await vc._send_event_to_host(evt)
        await asyncio.sleep(0.05)
        assert len(seen) == 1
        # listener received BDAddress (big-endian per our convention)
        from pybluehost.core.address import BDAddress
        assert seen[0] == BDAddress(b"\x01\x02\x03\x04\x05\x06")
    finally:
        await host_t.close()


async def test_on_simple_pairing_complete_fires():
    vc, host_t = await VirtualController.create()
    hci = HCIController(transport=host_t, trace=None, command_timeout=2.0)
    seen: list = []
    hci.on_simple_pairing_complete(lambda status, addr: seen.append((status, addr)))
    try:
        await hci.initialize()
        params = b"\x00" + b"\x06\x05\x04\x03\x02\x01"
        evt = HCIEvent(event_code=int(EventCode.SIMPLE_PAIRING_COMPLETE), parameters=params)
        await vc._send_event_to_host(evt)
        await asyncio.sleep(0.05)
        assert seen and seen[0][0] == 0
    finally:
        await host_t.close()


async def test_on_link_key_notification_fires():
    vc, host_t = await VirtualController.create()
    hci = HCIController(transport=host_t, trace=None, command_timeout=2.0)
    seen: list = []
    hci.on_link_key_notification(lambda addr, key, key_type: seen.append((addr, key, key_type)))
    try:
        await hci.initialize()
        params = b"\x06\x05\x04\x03\x02\x01" + b"\xBB" * 16 + bytes([0x07])
        evt = HCIEvent(event_code=int(EventCode.LINK_KEY_NOTIFICATION), parameters=params)
        await vc._send_event_to_host(evt)
        await asyncio.sleep(0.05)
        assert len(seen) == 1
        _, key, key_type = seen[0]
        assert key == b"\xBB" * 16
        assert key_type == 0x07
    finally:
        await host_t.close()


async def test_on_user_confirmation_request_fires():
    vc, host_t = await VirtualController.create()
    hci = HCIController(transport=host_t, trace=None, command_timeout=2.0)
    seen: list = []
    hci.on_user_confirmation_request(lambda addr, numeric: seen.append((addr, numeric)))
    try:
        await hci.initialize()
        params = b"\x06\x05\x04\x03\x02\x01" + (0x12345678).to_bytes(4, "little")
        evt = HCIEvent(event_code=int(EventCode.USER_CONFIRMATION_REQUEST), parameters=params)
        await vc._send_event_to_host(evt)
        await asyncio.sleep(0.05)
        assert seen and seen[0][1] == 0x12345678
    finally:
        await host_t.close()


async def test_on_link_key_request_fires():
    vc, host_t = await VirtualController.create()
    hci = HCIController(transport=host_t, trace=None, command_timeout=2.0)
    seen: list = []
    hci.on_link_key_request(lambda addr: seen.append(addr))
    try:
        await hci.initialize()
        params = b"\x06\x05\x04\x03\x02\x01"
        evt = HCIEvent(event_code=int(EventCode.LINK_KEY_REQUEST), parameters=params)
        await vc._send_event_to_host(evt)
        await asyncio.sleep(0.05)
        assert len(seen) == 1
    finally:
        await host_t.close()
