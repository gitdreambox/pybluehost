"""GAP event emission tests — scan callback -> DEVICE_FOUND."""
import asyncio
from dataclasses import dataclass

import pytest

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import BtpFrame
from pybluehost.pts.btp.services.gap import GapService


class _FakeTester:
    def __init__(self):
        self.events: list[BtpFrame] = []

    async def emit_event(self, frame: BtpFrame) -> None:
        self.events.append(frame)


@dataclass
class _FakeBDAddress:
    address_type: int
    raw: bytes

    @property
    def bytes(self) -> bytes:
        return self.raw


@dataclass
class _FakeAdvData:
    raw: bytes

    def to_bytes(self) -> bytes:
        return self.raw


@dataclass
class _FakeScanResult:
    address: _FakeBDAddress
    rssi: int
    advertising_data: _FakeAdvData
    connectable: bool = True


class _FakeActions:
    def __init__(self):
        self.calls = []
        self._scan_handler = None

    async def scan(self, *, active=False, on_result=None):
        self.calls.append(("scan", {"active": active}))
        self._scan_handler = on_result

    async def stop_scan(self):
        self.calls.append(("stop_scan", {}))
        self._scan_handler = None

    def simulate_scan_result(self, result):
        if self._scan_handler is not None:
            self._scan_handler(result)


@pytest.mark.asyncio
async def test_device_found_event_emitted_on_scan_result():
    tester = _FakeTester()
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    await svc.dispatch(opcode=op.OP_GAP_START_DISCOVERY, controller_index=0,
                       data=bytes([1]))

    result = _FakeScanResult(
        address=_FakeBDAddress(address_type=op.GAP_ADDR_TYPE_RANDOM,
                               raw=bytes.fromhex("FFEEDDCCBBAA")),
        rssi=-50,
        advertising_data=_FakeAdvData(raw=bytes.fromhex("020106")),
        connectable=True,
    )
    actions.simulate_scan_result(result)
    await asyncio.sleep(0)

    assert len(tester.events) == 1
    event = tester.events[0]
    assert event.service == op.SERVICE_GAP
    assert event.opcode == op.OP_GAP_EVENT_DEVICE_FOUND
    # Payload: addr_type(u8) + addr(6) + rssi(s8) + flags(u8) + eir_len(u16 LE) + eir
    assert event.data[0] == op.GAP_ADDR_TYPE_RANDOM
    assert event.data[1:7] == bytes.fromhex("FFEEDDCCBBAA")
    assert event.data[7] == (256 - 50) & 0xFF      # int8(-50) as u8
    assert event.data[8] & 0x01                    # connectable flag
    assert int.from_bytes(event.data[9:11], "little") == 3
    assert event.data[11:14] == bytes.fromhex("020106")


@pytest.mark.asyncio
async def test_device_found_event_address_is_little_endian():
    """auto-pts parses DEVICE_FOUND addr with le_bytes_to_hex_str (reverses
    bytes), so a real BDAddress must be emitted in HCI little-endian order."""
    from pybluehost.core.address import BDAddress

    tester = _FakeTester()
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    await svc.dispatch(opcode=op.OP_GAP_START_DISCOVERY, controller_index=0,
                       data=bytes([1]))

    # PTS dongle 5C:67:83:07:04:EE — canonical (big-endian) address.
    bd = BDAddress.from_string("5C:67:83:07:04:EE")
    result = _FakeScanResult(
        address=bd,
        rssi=-40,
        advertising_data=_FakeAdvData(raw=b"\x02\x01\x02"),
        connectable=True,
    )
    actions.simulate_scan_result(result)
    await asyncio.sleep(0)

    assert len(tester.events) == 1
    # to_hci() little-endian: EE 04 07 83 67 5C; le_bytes_to_hex_str reverses
    # it back to "5c67830704ee" on the autopts side.
    assert tester.events[0].data[1:7] == bytes.fromhex("EE040783675C")


@pytest.mark.asyncio
async def test_stop_discovery_clears_callback():
    tester = _FakeTester()
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    await svc.dispatch(opcode=op.OP_GAP_START_DISCOVERY, controller_index=0,
                       data=bytes([1]))
    status, _ = await svc.dispatch(opcode=op.OP_GAP_STOP_DISCOVERY,
                                   controller_index=0, data=b"")
    assert status == op.BTP_STATUS_SUCCESS
    # After stop, simulating a result should not fire an event.
    result = _FakeScanResult(
        address=_FakeBDAddress(address_type=0, raw=bytes(6)),
        rssi=0, advertising_data=_FakeAdvData(raw=b""),
    )
    actions.simulate_scan_result(result)
    await asyncio.sleep(0)
    assert len(tester.events) == 0


# ---------------------------------------------------------------------------
# T6: DEVICE_CONNECTED / DEVICE_DISCONNECTED events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_device_connected_event_on_state_change():
    tester = _FakeTester()
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    svc.on_connection_state_change(
        handle=0x000C, addr=bytes.fromhex("AABBCCDDEEFF"),
        addr_type=op.GAP_ADDR_TYPE_RANDOM, connected=True,
    )
    await asyncio.sleep(0)
    assert len(tester.events) == 1
    evt = tester.events[0]
    assert evt.opcode == op.OP_GAP_EVENT_DEVICE_CONNECTED
    assert evt.data[0] == op.GAP_ADDR_TYPE_RANDOM
    assert evt.data[1:7] == bytes.fromhex("AABBCCDDEEFF")
    # Payload includes conn_interval(2) + latency(2) + timeout(2) — 13 bytes total
    assert len(evt.data) == 13


@pytest.mark.asyncio
async def test_device_connected_event_carries_real_conn_params():
    """PTS GAP/CONN/CPUP: auto-pts's DEVICE_CONNECTED handler stores the reported
    (interval, latency, timeout) as the conn_params baseline that WID 46 reads and
    bumps. Zeros would make WID 46 request an invalid itvl=0 update, so the event
    must carry the real connection parameters (raw HCI units)."""
    import struct

    tester = _FakeTester()
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    svc.on_connection_state_change(
        handle=0x000C, addr=bytes.fromhex("AABBCCDDEEFF"),
        addr_type=op.GAP_ADDR_TYPE_RANDOM, connected=True,
        conn_params=(0x0030, 0x0001, 0x01F4),
    )
    await asyncio.sleep(0)
    evt = tester.events[0]
    assert evt.opcode == op.OP_GAP_EVENT_DEVICE_CONNECTED
    itvl, latency, timeout = struct.unpack_from("<HHH", evt.data, 7)
    assert (itvl, latency, timeout) == (0x0030, 0x0001, 0x01F4)


@pytest.mark.asyncio
async def test_device_connected_event_defaults_params_to_zero_when_unknown():
    tester = _FakeTester()
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    svc.on_connection_state_change(
        handle=0x000C, addr=bytes.fromhex("AABBCCDDEEFF"),
        addr_type=op.GAP_ADDR_TYPE_RANDOM, connected=True,
    )
    await asyncio.sleep(0)
    assert tester.events[0].data[7:13] == b"\x00" * 6


@pytest.mark.asyncio
async def test_device_disconnected_event_on_state_change():
    tester = _FakeTester()
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    svc.on_connection_state_change(
        handle=0x000C, addr=bytes.fromhex("AABBCCDDEEFF"),
        addr_type=op.GAP_ADDR_TYPE_RANDOM, connected=True,
    )
    svc.on_connection_state_change(
        handle=0x000C, addr=bytes.fromhex("AABBCCDDEEFF"),
        addr_type=op.GAP_ADDR_TYPE_RANDOM, connected=False,
    )
    await asyncio.sleep(0)
    assert tester.events[-1].opcode == op.OP_GAP_EVENT_DEVICE_DISCONNECTED
    assert len(tester.events[-1].data) == 7


@pytest.mark.asyncio
async def test_new_settings_pushed_when_connection_stops_advertising():
    """PTS GAP/SEC/SEM multi-round: when a connection forms, legacy advertising
    stops. The ADVERTISING bit must be cleared AND a NEW_SETTINGS event pushed so
    auto-pts's GAP model re-syncs — else gap_start_advertising() short-circuits
    the re-advertise on the next round (stale 'already advertising')."""
    tester = _FakeTester()
    svc = GapService(actions=_FakeActions(), tester=tester)
    svc._current_settings |= (1 << 10)  # GAP_SETTINGS_ADVERTISING (round-1 advertised)

    svc.on_connection_state_change(
        handle=0x000C, addr=bytes.fromhex("AABBCCDDEEFF"),
        addr_type=op.GAP_ADDR_TYPE_RANDOM, connected=True,
    )
    await asyncio.sleep(0)

    opcodes = [e.opcode for e in tester.events]
    assert op.OP_GAP_EVENT_DEVICE_CONNECTED in opcodes
    assert op.OP_GAP_EVENT_NEW_SETTINGS in opcodes
    ns = next(e for e in tester.events if e.opcode == op.OP_GAP_EVENT_NEW_SETTINGS)
    reported = int.from_bytes(ns.data, "little")
    assert not (reported & (1 << 10)), "ADVERTISING bit must be cleared in NEW_SETTINGS"
    assert not (svc._current_settings & (1 << 10)), "service settings must drop ADVERTISING"


@pytest.mark.asyncio
async def test_no_new_settings_when_not_advertising():
    """No NEW_SETTINGS push if we weren't advertising (no stale model to fix)."""
    tester = _FakeTester()
    svc = GapService(actions=_FakeActions(), tester=tester)
    # ADVERTISING bit NOT set.
    svc.on_connection_state_change(
        handle=0x000C, addr=bytes.fromhex("AABBCCDDEEFF"),
        addr_type=op.GAP_ADDR_TYPE_RANDOM, connected=True,
    )
    await asyncio.sleep(0)
    assert all(e.opcode != op.OP_GAP_EVENT_NEW_SETTINGS for e in tester.events)


# ---------------------------------------------------------------------------
# T7: Pairing events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pairing_failed_event_emitted():
    tester = _FakeTester()
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    svc.on_pairing_failed(addr=bytes.fromhex("AABBCCDDEEFF"),
                          addr_type=op.GAP_ADDR_TYPE_RANDOM, reason=0x05)
    await asyncio.sleep(0)
    assert len(tester.events) == 1
    evt = tester.events[0]
    assert evt.opcode == op.OP_GAP_EVENT_PAIRING_FAILED
    assert evt.data == bytes([op.GAP_ADDR_TYPE_RANDOM]) + bytes.fromhex("AABBCCDDEEFF") + bytes([0x05])


@pytest.mark.asyncio
async def test_sec_level_changed_event_emitted():
    tester = _FakeTester()
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    svc.on_sec_level_changed(addr=bytes(6), addr_type=0, sec_level=2)
    await asyncio.sleep(0)
    assert len(tester.events) == 1
    assert tester.events[-1].opcode == op.OP_GAP_EVENT_SEC_LEVEL_CHANGED
    assert tester.events[-1].data[-1] == 2


@pytest.mark.asyncio
async def test_passkey_display_event_emitted():
    tester = _FakeTester()
    actions = _FakeActions()
    svc = GapService(actions=actions, tester=tester)
    svc.on_passkey_display(addr=bytes.fromhex("AABBCCDDEEFF"),
                            addr_type=op.GAP_ADDR_TYPE_RANDOM, passkey=123456)
    await asyncio.sleep(0)
    assert len(tester.events) == 1
    evt = tester.events[0]
    assert evt.opcode == op.OP_GAP_EVENT_PASSKEY_DISPLAY
    assert evt.data[:7] == bytes([op.GAP_ADDR_TYPE_RANDOM]) + bytes.fromhex("AABBCCDDEEFF")
    assert int.from_bytes(evt.data[7:11], "little") == 123456


@pytest.mark.asyncio
async def test_bond_lost_event_carries_the_peer_address():
    """BTP GAP BOND_LOST (0x8B) — body addr_type(1) + addr(6, little-endian),
    matching auto-pts's `gap_bond_lost_ev_` (`'<B6s'`). GAP/SEC/AUT/BV-21/22
    pass only if the peer's "PIN or Key Missing" reaches the Upper Tester."""
    tester = _FakeTester()
    svc = GapService(actions=_FakeActions(), tester=tester)

    svc.on_bond_lost(addr=b"\x11\x22\x33\x44\x55\x66", addr_type=1)
    await asyncio.sleep(0)

    assert len(tester.events) == 1
    event = tester.events[0]
    assert event.opcode == op.OP_GAP_EVENT_BOND_LOST
    assert event.data == b"\x01\x11\x22\x33\x44\x55\x66"


@pytest.mark.asyncio
async def test_bond_lost_event_pads_a_short_address():
    tester = _FakeTester()
    svc = GapService(actions=_FakeActions(), tester=tester)

    svc.on_bond_lost(addr=b"\xAA", addr_type=0)
    await asyncio.sleep(0)

    assert tester.events[0].data == b"\x00\xAA\x00\x00\x00\x00\x00"


# ---------------------------------------------------------------------------
# Host-side RPA resolution (bond IRKs snapshot at START_DISCOVERY)
# ---------------------------------------------------------------------------

class _FakeBondStorage:
    def __init__(self, bonds):
        self._bonds = bonds

    async def list_bonds(self):
        return self._bonds


@dataclass
class _FakeBond:
    irk: bytes
    peer_address: object
    address_type: int = 0


def _stack_with_bonds(storage):
    from types import SimpleNamespace

    return SimpleNamespace(config=SimpleNamespace(bond_storage=storage))


@pytest.mark.asyncio
async def test_device_found_resolves_a_bonded_peer_rpa_to_identity():
    """The controller may report an unresolved resolvable-private address;
    auto-pts compares DEVICE_FOUND against the peer *identity*, so the adapter
    resolves against the bond IRKs (Core Vol 3 Part H §2.2.2 via resolve_rpa)."""
    from pybluehost.ble.gap import PrivacyManager
    from pybluehost.core.address import BDAddress

    irk = bytes(range(16))
    rpa = PrivacyManager.generate_rpa(irk)
    identity = BDAddress.from_string("FC:9E:53:D5:8D:EB")

    tester = _FakeTester()
    actions = _FakeActions()
    actions.stack = _stack_with_bonds(
        _FakeBondStorage([_FakeBond(irk=irk, peer_address=identity)])
    )
    svc = GapService(actions=actions, tester=tester)
    await svc.dispatch(opcode=op.OP_GAP_START_DISCOVERY, controller_index=0,
                       data=bytes([1]))

    actions.simulate_scan_result(_FakeScanResult(
        address=_FakeBDAddress(address_type=1, raw=rpa),
        rssi=-40,
        advertising_data=_FakeAdvData(raw=b"\x02\x01\x02"),
        connectable=False,
    ))
    await asyncio.sleep(0)

    assert len(tester.events) == 1
    payload = tester.events[0].data
    assert payload[0] == 0  # identity address type (public)
    assert payload[1:7] == identity.to_hci()


@pytest.mark.asyncio
async def test_device_found_leaves_unmatched_rpas_untouched():
    from pybluehost.ble.gap import PrivacyManager

    rpa = PrivacyManager.generate_rpa(bytes(range(16)))  # nobody holds this IRK

    tester = _FakeTester()
    actions = _FakeActions()
    actions.stack = _stack_with_bonds(_FakeBondStorage([]))
    svc = GapService(actions=actions, tester=tester)
    await svc.dispatch(opcode=op.OP_GAP_START_DISCOVERY, controller_index=0,
                       data=bytes([1]))

    actions.simulate_scan_result(_FakeScanResult(
        address=_FakeBDAddress(address_type=1, raw=rpa),
        rssi=-40,
        advertising_data=_FakeAdvData(raw=b"\x02\x01\x02"),
        connectable=False,
    ))
    await asyncio.sleep(0)

    assert len(tester.events) == 1
    payload = tester.events[0].data
    assert payload[0] == 1
    assert payload[1:7] == rpa


class _FakePrivacy:
    def __init__(self):
        self.resolution_calls = []

    async def set_address_resolution(self, enable):
        self.resolution_calls.append(enable)
        return True


@pytest.mark.asyncio
async def test_scan_resolution_off_disables_controller_resolution(monkeypatch):
    """PYBLUEHOST_SCAN_RESOLUTION=off flips RPA resolution to host-side: the
    START_DISCOVERY path must disable controller resolution before scanning."""
    from types import SimpleNamespace

    privacy = _FakePrivacy()
    stack = SimpleNamespace(
        config=SimpleNamespace(bond_storage=_FakeBondStorage([])),
        gap=SimpleNamespace(ble_privacy=privacy),
    )
    tester = _FakeTester()
    actions = _FakeActions()
    actions.stack = stack
    svc = GapService(actions=actions, tester=tester)

    monkeypatch.setenv("PYBLUEHOST_SCAN_RESOLUTION", "off")
    await svc.dispatch(opcode=op.OP_GAP_START_DISCOVERY, controller_index=0,
                       data=bytes([1]))
    assert privacy.resolution_calls == [False]


@pytest.mark.asyncio
async def test_scan_resolution_default_leaves_controller_resolution_alone(monkeypatch):
    from types import SimpleNamespace

    privacy = _FakePrivacy()
    stack = SimpleNamespace(
        config=SimpleNamespace(bond_storage=_FakeBondStorage([])),
        gap=SimpleNamespace(ble_privacy=privacy),
    )
    tester = _FakeTester()
    actions = _FakeActions()
    actions.stack = stack
    svc = GapService(actions=actions, tester=tester)

    monkeypatch.delenv("PYBLUEHOST_SCAN_RESOLUTION", raising=False)
    await svc.dispatch(opcode=op.OP_GAP_START_DISCOVERY, controller_index=0,
                       data=bytes([1]))
    assert privacy.resolution_calls == []
