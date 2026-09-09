"""Remote Name Request behavior of inquiry_for_target: RNR is issued even
without target_name.

A transparent MITM needs the target's real name to clone the local name;
when matching by address only (target_name=None), RNR must still be issued,
otherwise impersonation skips writing the name and the dongle advertises an
empty name that the phone does not display.

Also covers inquiry re-scan loops: a single 10s round window is too harsh
for real earbuds that are only intermittently discoverable (the JBL pairing
mode window is short), so recon must re-scan over multiple rounds within the
total budget, giving the operator time to re-trigger pairing mode instead of
exiting the whole script when nothing is found.
"""
import asyncio

import pytest

from pybluehost.cli.app.mitm.bredr_recon import inquiry_for_target
from pybluehost.hci.constants import (
    HCI_INQUIRY,
    HCI_INQUIRY_CANCEL,
    HCI_REMOTE_NAME_REQUEST,
    EventCode,
)
from pybluehost.hci.packets import HCICommand, HCIEvent

# Target address (big-endian string) and little-endian bytes
TARGET = "98:1D:F9:90:11:1E"
TARGET_LE = bytes.fromhex(TARGET.replace(":", ""))[::-1]
_EVENT_EXTENDED_INQUIRY_RESULT = 0x2F


class FakeReconController:
    def __init__(self):
        self._on_hci_event = None
        self._on_acl_data = None
        self._on_sco_data = None
        self.sent: list[HCICommand] = []

    def set_upstream(self, on_hci_event=None, on_acl_data=None, on_sco_data=None):
        self._on_hci_event = on_hci_event
        self._on_acl_data = on_acl_data
        self._on_sco_data = on_sco_data

    async def send_command(self, command):
        self.sent.append(command)

    def inject_eir_no_name(self):
        # num=1, addr(6 LE), psrm(1), reserved(1), cod(3), clock(2), rssi(1), eir(240 all zero)
        params = (
            bytes([0x01]) + TARGET_LE + b"\x01\x00" + b"\x24\x04\x0c"
            + b"\x00\x00" + b"\xc8" + bytes(240)
        )
        self._on_hci_event(
            HCIEvent.from_bytes(_EVENT_EXTENDED_INQUIRY_RESULT, params)
        )

    def inject_rnr_complete(self, name=b"WQ7035_2223"):
        params = bytes([0x00]) + TARGET_LE + name + bytes(248 - len(name))
        self._on_hci_event(
            HCIEvent.from_bytes(EventCode.REMOTE_NAME_REQUEST_COMPLETE, params)
        )


async def test_rnr_issued_even_without_target_name():
    """target_addr matched, EIR has no name, target_name=None -> RNR is still issued and the real name returned."""
    ctl = FakeReconController()
    task = asyncio.ensure_future(
        inquiry_for_target(ctl, target_addr=TARGET, target_name=None, timeout=5.0)
    )
    await asyncio.sleep(0)  # let the inquiry go out and the hook be installed
    assert any(c.opcode == HCI_INQUIRY for c in ctl.sent)

    ctl.inject_eir_no_name()  # address matched, EIR has no name
    await asyncio.sleep(0.05)  # let it enter the RNR branch
    opcodes = [c.opcode for c in ctl.sent]
    assert HCI_REMOTE_NAME_REQUEST in opcodes, \
        "EIR 无名时即使 target_name=None 也应发 RNR"
    # Intel controller rejects RNR (0x0C) while inquiry is running; must cancel inquiry before RNR
    assert HCI_INQUIRY_CANCEL in opcodes
    assert opcodes.index(HCI_INQUIRY_CANCEL) < opcodes.index(HCI_REMOTE_NAME_REQUEST), \
        "RNR 前必须先取消仍在进行的 inquiry"

    ctl.inject_rnr_complete()
    ident = await asyncio.wait_for(task, 2.0)
    assert ident.address == TARGET
    assert ident.name == "WQ7035_2223"
    assert any(c.opcode == HCI_INQUIRY_CANCEL for c in ctl.sent)


async def test_inquiry_retries_later_round_until_match():
    """First round finds nothing -> proceed to the next inquiry round; a later-round match returns the identity normally."""
    ctl = FakeReconController()
    task = asyncio.ensure_future(
        inquiry_for_target(ctl, target_addr=TARGET, target_name=None,
                           timeout=0.2, total_timeout=2.0)
    )
    await asyncio.sleep(0)
    assert sum(1 for c in ctl.sent if c.opcode == HCI_INQUIRY) == 1

    await asyncio.sleep(0.4)  # let round 1 (0.2s) time out and round 2 go out
    assert sum(1 for c in ctl.sent if c.opcode == HCI_INQUIRY) >= 2, \
        "第一轮未命中应继续发新一轮 inquiry"

    ctl.inject_eir_no_name()   # matched in round 2
    await asyncio.sleep(0.05)
    ctl.inject_rnr_complete()
    ident = await asyncio.wait_for(task, 2.0)
    assert ident.address == TARGET
    assert ident.name == "WQ7035_2223"


async def test_inquiry_total_timeout_raises_after_multiple_rounds():
    """Total budget exhausted without a match -> raises TimeoutError after re-scanning multiple rounds (not abandoning after a single round)."""
    ctl = FakeReconController()
    with pytest.raises(TimeoutError):
        await inquiry_for_target(ctl, target_addr=TARGET, target_name=None,
                                 timeout=0.2, total_timeout=0.5)
    n_inquiry = sum(1 for c in ctl.sent if c.opcode == HCI_INQUIRY)
    assert n_inquiry >= 2, f"总预算内应重扫多轮,实际只发了 {n_inquiry} 轮"
