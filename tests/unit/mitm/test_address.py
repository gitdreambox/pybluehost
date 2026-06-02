import pytest
from pybluehost.cli.app.mitm.address import (
    AddressCloneUnsupported, build_broadcom_write_bdaddr, clone_bd_addr, _addr_str_to_le_bytes,
)


class _FakeCtrl:
    def __init__(self, mfr): self._mfr = mfr; self.sent = []
    def manufacturer_id(self): return self._mfr
    async def send_command(self, cmd): self.sent.append(cmd)


def test_addr_to_le():
    assert _addr_str_to_le_bytes("AA:BB:CC:DD:EE:FF") == bytes.fromhex("ffeeddccbbaa")


def test_build_broadcom_write_bdaddr():
    cmd = build_broadcom_write_bdaddr("AA:BB:CC:DD:EE:FF")
    assert cmd.opcode == 0xFC01
    assert cmd.parameters == bytes.fromhex("ffeeddccbbaa")


async def test_clone_broadcom_sends_command():
    ctrl = _FakeCtrl(0x000F)
    await clone_bd_addr(ctrl, "AA:BB:CC:DD:EE:FF")
    assert len(ctrl.sent) == 1 and ctrl.sent[0].opcode == 0xFC01


async def test_clone_intel_raises():
    ctrl = _FakeCtrl(0x0002)
    with pytest.raises(AddressCloneUnsupported):
        await clone_bd_addr(ctrl, "AA:BB:CC:DD:EE:FF")


async def test_clone_unknown_raises():
    ctrl = _FakeCtrl(None)
    with pytest.raises(AddressCloneUnsupported):
        await clone_bd_addr(ctrl, "AA:BB:CC:DD:EE:FF")
