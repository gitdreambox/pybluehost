"""End-to-end LE lifecycle scenarios."""
from __future__ import annotations

import asyncio
import pytest


def test_test_service_definition_round_trips():
    """build_test_service() returns a valid ServiceDefinition with 3 chars."""
    from tests.e2e._test_service import build_test_service
    svc = build_test_service()
    assert len(svc.characteristics) == 3
    uuids = [c.uuid for c in svc.characteristics]
    from tests.e2e._test_service import (
        TEST_READ_CHAR_UUID, TEST_WRITE_CHAR_UUID, TEST_NOTIFY_CHAR_UUID,
    )
    assert TEST_READ_CHAR_UUID in uuids
    assert TEST_WRITE_CHAR_UUID in uuids
    assert TEST_NOTIFY_CHAR_UUID in uuids


@pytest.mark.asyncio
async def test_wait_for_notifications_returns_when_count_reached():
    from tests.e2e._helpers import wait_for_notifications
    events: list = []

    async def producer():
        await asyncio.sleep(0.01)
        events.append(b"a")
        await asyncio.sleep(0.01)
        events.append(b"b")

    task = asyncio.create_task(producer())
    await wait_for_notifications(events, n=2, timeout=1.0)
    await task
    assert events == [b"a", b"b"]


@pytest.mark.asyncio
async def test_wait_for_notifications_raises_on_timeout():
    from tests.e2e._helpers import wait_for_notifications
    events: list = []
    with pytest.raises(asyncio.TimeoutError):
        await wait_for_notifications(events, n=1, timeout=0.05)


def test_resolve_handles_returns_per_uuid_value_handles():
    """Given a discovered-characteristics list, returns a dict keyed by UUID
    that maps to the value_handle."""
    from tests.e2e._helpers import resolve_handles
    from tests.e2e._test_service import (
        TEST_READ_CHAR_UUID, TEST_WRITE_CHAR_UUID, TEST_NOTIFY_CHAR_UUID,
    )
    from pybluehost.ble.gatt import DiscoveredCharacteristic
    chars = [
        DiscoveredCharacteristic(declaration_handle=0x10, value_handle=0x11,
                                 properties=0x02, uuid=TEST_READ_CHAR_UUID.to_bytes()),
        DiscoveredCharacteristic(declaration_handle=0x12, value_handle=0x13,
                                 properties=0x08, uuid=TEST_WRITE_CHAR_UUID.to_bytes()),
        DiscoveredCharacteristic(declaration_handle=0x14, value_handle=0x15,
                                 properties=0x10, uuid=TEST_NOTIFY_CHAR_UUID.to_bytes()),
    ]
    handles = resolve_handles(chars, {
        "read": TEST_READ_CHAR_UUID,
        "write": TEST_WRITE_CHAR_UUID,
        "notify": TEST_NOTIFY_CHAR_UUID,
    })
    assert handles == {"read": 0x11, "write": 0x13, "notify": 0x15}
