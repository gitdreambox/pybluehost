"""End-to-end LE lifecycle scenarios."""
from __future__ import annotations

import asyncio
import pytest
import pytest_asyncio

from pybluehost.core.gap_common import AdvertisingData


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


def _build_test_ad_data() -> AdvertisingData:
    """Build advertising data for the E2E test peripheral.

    Notes:
    - AdvertisingData has no `from_dict` helper.
    - AdvertisingData has no `add_service_uuid128`; we therefore advertise
      with the local name only (which is enough — the central matches the
      peripheral by BD_ADDR, not by UUID).
    """
    ad = AdvertisingData()
    ad.set_flags(0x06)  # LE General Discoverable + BR/EDR Not Supported
    ad.set_complete_local_name("PBH-E2E")
    return ad


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_scan_connect_pair_read(central_peripheral_pair, virtual_link_or_real_rf):
    """Scan -> Connect -> SC JW Pair -> discover service -> read characteristic.

    Smoke baseline: shortest valuable end-to-end path.
    """
    from tests.e2e._helpers import (
        _supports_le_sc, central_discover_and_pair_sc_jw, resolve_handles,
    )
    from tests.e2e._test_service import (
        TEST_SERVICE_UUID, TEST_READ_CHAR_UUID, INITIAL_READ_VALUE,
    )

    stack_c, stack_p = central_peripheral_pair
    if not _supports_le_sc(stack_c):
        pytest.skip("adapter does not support LE Secure Connections")

    # Peripheral starts advertising
    ad_data = _build_test_ad_data()
    await stack_p.gap.ble_advertiser.start(ad_data=ad_data)

    # Allow the virtual controller to register the advertiser before the
    # central starts scanning. Harmless on real hardware.
    await asyncio.sleep(0.1)

    handle = None
    client = None
    try:
        # Virtual transport: the VirtualController doesn't bridge ADV reports
        # or auto-respond to LE_CREATE_CONNECTION. The fixture provides a
        # `VirtualLELink` we drive ourselves: bring the link up *concurrently*
        # with stack_c.connect_gatt() so the central's pending waiter receives
        # the synthesized LE_Connection_Complete and resolves with a handle.
        link = virtual_link_or_real_rf
        if link is not None:
            # Bypass scanning in virtual mode (no ADV bridge); connect_gatt
            # is what registers the LE_Connection_Complete waiter.
            connect_task = asyncio.create_task(
                stack_c.connect_gatt(stack_p._local_address, timeout=10.0)
            )
            # Give connect_gatt a turn to register its waiter, then drive the
            # virtual link to emit LE_Connection_Complete to both controllers.
            await asyncio.sleep(0.05)
            await link.connect()
            client = await connect_task
            handle = client._connection_handle
            await stack_c.pair(handle, timeout=20.0)
        else:
            # Real RF: scan + connect + SC JW pair via canonical helper.
            client, handle = await central_discover_and_pair_sc_jw(
                stack_c, stack_p._local_address,
            )

        # Discover services
        services = await client.discover_all_services()
        svc = next(
            (s for s in services if s[2] == TEST_SERVICE_UUID.to_bytes()),
            None,
        )
        assert svc is not None, f"TEST_SERVICE_UUID not found among {services}"
        s_handle, e_handle, _uuid = svc

        # Discover characteristics within the service handle range
        chars = await client.discover_characteristics(s_handle, e_handle)
        handles = resolve_handles(chars, {"read": TEST_READ_CHAR_UUID})

        # Read the characteristic
        value = await client.read_characteristic(handles["read"])
        assert value == INITIAL_READ_VALUE, (
            f"read returned {value!r}, expected {INITIAL_READ_VALUE!r}"
        )
    finally:
        # Clean disconnect
        if handle is not None:
            try:
                await stack_c.gap.ble_connections.disconnect(handle)
            except Exception:
                pass
        try:
            await stack_p.gap.ble_advertiser.stop()
        except Exception:
            pass
