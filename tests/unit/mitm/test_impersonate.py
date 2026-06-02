"""Tests for pybluehost.cli.app.mitm.impersonate — BLE advertising impersonation."""

from pybluehost.cli.app.mitm.impersonate import start_impersonation, _addr_str_to_le_bytes
from pybluehost.cli.app.mitm.recon import ClonedIdentity
from pybluehost.hci.virtual import VirtualController


def test_addr_str_to_le_bytes():
    assert _addr_str_to_le_bytes("AA:BB:CC:DD:EE:FF") == bytes.fromhex("ffeeddccbbaa")


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
