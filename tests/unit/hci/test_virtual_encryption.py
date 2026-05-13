"""VirtualController simulates HCI_LE_Start_Encryption -> Encryption_Change(success)."""
from __future__ import annotations

import asyncio

from pybluehost.hci.controller import HCIController
from pybluehost.hci.packets import (
    HCI_LE_LTK_Request_Reply_Command,
    HCI_LE_Start_Encryption_Command,
)
from pybluehost.hci.virtual import VirtualController


async def test_start_encryption_emits_encryption_change_success():
    vc, host_transport = await VirtualController.create()
    hci = HCIController(transport=host_transport, trace=None, command_timeout=5.0)
    seen: list[tuple[int, int, int]] = []
    hci.on_encryption_change(lambda h, s, e: seen.append((h, s, e)))
    try:
        await hci.initialize()
        await hci.send_command(
            HCI_LE_Start_Encryption_Command(
                connection_handle=0x0001,
                random_number=b"\x00" * 8,
                encrypted_diversifier=0,
                long_term_key=b"\xAA" * 16,
            )
        )
        await asyncio.sleep(0.05)
        assert seen, "no Encryption_Change event emitted"
        handle, status, enabled = seen[0]
        assert handle == 0x0001
        assert status == 0
        assert enabled == 1
    finally:
        await host_transport.close()


async def test_ltk_request_reply_completes_pairing_phase():
    """As-peripheral: VirtualController emits LE_LTK_Request, host replies, controller emits Encryption_Change(success)."""
    vc, host_transport = await VirtualController.create()
    hci = HCIController(transport=host_transport, trace=None, command_timeout=5.0)
    ltk_seen: list[tuple[int, bytes, int]] = []
    enc_seen: list[tuple[int, int, int]] = []
    hci.on_le_ltk_request(lambda h, r, e: ltk_seen.append((h, r, e)))
    hci.on_encryption_change(lambda h, s, e: enc_seen.append((h, s, e)))
    try:
        await hci.initialize()
        vc.simulate_le_ltk_request(handle=0x0002, rand=b"\x00" * 8, ediv=0)
        await asyncio.sleep(0.05)
        assert ltk_seen and ltk_seen[0][0] == 0x0002
        await hci.send_command(
            HCI_LE_LTK_Request_Reply_Command(
                connection_handle=0x0002,
                long_term_key=b"\xBB" * 16,
            )
        )
        await asyncio.sleep(0.05)
        assert enc_seen and enc_seen[0] == (0x0002, 0, 1)
    finally:
        await host_transport.close()
