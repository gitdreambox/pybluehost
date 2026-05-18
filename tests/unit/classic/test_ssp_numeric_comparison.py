"""Sub-Plan 3a: SSPManager delegate dispatch for BR/EDR Numeric Comparison."""
from __future__ import annotations

import asyncio

import pytest

from pybluehost.classic.gap import SSPManager
from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import EventCode
from pybluehost.hci.packets import HCIEvent


# HCICommand.to_bytes() layout: H4(0x01) + opcode(2 LE) + plen(1) + params.
# Opcodes (LE on wire):
#   HCI_USER_CONFIRMATION_REQUEST_REPLY          = 0x042C  -> bytes 1..3 = b"\x2C\x04"
#   HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY = 0x042D  -> bytes 1..3 = b"\x2D\x04"
_OPCODE_REPLY_LE = bytes.fromhex("2C04")
_OPCODE_NEG_REPLY_LE = bytes.fromhex("2D04")


class _FakeHCI:
    def __init__(self) -> None:
        self.commands: list[bytes] = []

    async def send_command(self, pkt: object) -> object:
        raw = pkt.to_bytes() if hasattr(pkt, "to_bytes") else bytes(pkt)
        self.commands.append(raw)
        return object()


class _CapturingDelegate:
    def __init__(self, accept: bool = True) -> None:
        self.accept = accept
        self.calls: list[tuple] = []

    async def confirm_numeric(self, peer_addr: BDAddress, value: int) -> bool:
        self.calls.append((peer_addr, value))
        return self.accept


def _make_user_confirmation_event(addr_bytes: bytes, numeric: int) -> HCIEvent:
    params = addr_bytes + numeric.to_bytes(4, "little")
    return HCIEvent(
        event_code=int(EventCode.USER_CONFIRMATION_REQUEST), parameters=params
    )


async def _drain() -> None:
    """Yield enough for _schedule_reply'd tasks (delegate await + HCI send) to run."""
    for _ in range(10):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_ssp_user_confirmation_calls_delegate_confirm_numeric() -> None:
    hci = _FakeHCI()
    delegate = _CapturingDelegate(accept=True)
    ssp = SSPManager(hci=hci, delegate=delegate)
    addr_bytes = bytes.fromhex("010203040506")
    await ssp.on_hci_event(_make_user_confirmation_event(addr_bytes, 314159))
    await _drain()
    assert delegate.calls == [(BDAddress(addr_bytes), 314159)]
    # Positive reply: opcode 0x042C at bytes 1..3 of the H4-framed command.
    assert any(cmd[1:3] == _OPCODE_REPLY_LE for cmd in hci.commands)
    assert not any(cmd[1:3] == _OPCODE_NEG_REPLY_LE for cmd in hci.commands)


@pytest.mark.asyncio
async def test_ssp_user_confirmation_negative_reply_when_delegate_rejects() -> None:
    hci = _FakeHCI()
    delegate = _CapturingDelegate(accept=False)
    ssp = SSPManager(hci=hci, delegate=delegate)
    addr_bytes = bytes.fromhex("AABBCCDDEEFF")
    await ssp.on_hci_event(_make_user_confirmation_event(addr_bytes, 42))
    await _drain()
    assert delegate.calls == [(BDAddress(addr_bytes), 42)]
    # Negative reply: opcode 0x042D at bytes 1..3.
    assert any(cmd[1:3] == _OPCODE_NEG_REPLY_LE for cmd in hci.commands)
    assert not any(cmd[1:3] == _OPCODE_REPLY_LE for cmd in hci.commands)


@pytest.mark.asyncio
async def test_ssp_user_confirmation_auto_accepts_when_no_delegate() -> None:
    """Backward compat: SSPManager with no delegate auto-accepts."""
    hci = _FakeHCI()
    ssp = SSPManager(hci=hci)  # No delegate
    await ssp.on_hci_event(_make_user_confirmation_event(bytes(6), 1))
    await _drain()
    assert any(cmd[1:3] == _OPCODE_REPLY_LE for cmd in hci.commands)


@pytest.mark.asyncio
async def test_ssp_user_confirmation_legacy_sync_handler_still_works() -> None:
    """Backward compat: when no delegate but legacy on_user_confirmation handler is set,
    SSPManager honours its return value."""
    hci = _FakeHCI()
    ssp = SSPManager(hci=hci)
    seen: list[tuple] = []

    def _handler(addr: BDAddress, value: int) -> bool:
        seen.append((addr, value))
        return False  # reject

    ssp.on_user_confirmation(_handler)
    addr_bytes = bytes.fromhex("0102030405AA")
    await ssp.on_hci_event(_make_user_confirmation_event(addr_bytes, 7))
    await _drain()
    assert seen == [(BDAddress(addr_bytes), 7)]
    assert any(cmd[1:3] == _OPCODE_NEG_REPLY_LE for cmd in hci.commands)


@pytest.mark.asyncio
async def test_ssp_user_confirmation_delegate_exception_denies() -> None:
    """If the delegate raises, the request must be rejected (fail closed)."""
    hci = _FakeHCI()

    class _BoomDelegate:
        async def confirm_numeric(self, *_a, **_kw):
            raise RuntimeError("boom")

    ssp = SSPManager(hci=hci, delegate=_BoomDelegate())
    await ssp.on_hci_event(_make_user_confirmation_event(bytes(6), 0))
    await _drain()
    assert any(cmd[1:3] == _OPCODE_NEG_REPLY_LE for cmd in hci.commands)
