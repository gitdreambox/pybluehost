from pybluehost.cli.app.mitm.bredr_impersonate import (
    _name_to_padded,
    _rewrite_eir_name,
    start_bredr_impersonation,
)
from pybluehost.cli.app.mitm.recon import ClonedIdentity, parse_adv_name
from pybluehost.hci.constants import (
    HCI_WRITE_CLASS_OF_DEVICE,
    HCI_WRITE_EXTENDED_INQUIRY_RESPONSE,
    HCI_WRITE_INQUIRY_SCAN_ACTIVITY,
    HCI_WRITE_LOCAL_NAME,
    HCI_WRITE_PAGE_SCAN_ACTIVITY,
    HCI_WRITE_SCAN_ENABLE,
    HCI_WRITE_SIMPLE_PAIRING_MODE,
)


class _FakeCtrl:
    def __init__(self): self.sent = []
    async def send_command(self, cmd): self.sent.append(cmd)


def test_name_padded():
    p = _name_to_padded("Phone", 248)
    assert len(p) == 248 and p[:5] == b"Phone" and p[5] == 0


# --- _rewrite_eir_name: EIR name override (key to --downstream-name taking effect on the phone scan list) ---

def test_rewrite_eir_name_replaces_complete_name():
    # original EIR: flags + Complete Local Name "Old"
    old = bytes([0x02, 0x01, 0x06, 0x04, 0x09]) + b"Old"
    new = _rewrite_eir_name(old, "NewName")
    assert parse_adv_name(new) == "NewName"
    # flags structure preserved as-is
    assert bytes([0x02, 0x01, 0x06]) in new


def test_rewrite_eir_name_none_returns_unchanged():
    old = bytes([0x04, 0x09]) + b"Old"
    assert _rewrite_eir_name(old, None) is old


def test_rewrite_eir_name_appends_when_absent():
    # no name field: append a Complete Local Name if there is room
    old = bytes([0x02, 0x01, 0x06])
    new = _rewrite_eir_name(old, "Added")
    assert parse_adv_name(new) == "Added"


def test_rewrite_eir_name_truncates_to_240():
    # fill other structures + overlong name -> total length still <= 240
    filler = bytes([0xE1, 0xFF]) + bytes(0xE1 - 1)  # one big structure occupying 227 bytes
    new = _rewrite_eir_name(filler, "X" * 100)
    assert len(new) <= 240
    assert parse_adv_name(new) is not None


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
    # SSP enable = 0x01 (without SSP, phone pairing fails and disconnects — real-device G3 verified)
    ssp_cmd = next(c for c in ctrl.sent if c.opcode == HCI_WRITE_SIMPLE_PAIRING_MODE)
    assert ssp_cmd.parameters == bytes([0x01])


async def test_impersonation_enables_ssp_even_when_name_none():
    """Even with no name to write, SSP must be enabled (pairing depends on it)."""
    ctrl = _FakeCtrl()
    ident = ClonedIdentity(address="AA:BB:CC:DD:EE:FF", address_type=0,
                           adv_data=b"", scan_response=b"", name=None)
    await start_bredr_impersonation(ctrl, ident, clone_address=False)
    ssp = next(c for c in ctrl.sent if c.opcode == HCI_WRITE_SIMPLE_PAIRING_MODE)
    assert ssp.parameters == bytes([0x01])


async def test_impersonation_skips_name_when_none():
    ctrl = _FakeCtrl()
    ident = ClonedIdentity(address="AA:BB:CC:DD:EE:FF", address_type=0,
                           adv_data=b"", scan_response=b"", name=None)
    await start_bredr_impersonation(ctrl, ident, clone_address=False)
    assert HCI_WRITE_LOCAL_NAME not in [c.opcode for c in ctrl.sent]


async def test_impersonation_eir_carries_override_name():
    """--downstream-name must be synced into the EIR (the phone scan list shows the EIR name, not the local name).

    The cloned EIR carries the target's old name; after the override, the name
    field in the EIR must also be replaced with the new name, otherwise the
    phone still sees the old name when scanning.
    """
    ctrl = _FakeCtrl()
    # cloned EIR holds the old name "JBL Live Beam 4"; override to "JBL Live MITM 4"
    eir = bytes([0x11, 0x09]) + b"JBL Live Beam 4"
    ident = ClonedIdentity(address="AA:BB:CC:DD:EE:FF", address_type=0,
                           adv_data=eir, scan_response=b"", name="JBL Live MITM 4")
    await start_bredr_impersonation(ctrl, ident, clone_address=False)
    eir_cmd = next(c for c in ctrl.sent if c.opcode == HCI_WRITE_EXTENDED_INQUIRY_RESPONSE)
    eir_bytes = eir_cmd.parameters[1:241]  # skip the fec byte
    assert parse_adv_name(eir_bytes) == "JBL Live MITM 4"
    assert b"JBL Live Beam 4" not in eir_bytes


async def test_impersonation_sets_fast_scan_activity():
    """inquiry/page scan use high duty cycle (interval==window=0x0028=25ms) so the phone finds it instantly.

    The controller's default scan window is small (~11-18ms/1.28s), so the
    impersonating device is often not found or found slowly; the MITM scenario
    does not care about power, so max it out.
    """
    ctrl = _FakeCtrl()
    ident = ClonedIdentity(address="AA:BB:CC:DD:EE:FF", address_type=0,
                           adv_data=b"", scan_response=b"", name=None)
    await start_bredr_impersonation(ctrl, ident, clone_address=False)
    for opcode in (HCI_WRITE_INQUIRY_SCAN_ACTIVITY, HCI_WRITE_PAGE_SCAN_ACTIVITY):
        cmd = next((c for c in ctrl.sent if c.opcode == opcode), None)
        assert cmd is not None, f"缺少 opcode {opcode:#06x}"
        # interval(2,LE) + window(2,LE),interval == window == 0x0028
        assert cmd.parameters == (0x0028).to_bytes(2, "little") + (0x0028).to_bytes(2, "little")
