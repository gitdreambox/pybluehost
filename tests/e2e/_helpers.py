"""Shared helpers for tests/e2e/ scenarios.

Discovery + capability + flow utilities. All are transport-agnostic.
"""
from __future__ import annotations

import asyncio
import time
from typing import Union

from pybluehost.ble.gap import ScanConfig
from pybluehost.ble.gatt import DiscoveredCharacteristic
from pybluehost.core.address import BDAddress
from pybluehost.core.uuid import UUID16, UUID128


# ---------------------------------------------------------------------------
# Capability gating
# ---------------------------------------------------------------------------

# Core Spec 5.4 Vol 4 Part E §6.27 Table 6.27 — Supported_Commands bitmap.
# These two LE Secure Connections commands sit at octet 34:
#   HCI_LE_Read_Local_P-256_Public_Key:  octet 34, bit 1
#   HCI_LE_Generate_DHKey:               octet 34, bit 2
_OCTET_LE_SC = 34
_BIT_LE_READ_LOCAL_P256_PK = 1
_BIT_LE_GENERATE_DHKEY = 2


def _supports_le_sc(stack) -> bool:
    """True iff the host can perform LE Secure Connections pairing.

    Virtual stacks always support SC (the SMP layer does ECDH in host code, not
    via controller P-256/DHKey HCI commands), so we short-circuit them. For
    real adapters we check the cached HCI Supported_Commands bitmap for the
    HCI_LE_Read_Local_P-256_Public_Key + HCI_LE_Generate_DHKey bits at
    octet 34. Older hardware (e.g. BT 4.0 dongles) lacks those commands and
    should be skipped.
    """
    # Virtual transport: SC pairing is executed by the host SMP module; the
    # virtual controller does not advertise the P-256/DHKey commands in its
    # Supported_Commands bitmap, but pairing still works end-to-end.
    if getattr(stack, "_virtual_controller", None) is not None:
        return True
    hci = getattr(stack, "_hci", None)
    if hci is None:
        return False
    caps = getattr(hci, "supported_commands", None)
    if caps is None:
        return False
    bitmap = getattr(caps, "bitmap", None)
    if bitmap is None or len(bitmap) <= _OCTET_LE_SC:
        return False
    p256 = bool(bitmap[_OCTET_LE_SC] & (1 << _BIT_LE_READ_LOCAL_P256_PK))
    dhkey = bool(bitmap[_OCTET_LE_SC] & (1 << _BIT_LE_GENERATE_DHKEY))
    return p256 and dhkey


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

async def central_discover_peripheral(
    stack_c, expected_addr: BDAddress, timeout: float = 5.0,
) -> None:
    """Start scanning, wait for an advertising report matching ``expected_addr``,
    then stop scanning.

    Raises asyncio.TimeoutError if no matching report arrives in time.
    """
    seen_event = asyncio.Event()

    def _on_result(result):
        if result.address == expected_addr:
            seen_event.set()

    gap = stack_c.gap
    gap.ble_scanner.on_result(_on_result)
    await gap.ble_scanner.start(ScanConfig())
    try:
        await asyncio.wait_for(seen_event.wait(), timeout=timeout)
    finally:
        await gap.ble_scanner.stop()


async def central_discover_and_pair_sc_jw(
    stack_c, expected_addr: BDAddress, *, scan_timeout: float = 5.0,
    pair_timeout: float = 20.0,
) -> tuple[object, int]:
    """Convenience composition: scan -> connect_gatt -> pair (SC Just Works).

    Returns (gatt_client, connection_handle).
    """
    await central_discover_peripheral(stack_c, expected_addr, timeout=scan_timeout)
    client = await stack_c.connect_gatt(expected_addr, timeout=scan_timeout)
    handle = client._connection_handle
    await stack_c.pair(handle, timeout=pair_timeout)
    return client, handle


# ---------------------------------------------------------------------------
# Notification waiter
# ---------------------------------------------------------------------------

async def wait_for_notifications(events: list, n: int, timeout: float = 1.0) -> None:
    """Block until ``len(events) >= n``; raise asyncio.TimeoutError otherwise."""
    deadline = time.monotonic() + timeout
    while len(events) < n:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise asyncio.TimeoutError(
                f"only received {len(events)}/{n} notifications within {timeout}s"
            )
        await asyncio.sleep(0.01)


# ---------------------------------------------------------------------------
# Handle resolution
# ---------------------------------------------------------------------------

def resolve_handles(
    chars: list[DiscoveredCharacteristic],
    labels: dict[str, Union[UUID16, UUID128]],
) -> dict[str, int]:
    """Given a discovered-characteristics list and a ``label -> UUID`` mapping,
    return a ``label -> value_handle`` mapping.

    Raises KeyError if any requested UUID was not discovered.
    """
    result: dict[str, int] = {}
    for label, uuid in labels.items():
        target = uuid.to_bytes()
        found = next((c for c in chars if c.uuid == target), None)
        if found is None:
            raise KeyError(f"characteristic {label!r} (uuid={uuid}) not discovered")
        result[label] = found.value_handle
    return result


# ---------------------------------------------------------------------------
# Classic (BR/EDR) helpers
# ---------------------------------------------------------------------------

def _supports_classic_ssp(stack) -> bool:
    """True iff the controller advertises BR/EDR SSP support.

    Virtual mode short-circuits True. Hardware adapters consult the HCI
    Read_Local_Supported_Commands bitmap for SSP opcodes
    (IO_Capability_Request_Reply at octet 32 bit 5 per Core Spec 5.4
    Vol 4 Part E §6.27).
    """
    if getattr(stack, "_virtual_controller", None) is not None:
        return True
    hci = getattr(stack, "_hci", None)
    if hci is None:
        return False
    caps = getattr(hci, "supported_commands", None)
    if caps is None:
        return False
    bitmap = getattr(caps, "bitmap", None) or caps
    try:
        return bool(bitmap[32] & (1 << 5))
    except (IndexError, TypeError):
        return False


async def classic_discover_peripheral(
    stack_c, expected_addr, timeout: float = 3.0,
) -> None:
    """Run inquiry on stack_c, wait until expected_addr appears in a result,
    then cancel.

    Mirrors the LE-side central_discover_peripheral but uses ClassicDiscovery.
    """
    import asyncio

    seen_event = asyncio.Event()

    def _on_result(info):
        # ClassicDiscovery results expose .address (or .bd_addr depending on
        # the dataclass spelling). Use a defensive check.
        addr = getattr(info, "address", None) or getattr(info, "bd_addr", None)
        if addr == expected_addr:
            seen_event.set()

    stack_c.gap.classic_discovery.on_result(_on_result)
    await stack_c.gap.classic_discovery.start()
    try:
        await asyncio.wait_for(seen_event.wait(), timeout=timeout)
    finally:
        # ClassicDiscovery exposes .stop() (not .cancel()) — issues HCI_Inquiry_Cancel.
        # Without this the inquiry leaks until the controller's inquiry-length timeout.
        if hasattr(stack_c.gap.classic_discovery, "stop"):
            try:
                await stack_c.gap.classic_discovery.stop()
            except Exception:
                pass


async def classic_discover_and_pair_jw(
    stack_c, peripheral_addr, *,
    scan_timeout: float = 3.0, pair_timeout: float = 3.0,
) -> int:
    """Composition: discover → connect_classic → authenticate_classic.

    Returns the connection handle on success.
    """
    await classic_discover_peripheral(stack_c, peripheral_addr, timeout=scan_timeout)
    handle = await stack_c.connect_classic(peripheral_addr, timeout=scan_timeout)
    await stack_c.authenticate_classic(handle, timeout=pair_timeout)
    return handle


# ---------------------------------------------------------------------------
# Transport-aware timeout helper (used by e2e scenarios)
# ---------------------------------------------------------------------------

def e2e_timeout(
    transport_mode: str,
    *,
    virtual: float,
    usb: float | None = None,
    uart: float | None = None,
) -> float:
    """Return a transport-appropriate timeout budget.

    Virtual transport completes operations in sub-second time; real RF needs
    more headroom for inquiry timing, page-scan windows, and connection setup.
    Defaults: usb = 5x virtual, uart = 8x virtual. Unknown transports fall
    back to the virtual budget.
    """
    if transport_mode == "virtual":
        return virtual
    if transport_mode == "usb":
        return usb if usb is not None else virtual * 5
    if transport_mode == "uart":
        return uart if uart is not None else virtual * 8
    return virtual
