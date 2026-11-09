"""Tests for the JSON-line PTS IUT controller."""
from __future__ import annotations

from types import SimpleNamespace

from pybluehost.classic.sdp import DataElementType
from pybluehost.core.address import BDAddress
from pybluehost.pts.iut_controller import ensure_pts_sdp_records, handle_command


class FakeActions:
    def __init__(self) -> None:
        self.connectable: list[bool] = []
        self.advertised: list[bool] = []
        self.connected: list[tuple[BDAddress, bool]] = []
        self.paired: list[int | None] = []
        self._session = SimpleNamespace(connections={}, last_handle=0x0042)

    def status(self):
        return self._session

    async def set_connectable(self, enabled: bool) -> None:
        self.connectable.append(enabled)

    async def advertise(self) -> None:
        self.advertised.append(True)

    async def stop_advertising(self) -> None:
        self.advertised.append(False)

    async def connect(self, addr: BDAddress, *, le: bool = True) -> int:
        self.connected.append((addr, le))
        self._session.last_handle = 0x0048
        self._session.connections[0x0048] = SimpleNamespace(
            handle=0x0048,
            peer=addr,
            transport="le" if le else "classic",
        )
        return 0x0048

    async def pair(self, handle: int | None = None, *, io_cap=None, mitm: bool = False) -> None:
        self.paired.append(handle)


class FakeL2CAP:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []
        self.le_calls: list[dict[str, int | float]] = []
        self.le_listeners: list[int] = []

    async def connect_classic_channel(self, handle: int, psm: int):
        self.calls.append((handle, psm))
        return SimpleNamespace(cid=0x0040)

    def listen_le_coc_channel(self, psm: int, handler) -> None:
        self.le_listeners.append(psm)

    async def connect_le_coc_channel(
        self,
        *,
        handle: int,
        psm: int,
        mtu: int = 512,
        mps: int = 247,
        initial_credits: int = 10,
        timeout: float = 5.0,
    ):
        self.le_calls.append(
            {
                "handle": handle,
                "psm": psm,
                "mtu": mtu,
                "mps": mps,
                "initial_credits": initial_credits,
                "timeout": timeout,
            }
        )
        return SimpleNamespace(cid=0x0041, _peer_cid=0x0051)


class FakeStack:
    def __init__(self) -> None:
        self.local_address = BDAddress.from_string("00:1A:7D:DA:71:11")
        self.l2cap = FakeL2CAP()


class FakeSDP:
    def __init__(self) -> None:
        self.records = []

    def register(self, record):
        self.records.append(record)
        return 0x00010000


class FakeStackWithSDP(FakeStack):
    def __init__(self) -> None:
        super().__init__()
        self.sdp = FakeSDP()


async def test_status_reports_local_address_transport_and_last_handle():
    result = await handle_command(
        {"cmd": "status"},
        actions=FakeActions(),
        stack=FakeStack(),
        transport="usb:0A12:0001#1",
    )

    assert result == {
        "ok": True,
        "bd_addr": "00:1A:7D:DA:71:11",
        "transport": "usb:0A12:0001#1",
        "last_handle": 0x0042,
    }


async def test_connectable_command_dispatches_enabled_flag():
    actions = FakeActions()

    result = await handle_command(
        {"cmd": "connectable", "enabled": False},
        actions=actions,
        stack=FakeStack(),
        transport="virtual",
    )

    assert result == {"ok": True}
    assert actions.connectable == [False]


async def test_advertise_commands_start_and_stop_ble_advertising():
    actions = FakeActions()

    start = await handle_command(
        {"cmd": "advertise"},
        actions=actions,
        stack=FakeStack(),
        transport="virtual",
    )
    stop = await handle_command(
        {"cmd": "stop-advertise"},
        actions=actions,
        stack=FakeStack(),
        transport="virtual",
    )

    assert start == {"ok": True}
    assert stop == {"ok": True}
    assert actions.advertised == [True, False]


async def test_connect_command_opens_le_acl_by_default_and_returns_handle():
    actions = FakeActions()

    result = await handle_command(
        {"cmd": "connect", "addr": "C8:8A:9A:6D:5F:5F"},
        actions=actions,
        stack=FakeStack(),
        transport="usb:0A12:0001#1",
    )

    assert result == {"ok": True, "handle": 0x0048}
    assert actions.connected == [
        (BDAddress.from_string("C8:8A:9A:6D:5F:5F"), True)
    ]


async def test_pair_command_uses_last_handle_by_default():
    actions = FakeActions()

    result = await handle_command(
        {"cmd": "pair"},
        actions=actions,
        stack=FakeStack(),
        transport="usb:0A12:0001#1",
    )

    assert result == {"ok": True}
    assert actions.paired == [None]


async def test_l2cap_connect_opens_classic_acl_and_returns_handle_and_cid():
    actions = FakeActions()
    stack = FakeStack()

    result = await handle_command(
        {"cmd": "l2cap-connect", "addr": "C8:8A:9A:6D:5F:5F", "psm": 1},
        actions=actions,
        stack=stack,
        transport="usb:0A12:0001#1",
    )

    assert result == {"ok": True, "handle": 0x0048, "cid": 0x0040}
    assert actions.connected == [
        (BDAddress.from_string("C8:8A:9A:6D:5F:5F"), False)
    ]
    assert stack.l2cap.calls == [(0x0048, 1)]


async def test_l2cap_connect_reuses_active_pts_initiated_link():
    # PTS-initiated incoming ACL connections are recorded with peer=None and
    # transport="le" (see IutActions._on_connection_event), so address lookup
    # never matches. l2cap-connect must reuse the active link's handle instead
    # of timing out trying to open a fresh outgoing ACL connection to PTS.
    actions = FakeActions()
    stack = FakeStack()
    actions._session.connections[0x0048] = SimpleNamespace(
        handle=0x0048, peer=None, transport="le", gatt_client=None
    )
    actions._session.last_handle = 0x0048

    result = await handle_command(
        {"cmd": "l2cap-connect", "addr": "5C:67:83:07:04:EE", "psm": 1},
        actions=actions,
        stack=stack,
        transport="usb:0A12:0001#1",
    )

    assert result == {"ok": True, "handle": 0x0048, "cid": 0x0040}
    assert actions.connected == []  # no new outgoing connection attempted
    assert stack.l2cap.calls == [(0x0048, 1)]


async def test_l2cap_le_listen_registers_psm_listener():
    actions = FakeActions()
    stack = FakeStack()

    result = await handle_command(
        {"cmd": "l2cap-le-listen", "psm": "0x0080"},
        actions=actions,
        stack=stack,
        transport="usb:0A12:0001#1",
    )

    assert result == {"ok": True, "psm": 0x0080}
    assert stack.l2cap.le_listeners == [0x0080]


async def test_l2cap_le_connect_opens_le_acl_and_returns_handle_and_cid():
    actions = FakeActions()
    stack = FakeStack()

    result = await handle_command(
        {
            "cmd": "l2cap-le-connect",
            "addr": "C8:8A:9A:6D:5F:5F",
            "psm": "0x0080",
            "mtu": 512,
            "mps": 247,
            "credits": 10,
        },
        actions=actions,
        stack=stack,
        transport="usb:0A12:0001#1",
    )

    assert result == {"ok": True, "handle": 0x0048, "cid": 0x0041}
    assert actions.connected == [
        (BDAddress.from_string("C8:8A:9A:6D:5F:5F"), True)
    ]
    assert stack.l2cap.le_calls == [
        {
            "handle": 0x0048,
            "psm": 0x0080,
            "mtu": 512,
            "mps": 247,
            "initial_credits": 10,
            "timeout": 5.0,
        }
    ]

async def test_l2cap_le_connect_uses_last_handle_when_addr_omitted():
    actions = FakeActions()
    stack = FakeStack()

    result = await handle_command(
        {"cmd": "l2cap-le-connect", "psm": "0x0080"},
        actions=actions,
        stack=stack,
        transport="usb:0A12:0001#1",
    )

    assert result == {"ok": True, "handle": 0x0042, "cid": 0x0041}
    assert actions.connected == []
    assert stack.l2cap.le_calls[0]["handle"] == 0x0042

def test_ensure_pts_sdp_records_registers_l2cap_search_record():
    stack = FakeStackWithSDP()

    handle = ensure_pts_sdp_records(stack)

    assert handle == 0x00010000
    assert len(stack.sdp.records) == 1
    record = stack.sdp.records[0]
    assert {0x0001, 0x0004, 0x0005}.issubset(record.attributes)
    service_classes = record.attributes[0x0001]
    assert service_classes.type == DataElementType.SEQUENCE
    assert service_classes.value[0].value == 0x0100