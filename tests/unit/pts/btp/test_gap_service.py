"""GapService skeleton — registration + bound IutActions/tester accessors."""
import pytest
from unittest.mock import MagicMock

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.base import BtpServiceRegistry
from pybluehost.pts.btp.services.gap import GapService


class _FakeActions:
    """Minimal stand-in for pybluehost.pts.actions.IutActions."""
    local_address: bytes = bytes(6)


def test_gap_service_id_matches_constant():
    assert GapService.SERVICE_ID == op.SERVICE_GAP


def test_gap_service_registers_in_registry():
    reg = BtpServiceRegistry()
    actions = MagicMock()
    tester = MagicMock()
    svc = GapService(actions=actions, tester=tester)
    reg.register(svc)
    assert reg.get(op.SERVICE_GAP) is svc


def test_gap_service_stores_actions_and_tester():
    actions = MagicMock()
    tester = MagicMock()
    svc = GapService(actions=actions, tester=tester)
    assert svc._actions is actions
    assert svc._tester is tester


# ---------------------------------------------------------------------------
# T2: Read Controller Index List / Info / Reset
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_controller_index_list_returns_single_index_0():
    """PyBlueHost is single-controller; the list contains just index 0."""
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    status, data = await svc.dispatch(
        opcode=op.OP_GAP_READ_CONTROLLER_INDEX_LIST,
        controller_index=op.CONTROLLER_INDEX_NONE, data=b"",
    )
    assert status == op.BTP_STATUS_SUCCESS
    # Format: [num_controllers (u8), controller_indices...]
    assert data == bytes([1, 0])


@pytest.mark.asyncio
async def test_read_controller_info_returns_address_and_settings():
    """Layout (auto-pts): 6 BD_ADDR + 4 supported_settings + 4 current_settings
    + 3 class_of_device + 249 name + 11 short_name = 277 bytes."""
    actions = _FakeActions()
    actions.local_address = bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06])
    svc = GapService(actions=actions, tester=MagicMock())
    status, data = await svc.dispatch(
        opcode=op.OP_GAP_READ_CONTROLLER_INFO,
        controller_index=0, data=b"",
    )
    assert status == op.BTP_STATUS_SUCCESS
    # Sanity: minimum length, address bytes at expected offset.
    assert len(data) >= 14
    assert data[:6] == bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06])
    # supported_settings is u32 LE at offset 6.
    supported = int.from_bytes(data[6:10], "little")
    assert supported != 0    # we set some bits


@pytest.mark.asyncio
async def test_reset_clears_current_settings():
    """GAP RESET opcode (0x04) returns SUCCESS and zeroes per-session state."""
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    svc._current_settings = 0xDEAD
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_RESET, controller_index=0, data=b"",
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert svc._current_settings == 0
