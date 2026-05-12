"""L2CAPManager.on_le_connection_open callback hook tests."""
from __future__ import annotations

from pybluehost.core.types import LinkType
from pybluehost.l2cap.constants import CID_ATT, CID_SMP
from pybluehost.l2cap.manager import L2CAPManager


async def test_on_le_connection_open_fires_when_le_connection_registered():
    manager = L2CAPManager(hci=None)
    seen: list[tuple[int, dict]] = []

    def listener(handle: int, channels: dict) -> None:
        seen.append((handle, channels))

    manager.on_le_connection_open(listener)
    await manager.on_connection(
        handle=0x0040, link_type=LinkType.LE, peer_address=None, role=None,
    )

    assert len(seen) == 1
    handle, channels = seen[0]
    assert handle == 0x0040
    assert CID_ATT in channels
    assert CID_SMP in channels


async def test_on_le_connection_open_does_not_fire_for_classic():
    manager = L2CAPManager(hci=None)
    seen: list[int] = []
    manager.on_le_connection_open(lambda h, c: seen.append(h))

    await manager.on_connection(
        handle=0x0080, link_type=LinkType.ACL, peer_address=None, role=None,
    )
    assert seen == []


async def test_on_le_connection_open_supports_multiple_listeners():
    manager = L2CAPManager(hci=None)
    seen_a: list[int] = []
    seen_b: list[int] = []
    manager.on_le_connection_open(lambda h, c: seen_a.append(h))
    manager.on_le_connection_open(lambda h, c: seen_b.append(h))

    await manager.on_connection(
        handle=0x0041, link_type=LinkType.LE, peer_address=None, role=None,
    )

    assert seen_a == [0x0041]
    assert seen_b == [0x0041]


async def test_on_le_connection_open_listener_exception_does_not_break_others(caplog):
    """A listener raising must not prevent later listeners from firing."""
    import logging

    manager = L2CAPManager(hci=None)
    seen: list[int] = []

    def bad_listener(handle: int, channels: dict) -> None:
        raise RuntimeError("boom")

    def good_listener(handle: int, channels: dict) -> None:
        seen.append(handle)

    manager.on_le_connection_open(bad_listener)
    manager.on_le_connection_open(good_listener)

    with caplog.at_level(logging.ERROR):
        await manager.on_connection(
            handle=0x0042, link_type=LinkType.LE, peer_address=None, role=None,
        )

    assert seen == [0x0042]
    assert any("LE connection listener raised" in rec.message for rec in caplog.records)
