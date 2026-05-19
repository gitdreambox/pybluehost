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
