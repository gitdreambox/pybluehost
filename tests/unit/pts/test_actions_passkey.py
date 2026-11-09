"""Legacy Passkey-Entry plumbing: IutActions.submit_passkey + _PtsSmpDelegate.

Covers the SM/*/PKE enablement path:
  * BTP PASSKEY_ENTRY_REPLY (op 0x13) → IutActions.submit_passkey → SMP input role.
  * io_cap propagation to the live SMP manager (DisplayOnly for passkey display).
  * _PtsSmpDelegate.display_passkey → BTP GAP PASSKEY_DISPLAY (ev 0x84), LE addr.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pybluehost.cli.app.pts_tester import _PtsSmpDelegate
from pybluehost.core.address import AddressType, BDAddress
from pybluehost.core.types import IOCapability
from pybluehost.pts.actions import IutActions


def _make_actions() -> IutActions:
    """IutActions over a minimal fake stack (config.security + _smp + hooks)."""
    stack = SimpleNamespace(
        config=SimpleNamespace(security=SimpleNamespace(io_capability=0x03)),
        _smp=SimpleNamespace(_local_io_caps=IOCapability.NO_INPUT_NO_OUTPUT),
        on_connection_event=lambda cb: None,
        local_address=None,
    )
    return IutActions(stack)


# ---------------------------------------------------------------------------
# submit_passkey → _await_passkey_entry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_await_passkey_entry_blocks_until_submit():
    actions = _make_actions()
    waiter = asyncio.ensure_future(actions._await_passkey_entry(timeout=5))
    await asyncio.sleep(0)                      # let the waiter park on the future
    await actions.submit_passkey(123456)
    assert await waiter == 123456


@pytest.mark.asyncio
async def test_submit_passkey_before_await_is_stashed():
    actions = _make_actions()
    await actions.submit_passkey(42)            # no waiter yet → stashed
    assert await actions._await_passkey_entry(timeout=1) == 42
    # Stash consumed — a second await with no new submit must time out.
    with pytest.raises(asyncio.TimeoutError):
        await actions._await_passkey_entry(timeout=0.05)


# ---------------------------------------------------------------------------
# set_io_cap propagates to the live SMP manager
# ---------------------------------------------------------------------------

def test_set_io_cap_propagates_to_smp_manager():
    actions = _make_actions()
    actions.set_io_cap("DisplayOnly")
    assert actions._stack.config.security.io_capability == 0x00
    assert actions._stack._smp._local_io_caps == IOCapability.DISPLAY_ONLY


# ---------------------------------------------------------------------------
# _PtsSmpDelegate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_display_passkey_emits_btp_event_little_endian():
    gap = MagicMock()
    actions = _make_actions()
    delegate = _PtsSmpDelegate(gap, actions)
    peer = BDAddress.from_string("5C:67:83:07:04:EE", type=AddressType.PUBLIC)

    await delegate.display_passkey(peer, 654321)

    gap.on_passkey_display.assert_called_once()
    kwargs = gap.on_passkey_display.call_args.kwargs
    assert kwargs["passkey"] == 654321
    # auto-pts parses the event addr with le_bytes_to_hex_str → little-endian.
    assert kwargs["addr"] == peer.to_hci()


@pytest.mark.asyncio
async def test_get_passkey_waits_for_submit():
    gap = MagicMock()
    actions = _make_actions()
    delegate = _PtsSmpDelegate(gap, actions)

    waiter = asyncio.ensure_future(delegate.get_passkey(None))
    await asyncio.sleep(0)
    await actions.submit_passkey(7)
    assert await waiter == 7


@pytest.mark.asyncio
async def test_confirm_methods_auto_accept():
    delegate = _PtsSmpDelegate(MagicMock(), _make_actions())
    assert await delegate.confirm_pairing(0x40, 0) is True
    assert await delegate.confirm_passkey(None, 0) is True
    assert await delegate.confirm_numeric(None, 0) is True
