"""Shared helpers for BLE peripheral demo applications."""
from __future__ import annotations

from collections.abc import Iterable

from pybluehost.ble.gap import AdvertisingConfig
from pybluehost.core.gap_common import AdvertisingData


def build_ble_advertising_data(service_uuids: Iterable[int]) -> AdvertisingData:
    ad = AdvertisingData()
    ad.set_flags(0x06)
    for uuid in service_uuids:
        ad.add_service_uuid16(uuid)
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
        ad_data=build_ble_advertising_data(service_uuids),
        scan_rsp_data=build_ble_scan_response(local_name),
    )


async def stop_advertising(stack: object) -> None:
    advertiser = getattr(getattr(stack, "gap", None), "ble_advertiser", None)
    if advertiser is not None:
        await advertiser.stop()
