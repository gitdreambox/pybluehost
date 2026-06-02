"""Unit tests for SspTermination (BR/EDR Secure Simple Pairing HCI termination)."""
from __future__ import annotations

import pytest

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import (
    HCI_IO_CAPABILITY_REQUEST_REPLY,
    HCI_USER_CONFIRMATION_REQUEST_REPLY,
    HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY,
    HCI_LINK_KEY_REQUEST_REPLY,
    HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY,
)
from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate
from pybluehost.cli.app.mitm.pairing.ssp import (
    SspTermination,
    IOCAP_DISPLAY_YESNO,
    IOCAP_NO_INPUT_NO_OUTPUT,
)


# ---------------------------------------------------------------------------
# Fake controller
# ---------------------------------------------------------------------------

class FakeController:
    """Minimal fake that records listener registrations and send_command calls."""

    def __init__(self) -> None:
        self._io_listeners: list = []
        self._uc_listeners: list = []
        self._lkn_listeners: list = []
        self._lkr_listeners: list = []
        self.sent: list[tuple[int, bytes]] = []  # (opcode, parameters)

    def on_io_capability_request(self, listener) -> None:
        self._io_listeners.append(listener)

    def on_user_confirmation_request(self, listener) -> None:
        self._uc_listeners.append(listener)

    def on_link_key_notification(self, listener) -> None:
        self._lkn_listeners.append(listener)

    def on_link_key_request(self, listener) -> None:
        self._lkr_listeners.append(listener)

    async def send_command(self, cmd) -> None:
        self.sent.append((cmd.opcode, cmd.parameters))

    # Helpers to fire events (mirrors controller dispatch logic)
    async def fire_io(self, addr: BDAddress) -> None:
        import asyncio
        for listener in list(self._io_listeners):
            result = listener(addr)
            if asyncio.iscoroutine(result):
                await result

    async def fire_uc(self, addr: BDAddress, value: int) -> None:
        import asyncio
        for listener in list(self._uc_listeners):
            result = listener(addr, value)
            if asyncio.iscoroutine(result):
                await result

    async def fire_lkn(self, addr: BDAddress, key: bytes, key_type: int) -> None:
        import asyncio
        for listener in list(self._lkn_listeners):
            result = listener(addr, key, key_type)
            if asyncio.iscoroutine(result):
                await result

    async def fire_lkr(self, addr: BDAddress) -> None:
        import asyncio
        for listener in list(self._lkr_listeners):
            result = listener(addr)
            if asyncio.iscoroutine(result):
                await result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ADDR = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
_ADDR_BYTES = _ADDR.address  # 6 bytes used as bd_addr in params

_LINK_KEY = bytes(range(16))  # 16-byte test key


class _RejectDelegate:
    async def confirm_numeric(self, side_name: str, value: int) -> bool:
        return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_attach_registers_all_four_listeners():
    ctrl = FakeController()
    ssp = SspTermination(ctrl, delegate=AutoConfirmDelegate(), side_name="side-A")
    ssp.attach()
    assert len(ctrl._io_listeners) == 1
    assert len(ctrl._uc_listeners) == 1
    assert len(ctrl._lkn_listeners) == 1
    assert len(ctrl._lkr_listeners) == 1


async def test_io_capability_just_works_sends_nino():
    """Just Works (numeric=False) → NoInputNoOutput (0x03), auth_req=0x02."""
    ctrl = FakeController()
    ssp = SspTermination(ctrl, delegate=AutoConfirmDelegate(), side_name="side-A", numeric=False)
    ssp.attach()
    await ctrl.fire_io(_ADDR)

    assert len(ctrl.sent) == 1
    opcode, params = ctrl.sent[0]
    assert opcode == HCI_IO_CAPABILITY_REQUEST_REPLY
    # bd_addr prefix
    assert params[:6] == _ADDR_BYTES
    # io_cap byte
    assert params[6] == IOCAP_NO_INPUT_NO_OUTPUT
    # oob_data_present
    assert params[7] == 0x00
    # authentication_requirements: 0x02 (dedicated bonding, MITM not required)
    assert params[8] == 0x02


async def test_io_capability_numeric_sends_display_yes_no():
    """Numeric comparison (numeric=True) → DisplayYesNo (0x01), auth_req=0x03."""
    ctrl = FakeController()
    ssp = SspTermination(ctrl, delegate=AutoConfirmDelegate(), side_name="side-A", numeric=True)
    ssp.attach()
    await ctrl.fire_io(_ADDR)

    assert len(ctrl.sent) == 1
    opcode, params = ctrl.sent[0]
    assert opcode == HCI_IO_CAPABILITY_REQUEST_REPLY
    assert params[:6] == _ADDR_BYTES
    assert params[6] == IOCAP_DISPLAY_YESNO
    assert params[7] == 0x00
    # authentication_requirements: 0x03 (dedicated bonding, MITM required)
    assert params[8] == 0x03


async def test_user_confirmation_auto_confirm_sends_reply():
    """AutoConfirmDelegate → USER_CONFIRMATION_REQUEST_REPLY."""
    ctrl = FakeController()
    ssp = SspTermination(ctrl, delegate=AutoConfirmDelegate(), side_name="side-A")
    ssp.attach()
    await ctrl.fire_uc(_ADDR, 123456)

    assert len(ctrl.sent) == 1
    opcode, params = ctrl.sent[0]
    assert opcode == HCI_USER_CONFIRMATION_REQUEST_REPLY
    assert params[:6] == _ADDR_BYTES


async def test_user_confirmation_reject_sends_negative_reply():
    """RejectDelegate → USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY."""
    ctrl = FakeController()
    ssp = SspTermination(ctrl, delegate=_RejectDelegate(), side_name="side-A")
    ssp.attach()
    await ctrl.fire_uc(_ADDR, 999999)

    assert len(ctrl.sent) == 1
    opcode, params = ctrl.sent[0]
    assert opcode == HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY
    assert params[:6] == _ADDR_BYTES


async def test_link_key_store_and_reply_known_addr():
    """Store link key via lkn, then lkr with same addr → LINK_KEY_REQUEST_REPLY."""
    ctrl = FakeController()
    ssp = SspTermination(ctrl, delegate=AutoConfirmDelegate(), side_name="side-A")
    ssp.attach()

    # Store the key (sync, no send)
    await ctrl.fire_lkn(_ADDR, _LINK_KEY, key_type=0)
    assert len(ctrl.sent) == 0

    # Request → should reply with stored key
    await ctrl.fire_lkr(_ADDR)
    assert len(ctrl.sent) == 1
    opcode, params = ctrl.sent[0]
    assert opcode == HCI_LINK_KEY_REQUEST_REPLY
    # Link_Key_Request_Reply 用专用 command 类,bd_addr 反转为小端 wire(同 classic/gap.py)
    assert params[:6] == _ADDR.address[::-1]
    assert params[6:22] == _LINK_KEY


async def test_link_key_request_unknown_addr_negative_reply():
    """lkr for an address with no stored key → LINK_KEY_REQUEST_NEGATIVE_REPLY."""
    ctrl = FakeController()
    ssp = SspTermination(ctrl, delegate=AutoConfirmDelegate(), side_name="side-A")
    ssp.attach()

    unknown = BDAddress.from_string("11:22:33:44:55:66")
    await ctrl.fire_lkr(unknown)
    assert len(ctrl.sent) == 1
    opcode, params = ctrl.sent[0]
    assert opcode == HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY
    assert params[:6] == unknown.address


async def test_link_key_store_multiple_addrs():
    """Keys for two addresses are stored and retrieved independently."""
    ctrl = FakeController()
    ssp = SspTermination(ctrl, delegate=AutoConfirmDelegate(), side_name="side-A")
    ssp.attach()

    addr1 = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
    addr2 = BDAddress.from_string("11:22:33:44:55:66")
    key1 = bytes(range(16))
    key2 = bytes(reversed(range(16)))

    await ctrl.fire_lkn(addr1, key1, key_type=0)
    await ctrl.fire_lkn(addr2, key2, key_type=4)

    await ctrl.fire_lkr(addr1)
    opcode, params = ctrl.sent[0]
    assert opcode == HCI_LINK_KEY_REQUEST_REPLY
    assert params[6:22] == key1

    await ctrl.fire_lkr(addr2)
    opcode, params = ctrl.sent[1]
    assert opcode == HCI_LINK_KEY_REQUEST_REPLY
    assert params[6:22] == key2
