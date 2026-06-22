"""GapService skeleton — registration + bound IutActions/tester accessors."""
import pytest
from unittest.mock import MagicMock

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.base import BtpServiceRegistry
from pybluehost.pts.btp.services.gap import GapService


class _FakeActions:
    """Records calls to async IutActions methods."""
    local_address: bytes = bytes(6)

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def advertise(self, *, adv_type=None, data=None):
        self.calls.append(("advertise", {"adv_type": adv_type, "data": data}))

    async def stop_advertising(self):
        self.calls.append(("stop_advertising", {}))


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


# ---------------------------------------------------------------------------
# T3: Set Powered / Connectable / Fast Connectable / Discoverable / Bondable
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("opcode,bit", [
    (op.OP_GAP_SET_POWERED, 0),
    (op.OP_GAP_SET_CONNECTABLE, 1),
    (op.OP_GAP_SET_FAST_CONNECTABLE, 2),
    (op.OP_GAP_SET_DISCOVERABLE, 3),
    (op.OP_GAP_SET_BONDABLE, 4),
])
@pytest.mark.asyncio
async def test_set_flag_updates_current_settings_bit(opcode, bit):
    from unittest.mock import MagicMock
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    status, data = await svc.dispatch(opcode=opcode, controller_index=0,
                                       data=bytes([1]))
    assert status == op.BTP_STATUS_SUCCESS
    current = int.from_bytes(data, "little")
    assert (current >> bit) & 1


@pytest.mark.asyncio
async def test_set_powered_off_clears_bit():
    from unittest.mock import MagicMock
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    await svc.dispatch(opcode=op.OP_GAP_SET_POWERED, controller_index=0, data=bytes([1]))
    _, data = await svc.dispatch(opcode=op.OP_GAP_SET_POWERED, controller_index=0, data=bytes([0]))
    current = int.from_bytes(data, "little")
    assert not (current & 0x01)


@pytest.mark.asyncio
async def test_set_command_rejects_empty_data():
    from unittest.mock import MagicMock
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    status, _ = await svc.dispatch(opcode=op.OP_GAP_SET_POWERED,
                                    controller_index=0, data=b"")
    assert status == op.BTP_STATUS_FAILED


# ---------------------------------------------------------------------------
# T4: Start / Stop Advertising
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_advertising_decodes_body_and_calls_actions():
    """Upstream layout: adv_len(1), scan_len(1), adv_data, scan_rsp, duration(4), own_addr_type(1)."""
    from unittest.mock import MagicMock
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=MagicMock())
    adv_data = bytes.fromhex("0201060807090A0B0C0D0E")    # 11 bytes
    scan_rsp = bytes.fromhex("030819")                    # 3 bytes
    body = (
        bytes([len(adv_data), len(scan_rsp)])
        + adv_data + scan_rsp
        + (0).to_bytes(4, "little")
        + bytes([op.GAP_ADDR_TYPE_PUBLIC])
    )
    status, data = await svc.dispatch(
        opcode=op.OP_GAP_START_ADVERTISING, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    # Response = updated current_settings; advertising bit 9 should be set.
    settings = int.from_bytes(data, "little")
    assert settings & (1 << 9)
    # IutActions.advertise was invoked with the adv_data.
    assert actions.calls[0][0] == "advertise"
    assert actions.calls[0][1].get("data") == adv_data


@pytest.mark.asyncio
async def test_stop_advertising_clears_bit_and_calls_actions():
    from unittest.mock import MagicMock
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=MagicMock())
    svc._current_settings |= (1 << 9)        # pretend advertising is on
    status, data = await svc.dispatch(
        opcode=op.OP_GAP_STOP_ADVERTISING, controller_index=0, data=b"",
    )
    assert status == op.BTP_STATUS_SUCCESS
    settings = int.from_bytes(data, "little")
    assert not (settings & (1 << 9))
    assert any(c[0] == "stop_advertising" for c in actions.calls)


@pytest.mark.asyncio
async def test_start_advertising_truncated_body_fails():
    from unittest.mock import MagicMock
    svc = GapService(actions=_FakeActions(), tester=MagicMock())
    # Body says adv_len=10, scan_len=0, but only 3 bytes of adv_data provided.
    body = bytes([10, 0]) + b"\x01\x02\x03"
    status, _ = await svc.dispatch(
        opcode=op.OP_GAP_START_ADVERTISING, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED
