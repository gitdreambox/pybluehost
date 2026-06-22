"""Shared helpers for BLE peripheral demo applications."""
from __future__ import annotations

from collections.abc import Iterable
import struct

from pybluehost.ble.gap import _make_cmd
from pybluehost.ble.gap import AdvertisingConfig
from pybluehost.core.address import AddressType, BDAddress
from pybluehost.core.gap_common import AdvertisingData
from pybluehost.hci.constants import (
    ErrorCode,
    HCI_LE_SET_ADVERTISE_ENABLE,
    HCI_LE_SET_ADVERTISING_DATA,
    HCI_LE_SET_ADVERTISING_PARAMS,
    HCI_LE_SET_SCAN_RESPONSE_DATA,
)
from pybluehost.hci.packets import HCI_Command_Complete_Event


def build_ble_advertising_data(service_uuids: Iterable[int], *, local_name: str | None = None) -> AdvertisingData:
    ad = AdvertisingData()
    ad.set_flags(0x06)
    for uuid in service_uuids:
        ad.add_service_uuid16(uuid)
    if local_name:
        ad.set_complete_local_name(local_name)
    return ad


def build_ble_scan_response(local_name: str) -> AdvertisingData:
    scan_rsp = AdvertisingData()
    scan_rsp.set_complete_local_name(local_name)
    return scan_rsp


async def start_connectable_advertising(
    stack: object,
    *,
    service_uuids: Iterable[int],
    local_name: str,
) -> None:
    advertiser = getattr(getattr(stack, "gap", None), "ble_advertiser", None)
    if advertiser is None:
        raise RuntimeError("BLE advertiser is not available")
    await advertiser.start(
        config=AdvertisingConfig(adv_type=0x00),
        ad_data=build_ble_advertising_data(service_uuids, local_name=local_name),
        scan_rsp_data=build_ble_scan_response(local_name),
    )


async def stop_advertising(stack: object) -> None:
    advertiser = getattr(getattr(stack, "gap", None), "ble_advertiser", None)
    if advertiser is not None:
        await advertiser.stop()


def _legacy_address_type(value: str) -> AddressType:
    normalized = value.strip().lower().replace("-", "_")
    if normalized == "public":
        return AddressType.PUBLIC
    if normalized == "random":
        return AddressType.RANDOM
    raise ValueError(f"legacy directed advertising supports public/random address types, got {value!r}")


def _legacy_direct_peer_address_type(address: BDAddress) -> AddressType:
    if int(address.type) in (int(AddressType.RANDOM), int(AddressType.RANDOM_IDENTITY)):
        return AddressType.RANDOM
    return AddressType.PUBLIC


def _legacy_adv_interval_units(interval_ms: float) -> int:
    if interval_ms <= 0:
        raise ValueError("advertising interval must be positive")
    units = int(interval_ms / 0.625)
    return max(0x0020, min(0x4000, units))


def _ensure_hci_success(
    event: object,
    opcode: int,
    *,
    allowed_statuses: set[int] | None = None,
) -> None:
    if not isinstance(event, HCI_Command_Complete_Event):
        return
    if not event.return_parameters:
        return
    status = event.return_parameters[0]
    allowed = allowed_statuses or {int(ErrorCode.SUCCESS)}
    if status in allowed:
        return
    try:
        status_name = ErrorCode(status).name
    except ValueError:
        status_name = f"0x{status:02X}"
    raise RuntimeError(f"HCI command 0x{opcode:04X} failed: {status_name} (0x{status:02X})")


async def start_directed_advertising(
    hci: object,
    *,
    peer_address: str | BDAddress,
    peer_address_type: str = "public",
    own_address_type: str = "public",
    duty: str = "low",
    interval_ms: float = 100.0,
) -> None:
    """Start legacy directed advertising toward one peer.

    The helper deliberately clears legacy advertising and scan-response data
    before switching to ADV_DIRECT_IND, so stale ordinary advertising payloads
    cannot leak into the directed phase.
    """
    own_type = _legacy_address_type(own_address_type)
    if isinstance(peer_address, BDAddress):
        peer = peer_address
    else:
        peer = BDAddress.from_string(peer_address, _legacy_address_type(peer_address_type))
    peer_type = _legacy_direct_peer_address_type(peer)

    duty_normalized = duty.strip().lower()
    if duty_normalized == "high":
        adv_type = 0x01
    elif duty_normalized == "low":
        adv_type = 0x04
    else:
        raise ValueError(f"directed advertising duty must be 'low' or 'high', got {duty!r}")

    interval = _legacy_adv_interval_units(interval_ms)

    _ensure_hci_success(
        await hci.send_command(_make_cmd(HCI_LE_SET_ADVERTISE_ENABLE, b"\x00")),
        HCI_LE_SET_ADVERTISE_ENABLE,
        allowed_statuses={int(ErrorCode.SUCCESS), int(ErrorCode.COMMAND_DISALLOWED)},
    )
    for opcode, params_to_send in (
        (HCI_LE_SET_ADVERTISING_DATA, bytes(32)),
        (HCI_LE_SET_SCAN_RESPONSE_DATA, bytes(32)),
    ):
        _ensure_hci_success(await hci.send_command(_make_cmd(opcode, params_to_send)), opcode)

    params = struct.pack(
        "<HHBBB6sBB",
        interval,
        interval,
        adv_type,
        int(own_type),
        int(peer_type),
        peer.to_hci(),
        0x07,
        0x00,
    )
    _ensure_hci_success(
        await hci.send_command(_make_cmd(HCI_LE_SET_ADVERTISING_PARAMS, params)),
        HCI_LE_SET_ADVERTISING_PARAMS,
    )
    _ensure_hci_success(
        await hci.send_command(_make_cmd(HCI_LE_SET_ADVERTISE_ENABLE, b"\x01")),
        HCI_LE_SET_ADVERTISE_ENABLE,
    )
