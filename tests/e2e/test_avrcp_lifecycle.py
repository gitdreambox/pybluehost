"""AVRCP controller ↔ target end-to-end via VirtualClassicLink."""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from pybluehost.classic.avrcp.constants import AVRCPEventID, AVRCPOperationID, AVRCPPlayStatus
from pybluehost.hci.virtual_classic_link import VirtualClassicLink
from pybluehost.profiles.classic import AVRCPController, AVRCPTarget

from tests.e2e._helpers import (
    classic_discover_and_pair_jw, disconnect_classic_and_wait, e2e_timeout,
)


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def avrcp_pair(stack, peer_stack, transport_mode):
    if transport_mode != "virtual":
        pytest.skip("AVRCP real-hardware loopback is part of A.6 runbook")
    await peer_stack.gap.classic_discoverability.set_connectable(True)
    await peer_stack.gap.classic_discoverability.set_discoverable(True)
    link = VirtualClassicLink(
        central=stack._virtual_controller,
        peripheral=peer_stack._virtual_controller,
        central_address=stack._local_address,
        peripheral_address=peer_stack._local_address,
        page_timeout_seconds=0.5,
    )
    link.attach()
    try:
        yield stack, peer_stack, link
    finally:
        try:
            await link.disconnect()
        except Exception:
            pass


async def test_avrcp_controller_pass_through_and_notify(avrcp_pair, transport_mode):
    """Controller sends PLAY/PAUSE/VOL_UP; target records each. Then
    controller subscribes to PLAYBACK_STATUS_CHANGED and receives INTERIM
    response with the target's current status."""
    stack_ctrl, stack_tgt, _link = avrcp_pair
    timeout = e2e_timeout(transport_mode, virtual=5.0)

    received_commands: list[tuple[int, bool]] = []

    async def on_pt(cmd) -> bool:
        received_commands.append((cmd.operation_id, cmd.pressed))
        return True

    async def on_notify_register(event_id: int) -> bytes:
        if event_id == AVRCPEventID.PLAYBACK_STATUS_CHANGED:
            return bytes([AVRCPPlayStatus.PLAYING])
        return b"\x00"

    target = AVRCPTarget(
        stack=stack_tgt,
        on_pass_through=on_pt,
        on_notification_register=on_notify_register,
    )
    target.register()
    controller = AVRCPController(stack=stack_ctrl)
    controller.register()

    handle = None
    try:
        handle = await classic_discover_and_pair_jw(
            stack_ctrl, stack_tgt._local_address,
            scan_timeout=timeout, pair_timeout=timeout,
        )
        session = await controller.connect(handle=handle)
        await asyncio.sleep(0.1)

        assert await session.play()
        assert await session.pause()
        assert await session.volume_up()

        # Each play/pause/vol_up = 2 frames (pressed + released).
        op_ids = {cmd[0] for cmd in received_commands}
        assert AVRCPOperationID.PLAY in op_ids
        assert AVRCPOperationID.PAUSE in op_ids
        assert AVRCPOperationID.VOLUME_UP in op_ids
        assert len(received_commands) == 6

        # Notification subscription.
        status_payload = await session.register_notification(
            AVRCPEventID.PLAYBACK_STATUS_CHANGED,
        )
        assert status_payload == bytes([AVRCPPlayStatus.PLAYING])

        await session.close()
    finally:
        if handle is not None:
            try:
                await disconnect_classic_and_wait(stack_ctrl, handle, timeout=timeout)
            except Exception:
                pass
