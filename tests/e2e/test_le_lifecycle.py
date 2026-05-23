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


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_gatt_write_and_notify(central_peripheral_pair, virtual_link_or_real_rf, transport_mode):
    """Write a characteristic; subscribe to notifications; observe two
    notifications; unsubscribe; verify a third notification is NOT observed."""
    import contextlib

    from tests.e2e._helpers import (
        _supports_le_sc, central_discover_peripheral,
        e2e_timeout, resolve_handles, wait_for_notifications,
    )
    from tests.e2e._test_service import (
        TEST_SERVICE_UUID, TEST_WRITE_CHAR_UUID, TEST_NOTIFY_CHAR_UUID,
    )
    from pybluehost.ble.gatt import UUID_CCCD

    stack_c, stack_p = central_peripheral_pair
    if not _supports_le_sc(stack_c):
        pytest.skip("adapter does not support LE Secure Connections")

    ad_data = _build_test_ad_data()
    await stack_p.gap.ble_advertiser.start(ad_data=ad_data)
    handle = None
    try:
        # === Connection + pairing (mirror Test 1's virtual-mode adaptation) ===
        link = virtual_link_or_real_rf
        if link is not None:
            connect_task = asyncio.create_task(
                stack_c.connect_gatt(stack_p._local_address, timeout=10.0)
            )
            await asyncio.sleep(0.05)
            await link.connect()
            client = await connect_task
        else:
            await central_discover_peripheral(stack_c, stack_p._local_address)
            client = await stack_c.connect_gatt(stack_p._local_address, timeout=10.0)
        handle = client._connection_handle
        await stack_c.pair(handle, timeout=20.0)

        # === Discover service + characteristics + CCCD ===
        services = await client.discover_all_services()
        svc = next(s for s in services if s[2] == TEST_SERVICE_UUID.to_bytes())
        s_handle, e_handle, _ = svc
        chars = await client.discover_characteristics(s_handle, e_handle)
        handles = resolve_handles(chars, {
            "write": TEST_WRITE_CHAR_UUID,
            "notify": TEST_NOTIFY_CHAR_UUID,
        })
        # Find CCCD descriptor for the notify char (in handle range [notify_value+1, e_handle]).
        descs = await client.discover_descriptors(handles["notify"] + 1, e_handle)
        cccd = next(d for d in descs if d.uuid == UUID_CCCD.to_bytes())

        # === Write path ===
        await client.write_characteristic(handles["write"], b"hello e2e")
        await asyncio.sleep(0.05)

        # === Notify path ===
        notify_events: list[bytes] = []

        def _on_notify(att_handle: int, value: bytes) -> None:
            if att_handle == handles["notify"]:
                notify_events.append(value)

        client._bearer.set_notification_handler(_on_notify)

        # Subscribe (CCCD = 0x0001 enables notifications, little-endian)
        await client.write_characteristic(cccd.handle, bytes([0x01, 0x00]))
        await asyncio.sleep(0.05)

        # Peripheral emits two notifications
        await stack_p._gatt_server.notify(handles["notify"], b"ping-1")
        await stack_p._gatt_server.notify(handles["notify"], b"ping-2")
        await wait_for_notifications(notify_events, n=2, timeout=e2e_timeout(transport_mode, virtual=2.0, usb=5.0))
        assert notify_events == [b"ping-1", b"ping-2"]

        # Unsubscribe (CCCD = 0x0000)
        await client.write_characteristic(cccd.handle, bytes([0x00, 0x00]))
        await asyncio.sleep(0.05)

        # A subsequent peripheral notify should NOT be observed
        await stack_p._gatt_server.notify(handles["notify"], b"ping-3")
        await asyncio.sleep(0.2)
        assert notify_events == [b"ping-1", b"ping-2"]

    finally:
        if handle is not None:
            with contextlib.suppress(Exception):
                await stack_c.gap.ble_connections.disconnect(handle)
        with contextlib.suppress(Exception):
            await stack_p.gap.ble_advertiser.stop()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_bonded_reconnect_auto_encrypt(
    tmp_path, selected_transport_spec, selected_peer_spec, transport_mode,
):
    """Two sessions sharing on-disk bond storage. Session 1: pair + bond.
    Session 2: reconnect -> auto-encrypt event fires -> GATT read works on
    the encrypted link without redoing SMP."""
    import contextlib

    from pybluehost.ble.security import SecurityConfig
    from pybluehost.ble.smp import JsonBondStorage
    from pybluehost.core.address import BDAddress
    from pybluehost.hci.virtual_link import VirtualLELink
    from pybluehost.stack import Stack, StackConfig

    from tests.e2e._helpers import (
        _supports_le_sc, central_discover_peripheral, e2e_timeout, resolve_handles,
    )
    from tests.e2e._test_service import (
        TEST_SERVICE_UUID, TEST_READ_CHAR_UUID, INITIAL_READ_VALUE,
        build_test_service,
    )

    bonds_c_path = tmp_path / "bonds_c.json"
    bonds_p_path = tmp_path / "bonds_p.json"
    central_addr = BDAddress(b"\x0A\x0A\x0A\x0A\x0A\x0A")
    peripheral_addr = BDAddress(b"\x0B\x0B\x0B\x0B\x0B\x0B")

    async def _open_pair():
        cfg_c = StackConfig(
            bond_storage=JsonBondStorage(bonds_c_path),
            security=SecurityConfig(enable_secure_connections=True),
        )
        cfg_p = StackConfig(
            bond_storage=JsonBondStorage(bonds_p_path),
            security=SecurityConfig(enable_secure_connections=True),
        )
        if transport_mode == "virtual":
            stack_c = await Stack.virtual(config=cfg_c, address=central_addr)
            stack_p = await Stack.virtual(config=cfg_p, address=peripheral_addr)
            link = VirtualLELink(
                central=stack_c._virtual_controller,
                peripheral=stack_p._virtual_controller,
                central_address=central_addr,
                peripheral_address=peripheral_addr,
            )
        else:
            from tests._transport_resolve import build_stack_from_spec
            stack_c = await build_stack_from_spec(selected_transport_spec, config=cfg_c)
            stack_p = await build_stack_from_spec(selected_peer_spec, config=cfg_p)
            link = None
        stack_p._gatt_server.add_service(build_test_service())
        return stack_c, stack_p, link

    async def _close_pair(stack_c, stack_p, link):
        if link is not None:
            with contextlib.suppress(Exception):
                await link.disconnect()
        with contextlib.suppress(Exception):
            await stack_c.close()
        with contextlib.suppress(Exception):
            await stack_p.close()

    # ===== Session 1: pair + bond =====
    stack_c, stack_p, link = await _open_pair()
    if not _supports_le_sc(stack_c):
        await _close_pair(stack_c, stack_p, link)
        pytest.skip("adapter does not support LE Secure Connections")
    # In hardware mode the adapter's real BD_ADDR is canonical
    if transport_mode != "virtual":
        central_addr = stack_c._local_address
        peripheral_addr = stack_p._local_address

    ad_data = _build_test_ad_data()
    await stack_p.gap.ble_advertiser.start(ad_data=ad_data)
    handle = None
    try:
        # Mirror Test 1's virtual-mode connection injection
        if link is not None:
            connect_task = asyncio.create_task(
                stack_c.connect_gatt(peripheral_addr, timeout=10.0)
            )
            await asyncio.sleep(0.1)
            await link.connect()
            client = await connect_task
        else:
            await central_discover_peripheral(stack_c, peripheral_addr)
            client = await stack_c.connect_gatt(peripheral_addr, timeout=10.0)
        handle = client._connection_handle
        await stack_c.pair(handle, timeout=20.0)

        # Verify bond was persisted
        bond_c = await JsonBondStorage(bonds_c_path).load_bond(peripheral_addr)
        assert bond_c is not None, "Central bond not persisted after Session 1 pair"
        assert bond_c.sc is True, "Session 1 bond should be SC"

        # Clean disconnect before tearing down session 1
        with contextlib.suppress(Exception):
            await stack_c.gap.ble_connections.disconnect(handle)
    finally:
        with contextlib.suppress(Exception):
            await stack_p.gap.ble_advertiser.stop()
        await _close_pair(stack_c, stack_p, link)

    # ===== Session 2: reconnect + auto-encrypt + GATT read =====
    stack_c, stack_p, link = await _open_pair()
    # In hardware mode the adapter's real BD_ADDR is canonical
    if transport_mode != "virtual":
        central_addr = stack_c._local_address
        peripheral_addr = stack_p._local_address

    encrypted_events: list = []

    def _on_event(e):
        if getattr(e, "state", None) == "encrypted":
            encrypted_events.append(e)

    stack_c.on_connection_event(_on_event)

    await stack_p.gap.ble_advertiser.start(ad_data=_build_test_ad_data())
    handle = None
    try:
        # Reconnect — NO pair() call; auto-encrypt should fire automatically.
        if link is not None:
            connect_task = asyncio.create_task(
                stack_c.connect_gatt(peripheral_addr, timeout=10.0)
            )
            await asyncio.sleep(0.1)
            await link.connect()
            client = await connect_task
        else:
            await central_discover_peripheral(stack_c, peripheral_addr)
            client = await stack_c.connect_gatt(peripheral_addr, timeout=10.0)
        handle = client._connection_handle

        # Wait up to e2e_timeout budget for the encryption-change event
        for _ in range(int(e2e_timeout(transport_mode, virtual=2.0, usb=10.0) / 0.05)):
            if encrypted_events:
                break
            await asyncio.sleep(0.05)
        assert encrypted_events, "auto-encrypt did not fire on bonded reconnect"

        # GATT read on the encrypted link
        services = await client.discover_all_services()
        svc = next(s for s in services if s[2] == TEST_SERVICE_UUID.to_bytes())
        chars = await client.discover_characteristics(svc[0], svc[1])
        handles = resolve_handles(chars, {"read": TEST_READ_CHAR_UUID})
        value = await client.read_characteristic(handles["read"])
        assert value == INITIAL_READ_VALUE
    finally:
        if handle is not None:
            with contextlib.suppress(Exception):
                await stack_c.gap.ble_connections.disconnect(handle)
        with contextlib.suppress(Exception):
            await stack_p.gap.ble_advertiser.stop()
        await _close_pair(stack_c, stack_p, link)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_e2e_pair_failure_disconnects_cleanly(
    tmp_path, selected_transport_spec, selected_peer_spec, transport_mode,
):
    """Mismatched NC delegates -> pair() raises with reason=3 -> teardown
    completes within 2s on each stack. Regression guard against leaked
    pairing_complete futures from Sub-Plan 3a/3b reviews."""
    import asyncio
    import contextlib

    from pybluehost.ble.security import SecurityConfig
    from pybluehost.ble.smp import AutoAcceptDelegate, JsonBondStorage
    from pybluehost.core.address import BDAddress
    from pybluehost.core.types import IOCapability
    from pybluehost.hci.virtual_link import VirtualLELink
    from pybluehost.stack import Stack, StackConfig

    from tests._transport_resolve import build_stack_from_spec
    from tests.e2e._helpers import _supports_le_sc, e2e_timeout

    # This test requires SecurityConfig(mitm_required=True), which is not the
    # default session fixture; build our own stacks.
    central_addr = BDAddress(b"\x0A\x0A\x0A\x0A\x0A\x0A")
    peripheral_addr = BDAddress(b"\x0B\x0B\x0B\x0B\x0B\x0B")

    cfg_c = StackConfig(
        bond_storage=JsonBondStorage(tmp_path / "bonds_c.json"),
        security=SecurityConfig(
            enable_secure_connections=True, mitm_required=True,
        ),
        le_io_capability=IOCapability.DISPLAY_YES_NO,
    )
    cfg_p = StackConfig(
        bond_storage=JsonBondStorage(tmp_path / "bonds_p.json"),
        security=SecurityConfig(
            enable_secure_connections=True, mitm_required=True,
        ),
        le_io_capability=IOCapability.DISPLAY_YES_NO,
    )

    if transport_mode == "virtual":
        stack_c = await Stack.virtual(config=cfg_c, address=central_addr)
        stack_p = await Stack.virtual(config=cfg_p, address=peripheral_addr)
        link = VirtualLELink(
            central=stack_c._virtual_controller,
            peripheral=stack_p._virtual_controller,
            central_address=central_addr,
            peripheral_address=peripheral_addr,
        )
    else:
        stack_c = await build_stack_from_spec(selected_transport_spec, config=cfg_c)
        stack_p = await build_stack_from_spec(selected_peer_spec, config=cfg_p)
        central_addr = stack_c._local_address
        peripheral_addr = stack_p._local_address
        link = None

    if not _supports_le_sc(stack_c):
        if link is not None:
            with contextlib.suppress(Exception):
                await link.disconnect()
        await stack_c.close()
        await stack_p.close()
        pytest.skip("adapter does not support LE Secure Connections")

    # Inject mismatched delegates: Central accepts, Peripheral rejects.
    class _AcceptNC(AutoAcceptDelegate):
        async def confirm_numeric(self, peer_addr, value):
            return True

    class _RejectNC(AutoAcceptDelegate):
        async def confirm_numeric(self, peer_addr, value):
            return False

    stack_c._smp.set_delegate(_AcceptNC())
    stack_p._smp.set_delegate(_RejectNC())

    ad_data = _build_test_ad_data()
    await stack_p.gap.ble_advertiser.start(ad_data=ad_data)
    handle = None
    try:
        # Establish connection (virtual injection pattern in virtual mode;
        # hardware uses real LE advertising/scan).
        if link is not None:
            connect_task = asyncio.create_task(
                stack_c.connect_gatt(peripheral_addr, timeout=10.0)
            )
            await asyncio.sleep(0.1)
            await link.connect()
            client = await connect_task
        else:
            client = await stack_c.connect_gatt(peripheral_addr, timeout=10.0)
        handle = client._connection_handle

        # Pair must raise; reason matches "SMP pairing failed"
        with pytest.raises(Exception, match="SMP pairing failed"):
            await stack_c.pair(handle, timeout=5.0)

        # Critical assertion: cleanup completes within budget on each side.
        with contextlib.suppress(Exception):
            await asyncio.wait_for(
                stack_c.gap.ble_connections.disconnect(handle), timeout=e2e_timeout(transport_mode, virtual=2.0, usb=3.0),
            )
    finally:
        with contextlib.suppress(Exception):
            await stack_p.gap.ble_advertiser.stop()
        if link is not None:
            with contextlib.suppress(Exception):
                await link.disconnect()
        # The regression guard: stack.close() must complete within budget.
        await asyncio.wait_for(stack_c.close(), timeout=e2e_timeout(transport_mode, virtual=2.0, usb=3.0))
        await asyncio.wait_for(stack_p.close(), timeout=e2e_timeout(transport_mode, virtual=2.0, usb=3.0))
