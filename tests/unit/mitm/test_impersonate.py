"""Tests for pybluehost.cli.app.mitm.impersonate — BLE advertising impersonation."""

from pybluehost.cli.app.mitm.impersonate import (
    _addr_str_to_le_bytes,
    _build_adv_data_payload,
    start_impersonation,
)
from pybluehost.cli.app.mitm.recon import ClonedIdentity
from pybluehost.hci.virtual import VirtualController


def test_addr_str_to_le_bytes():
    assert _addr_str_to_le_bytes("AA:BB:CC:DD:EE:FF") == bytes.fromhex("ffeeddccbbaa")


def test_adv_data_payload_pads_to_32():
    payload = _build_adv_data_payload(bytes([0x02, 0x01, 0x06]))
    assert len(payload) == 32
    assert payload[0] == 3  # significant length
    assert payload[1:4] == bytes([0x02, 0x01, 0x06])


def test_adv_data_payload_truncates_oversized():
    payload = _build_adv_data_payload(bytes(40))
    assert len(payload) == 32
    assert payload[0] == 31  # truncated significant length


async def test_start_impersonation_smoke_virtual():
    vc, host_t = await VirtualController.create()
    from pybluehost.hci.controller import HCIController
    ctrl = HCIController(host_t)
    await host_t.open()
    await ctrl.initialize()
    ident = ClonedIdentity(address="AA:BB:CC:DD:EE:FF", address_type=0,
                           adv_data=bytes([0x02, 0x01, 0x06, 0x06, 0x09]) + b"Watch",
                           scan_response=b"", name="Watch")
    # Should issue the advertising command sequence without raising:
    await start_impersonation(ctrl, ident, clone_address=False)
    # clone_address path should also not raise:
    await start_impersonation(ctrl, ident, clone_address=True)
    close = getattr(host_t, "close", None)
    if close:
        res = close()
        if hasattr(res, "__await__"):
            await res
