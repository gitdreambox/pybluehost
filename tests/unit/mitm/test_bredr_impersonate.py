from pybluehost.cli.app.mitm.bredr_impersonate import start_bredr_impersonation, _name_to_padded
from pybluehost.cli.app.mitm.recon import ClonedIdentity
from pybluehost.hci.constants import (
    HCI_WRITE_CLASS_OF_DEVICE,
    HCI_WRITE_EXTENDED_INQUIRY_RESPONSE,
    HCI_WRITE_LOCAL_NAME,
    HCI_WRITE_SCAN_ENABLE,
)


class _FakeCtrl:
    def __init__(self): self.sent = []
    async def send_command(self, cmd): self.sent.append(cmd)


def test_name_padded():
    p = _name_to_padded("Phone", 248)
    assert len(p) == 248 and p[:5] == b"Phone" and p[5] == 0


async def test_impersonation_writes_cod_eir_name_scan():
    ctrl = _FakeCtrl()
    ident = ClonedIdentity(address="AA:BB:CC:DD:EE:FF", address_type=0,
                           adv_data=bytes([0x05, 0x09]) + b"Phon", scan_response=b"",
                           name="Phon", class_of_device=0x5A020C)
    await start_bredr_impersonation(ctrl, ident, clone_address=False)
    opcodes = [c.opcode for c in ctrl.sent]
    assert HCI_WRITE_CLASS_OF_DEVICE in opcodes
    assert HCI_WRITE_EXTENDED_INQUIRY_RESPONSE in opcodes
    assert HCI_WRITE_LOCAL_NAME in opcodes
    assert HCI_WRITE_SCAN_ENABLE in opcodes
    # CoD is 3 LE bytes
    cod_cmd = next(c for c in ctrl.sent if c.opcode == HCI_WRITE_CLASS_OF_DEVICE)
    assert cod_cmd.parameters == (0x5A020C).to_bytes(3, "little")
    # scan enable = 0x03
    scan_cmd = next(c for c in ctrl.sent if c.opcode == HCI_WRITE_SCAN_ENABLE)
    assert scan_cmd.parameters == bytes([0x03])


async def test_impersonation_skips_name_when_none():
    ctrl = _FakeCtrl()
    ident = ClonedIdentity(address="AA:BB:CC:DD:EE:FF", address_type=0,
                           adv_data=b"", scan_response=b"", name=None)
    await start_bredr_impersonation(ctrl, ident, clone_address=False)
    assert HCI_WRITE_LOCAL_NAME not in [c.opcode for c in ctrl.sent]
