"""BTP PADV primitives that have to translate between two different conventions.

Both commands here take a flag byte from auto-pts whose bit meanings do not
line up with the HCI field they end up in. Getting the mapping wrong is silent
— the command is accepted (status 0x00) and the controller just does something
else, so the case times out instead of erroring.
"""
import pytest

from pybluehost.core.address import AddressType, BDAddress
from pybluehost.pts.actions import ConnInfo, IutActions


class _FakePeriodicAdvertising:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.sync_handle = 0x1234

    async def set_sync_transfer_parameters(self, **kwargs):
        self.calls.append(("set_sync_transfer_parameters", kwargs))

    async def sync_transfer(self, **kwargs):
        self.calls.append(("sync_transfer", kwargs))

    async def set_info_transfer(self, **kwargs):
        self.calls.append(("set_info_transfer", kwargs))


class _FakeGap:
    def __init__(self):
        self.periodic_advertising = _FakePeriodicAdvertising()


class _FakeStack:
    def __init__(self):
        self.gap = _FakeGap()
        self.local_address = None
        self._conn_cbs: list = []

    def on_connection_event(self, cb):
        self._conn_cbs.append(cb)


def _actions_with_connection(transport: str = "le"):
    stack = _FakeStack()
    actions = IutActions(stack)
    peer = BDAddress.from_hci(bytes.fromhex("ee6a1eff5394"),
                              type=AddressType(0x00))
    actions._session.connections[0x0E01] = ConnInfo(
        handle=0x0E01, peer=peer, transport=transport,
    )
    return actions, stack


@pytest.mark.parametrize(
    "flags, expected_mode",
    [
        # doc/btp_gap.txt opcode 0x29: bit 0 = Reports Disabled.
        # HCI §7.8.91 Mode: 0x01 = sync with reports disabled,
        # 0x02 = sync with reports enabled. WID 307 sends flags=1, WID 308
        # sends flags=0 — hardcoding either one breaks the other case.
        (0x01, 0x01),
        (0x00, 0x02),
    ],
)
async def test_padv_sync_transfer_recv_maps_flags_to_hci_mode(flags, expected_mode):
    actions, stack = _actions_with_connection()

    await actions.padv_sync_transfer_recv(
        skip=0x0000, sync_timeout=0x01F4, flags=flags,
        address_type=0x00, address=bytes.fromhex("ee6a1eff5394"),
    )

    name, kwargs = stack.gap.periodic_advertising.calls[-1]
    assert name == "set_sync_transfer_parameters"
    assert kwargs["mode"] == expected_mode
    assert kwargs["conn_handle"] == 0x0E01
    assert kwargs["skip"] == 0x0000
    assert kwargs["sync_timeout"] == 0x01F4


async def test_padv_sync_transfer_recv_requires_a_live_connection():
    """The HCI command is per-connection; no handle means the caller sent the
    BTP command before the ACL was up, which must surface as an error rather
    than a silent no-op."""
    actions, stack = _actions_with_connection()
    actions._session.connections.clear()

    with pytest.raises(ValueError, match="no connection"):
        await actions.padv_sync_transfer_recv(
            skip=0x0000, sync_timeout=0x01F4, flags=0x00,
            address_type=0x00, address=bytes.fromhex("ee6a1eff5394"),
        )


async def test_padv_sync_transfer_set_info_sends_the_transfer_on_air():
    """BTP 0x27 must issue LE_Periodic_Advertising_Set_Info_Transfer.

    GAP.TS §4.7.8.4.2 step 4 has the IUT perform the Periodic Advertising
    Synchronization Transfer, and the pass verdict is the Lower Tester
    receiving it. This action used to only stash (service data, peer) for a
    later BTP 0x28, so WID 305 answered Ok and then nothing went on air for
    the whole 30 s until PTS disconnected and judged FAIL.
    """
    actions, stack = _actions_with_connection()

    await actions.padv_sync_transfer_set_info(
        address_type=0x00, address=bytes.fromhex("ee6a1eff5394"),
        service_data=0x0000,
    )

    name, kwargs = stack.gap.periodic_advertising.calls[-1]
    assert name == "set_info_transfer"
    assert kwargs["conn_handle"] == 0x0E01
    assert kwargs["service_data"] == 0x0000
    # Remembered for the re-transfer path (BTP 0x28), which targets the same
    # peer but needs a Sync_Handle the Host must already hold.
    assert actions._padv_transfer_info == (0x0000, actions._session.connections[0x0E01].peer)


async def test_padv_sync_transfer_set_info_requires_a_live_le_connection():
    actions, stack = _actions_with_connection()
    actions._session.connections.clear()

    with pytest.raises(ValueError, match="PADV_SYNC_TRANSFER_SET_INFO"):
        await actions.padv_sync_transfer_set_info(
            address_type=0x00, address=bytes.fromhex("ee6a1eff5394"),
            service_data=0x0000,
        )


async def test_padv_sync_transfer_set_info_ignores_a_classic_connection():
    """PAST rides an LE link; a BR/EDR connection to the same peer is a
    different link type and must not supply the handle."""
    actions, stack = _actions_with_connection(transport="classic")

    with pytest.raises(ValueError, match="no LE connection"):
        await actions.padv_sync_transfer_set_info(
            address_type=0x00, address=bytes.fromhex("ee6a1eff5394"),
            service_data=0x0000,
        )
