"""LE link: connection setup, SMP bridging with real addresses, LTK encryption."""
import asyncio
import struct

import pytest

from pybluehost.cli.app.mitm.acl import CID_SMP, encode_l2cap_basic
from pybluehost.cli.app.mitm.pairing.smp_pdu import PAIRING_REQUEST, PAIRING_RESPONSE
from pybluehost.cli.app.mitm.recon import ClonedIdentity
from pybluehost.cli.app.mitm.session import (
    _addr7_msb,
    _addr_str_to_le6,
    build_le_create_connection_params,
)
from pybluehost.hci.constants import (
    HCI_LE_CREATE_CONNECTION,
    HCI_LE_LONG_TERM_KEY_REQUEST_REPLY,
    HCI_LE_START_ENCRYPTION,
    HCI_READ_BD_ADDR,
    LEMetaSubEvent,
)
from pybluehost.hci.packets import HCI_LE_Meta_Event, HCIACLData
from tests.unit.mitm.test_session import _mk_session

LE_IDENT = ClonedIdentity(address="38:D5:18:CD:52:F7", address_type=0, adv_data=b"",
                          scan_response=b"", name=None)
LE_ADDR_LE = bytes.fromhex("F752CD18D538")  # little-endian wire order of the above address


def _le_idents(ident=LE_IDENT):
    return {"bredr": None, "le": ident}


def _stop_link_drains(link):
    """Cleanup: cancel the SMP drain tasks created by _build_link_for_test to
    avoid dangling tasks."""
    for t in link.drain_tasks:
        t.cancel()
    return asyncio.gather(*link.drain_tasks, return_exceptions=True)


def test_addr_str_to_le6():
    assert _addr_str_to_le6("38:D5:18:CD:52:F7") == bytes.fromhex("F752CD18D538")


def test_addr7_msb_matches_spec_sample():
    """SMP A1/A2 is [type] + MSB-first address: f5/f6 KAT has A1=00561237372600.

    Pins the contract against regressing to HCI wire order (LSB-first) — a
    regression would keep the ScPairing-vs-ScPairing unit tests all green while
    real-device DHKey Check always fails (both ends share the same wrong
    convention).
    """
    assert _addr7_msb("56:12:37:37:26:00", 0) == bytes.fromhex("00561237372600")
    assert _addr7_msb("38:D5:18:CD:52:F7", 1) == bytes.fromhex("0138D518CD52F7")


def test_build_le_create_connection_params_layout():
    p = build_le_create_connection_params(LE_ADDR_LE, 0)
    # scan_int(2) scan_win(2) filter(1) ptype(1) paddr(6) own(1)
    # min(2) max(2) lat(2) timeout(2) ce_min(2) ce_max(2) = 25 bytes
    assert len(p) == 25
    scan_int, scan_win = struct.unpack_from("<HH", p, 0)
    assert (scan_int, scan_win) == (0x0060, 0x0030)
    assert p[4] == 0x00          # filter: use peer address
    assert p[5] == 0x00          # peer addr type public
    assert p[6:12] == LE_ADDR_LE
    assert p[12] == 0x00         # own addr type public
    ci_min, ci_max, lat, sup = struct.unpack_from("<HHHH", p, 13)
    # 30-50ms / 5s: aligned with the stack BLEConnectionConfig defaults
    # (Nordic peripherals reject 7.5-15ms)
    assert (ci_min, ci_max, lat, sup) == (0x0018, 0x0028, 0x0000, 0x01F4)


def _le_conn_event(handle=0x0030, role=0x00, peer_type=0,
                   peer6=LE_ADDR_LE) -> HCI_LE_Meta_Event:
    """Build an LE_Connection_Complete.

    Subevent layout: status(1) handle(2, little-endian) role(1) peer_type(1)
    peer(6) interval(2) latency(2) clock(1); the Enhanced subevent has the
    same first 11 bytes.
    """
    params = (bytes([0x00]) + handle.to_bytes(2, "little") + bytes([role])
              + bytes([peer_type]) + peer6
              + struct.pack("<HHB", 0x0008, 0x0000, 0x00))
    return HCI_LE_Meta_Event.from_bytes(
        0x3E, bytes([LEMetaSubEvent.LE_CONNECTION_COMPLETE]) + params)


async def test_accept_le_parses_handle_and_peer_addr():
    s, pair = _mk_session(identities=_le_idents(ClonedIdentity(
        address="38:D5:18:CD:52:F8", address_type=0, adv_data=b"",
        scan_response=b"", name=None)))
    s._install_dispatch()
    task = asyncio.ensure_future(s._accept_le_on(pair.downstream))
    await asyncio.sleep(0)
    evt = _le_conn_event()
    # inject_event goes through the base HCIEvent path (no registry decode): the
    # session's LE meta parsing must accept both typed and plain forms (same
    # dual-path as recon.py).
    pair.downstream.inject_event(
        0x3E, bytes([evt.subevent_code]) + evt.subevent_parameters)
    conn = await asyncio.wait_for(task, 1.0)
    assert conn.handle == 0x0030
    assert conn.role == 0x00
    assert conn.peer_addr6 == LE_ADDR_LE
    assert s._subs["down"] == []  # finally already unsubscribed


async def test_le_accept_timeout_none_waits_indefinitely():
    """accept_timeout=None waits indefinitely: must not fall back to the
    connect_timeout 30s killing the session."""
    s, pair = _mk_session(identities=_le_idents())
    s._connect_timeout = 0.05  # if it wrongly fell back to connect_timeout, this times out before 0.15s (3x)
    s._install_dispatch()
    task = asyncio.ensure_future(s._accept_le_on(pair.downstream))
    await asyncio.sleep(0.15)  # far past the fallback window, still no event
    assert not task.done()     # not killed by timeout (the fallback bug would have raised TimeoutError here)
    evt = _le_conn_event(handle=0x0055)
    pair.downstream.inject_event(
        0x3E, bytes([evt.subevent_code]) + evt.subevent_parameters)
    conn = await asyncio.wait_for(task, 1.0)
    assert conn.handle == 0x0055
    assert s._subs["down"] == []  # finally already unsubscribed


async def test_connect_le_sends_create_connection_and_waits():
    s, pair = _mk_session(identities=_le_idents())
    s._install_dispatch()
    task = asyncio.ensure_future(s._connect_le_on(pair.upstream))
    await asyncio.sleep(0)
    assert any(c.opcode == HCI_LE_CREATE_CONNECTION for c in pair.upstream.commands)
    # typed HCI_LE_Meta_Event fed directly to dispatch (the shape produced by
    # the production registry decode)
    pair.upstream._on_hci_event(_le_conn_event(handle=0x0040))
    handle = await asyncio.wait_for(task, 1.0)
    assert handle == 0x0040
    assert s._subs["up"] == []  # finally already unsubscribed


async def test_smp_bridged_with_real_addresses_end_to_end():
    """SMP PDUs are terminated locally to the same-side pairing; pairings use
    the real addr7 (not the bytes(7) placeholder)."""
    s, pair = _mk_session(identities=_le_idents())
    pair.downstream.bd_addr = bytes.fromhex("C0FFEE000001")
    pair.upstream.bd_addr = bytes.fromhex("C0FFEE000002")
    s._down_addr6 = pair.downstream.bd_addr
    s._up_addr6 = pair.upstream.bd_addr
    relay, link = s._build_link_for_test()
    try:
        # real-address wiring (regression guard for the orchestrator bytes(7)
        # placeholder bug); addr7 = [type] + MSB-first address (f5/f6 contract),
        # the wire 6B must be reversed
        assert link.phone_addr7 == bytes([0x00]) + bytes(reversed(pair.downstream.bd_addr))
        assert link.phone_peer7 == bytes([0x00]) + bytes.fromhex("112233445566")
        assert link.target_addr7 == bytes([0x00]) + bytes(reversed(pair.upstream.bd_addr))
        assert link.target_peer7 == bytes([0x00]) + bytes.fromhex("38D518CD52F7")
        # auth_req=0x09 (bonding|SC): ScPairing is SC-only, 0x00 would be rejected
        pdu = encode_l2cap_basic(CID_SMP, bytes([PAIRING_REQUEST]) + bytes([0x03, 0x00, 0x09, 16, 0, 0]))
        acl = HCIACLData(handle=link.phone_handle, pb_flag=0x02, data=pdu)
        await relay.on_phone_acl(acl)
        # phone pairing (responder) answers with a Pairing Response to the
        # phone side; it must never be relayed to the other side
        await link.smp_queues["phone"].join()
        frames = pair.downstream.acl_sent
        assert len(frames) == 1
        handle, _pb, data = frames[0]
        assert handle == link.phone_handle
        assert int.from_bytes(data[2:4], "little") == CID_SMP  # L2CAP header CID
        assert data[4] == PAIRING_RESPONSE
        assert pair.upstream.acl_sent == []
    finally:
        await _stop_link_drains(link)


async def test_le_bring_up_starts_encryption_after_pairing():
    s, pair = _mk_session(identities=_le_idents())
    # proactive target pairing is opt-in (SC/LTK tests); the encryption path
    # must be explicitly enabled
    s._le_target_initiate_pairing = True
    relay, link = s._build_link_for_test()
    try:
        # simulate pairing already done (inject the LTK directly)
        link.pairings["target"].ltk = b"\x11" * 16
        await asyncio.wait_for(s._le_bring_up(link), 2.0)
        enc = [c for c in pair.upstream.commands if c.opcode == HCI_LE_START_ENCRYPTION]
        assert len(enc) == 1
        assert enc[0].parameters[0:2] == link.earbud_handle.to_bytes(2, "little")
        # SC: rand(8)/ediv(2) all zero, LTK in [12:28]
        assert enc[0].parameters[2:12] == bytes(10)
        assert enc[0].parameters[12:28] == b"\x11" * 16
    finally:
        await _stop_link_drains(link)


async def test_le_bring_up_skips_target_pairing_by_default():
    """Default is pure GATT pass-through: no proactive SMP pairing to the
    target, and no 20s LTK wait.

    Real-device lesson (NRF_EPD_7D4D): the target leg receiving an unsolicited
    Pairing Request drops the link with 0x3E within ~0.24s; plain
    unencrypted GATT does not need the relay to pair first at all.
    """
    s, pair = _mk_session(identities=_le_idents())
    relay, link = s._build_link_for_test()
    try:
        started = []
        orig_start = link.pairings["target"].start

        async def spy_start():
            started.append(True)
            return await orig_start()

        link.pairings["target"].start = spy_start
        await asyncio.wait_for(s._le_bring_up(link), 1.0)  # returns immediately, not a 20s poll
        assert started == []                              # no pairing initiated on the target side
        assert not any(c.opcode == HCI_LE_START_ENCRYPTION
                       for c in pair.upstream.commands)   # encryption not enabled
    finally:
        await _stop_link_drains(link)


async def test_ltk_request_replies_from_pairing():
    s, pair = _mk_session(identities=_le_idents())
    relay, link = s._build_link_for_test()
    try:
        s._le = link
        link.pairings["phone"].ltk = b"\x22" * 16
        s._on_phone_ltk_request(link.phone_handle, b"\x01" * 8, 0x0202)
        await asyncio.sleep(0)
        replies = [c for c in pair.downstream.commands
                   if c.opcode == HCI_LE_LONG_TERM_KEY_REQUEST_REPLY]
        assert len(replies) == 1 and replies[0].parameters[2:18] == b"\x22" * 16
        # unknown handle → ignore, send nothing extra
        s._on_phone_ltk_request(0x99, b"\x01" * 8, 0x0202)
        await asyncio.sleep(0)
        replies = [c for c in pair.downstream.commands
                   if c.opcode == HCI_LE_LONG_TERM_KEY_REQUEST_REPLY]
        assert len(replies) == 1
    finally:
        await _stop_link_drains(link)


async def test_run_le_reads_bd_addr_and_registers_ltk_hook(monkeypatch):
    """run() LE startup section: reads BD_ADDR on both sides + registers the
    LTK Request hook on downstream."""
    s, pair = _mk_session(identities=_le_idents())
    pair.downstream.bd_addr = bytes.fromhex("0A0B0C0D0E0F")
    pair.upstream.bd_addr = bytes.fromhex("1A1B1C1D1E1F")

    async def fake_impersonate(ctl, ident, *, clone_address):
        pass

    async def fake_accept():
        await asyncio.Event().wait()  # stays resident: run() blocks waiting for the phone connection

    monkeypatch.setattr(
        "pybluehost.cli.app.mitm.impersonate.start_impersonation", fake_impersonate)
    monkeypatch.setattr(s, "_accept_le", fake_accept)
    task = asyncio.ensure_future(s.run())
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)
    for ctl in (pair.downstream, pair.upstream):
        assert any(c.opcode == HCI_READ_BD_ADDR for c in ctl.commands)
    assert s._down_addr6 == pair.downstream.bd_addr
    assert s._up_addr6 == pair.upstream.bd_addr
    assert any(name == "le_ltk_request" and cb == s._on_phone_ltk_request
               for name, cb in pair.downstream.listeners)


def test_phone_visible_desc_name_mac_and_random():
    """Wait-log description: name + MAC; LE defaults to public own address,
    clone uses random = target address."""
    s, _pair = _mk_session(_le_idents())
    s._down_addr6 = LE_ADDR_LE  # little-endian wire order
    d = s._phone_visible_desc("le")
    assert "无名字" in d and "(public)" in d  # LE_IDENT.name=None → warning; public own address
    mac_hex = d.split("MAC=")[1].split(" ")[0]
    assert bytes.fromhex(mac_hex.replace(":", ""))[::-1] == LE_ADDR_LE  # display order reversed = wire order

    s2, _ = _mk_session(_le_idents(ClonedIdentity(
        address="99:1D:F9:90:11:1F", address_type=0, adv_data=b"",
        scan_response=b"", name="WQ7035_2223")))
    s2._clone_address = True
    d2 = s2._phone_visible_desc("le")
    assert "「WQ7035_2223」" in d2 and "MAC=99:1D:F9:90:11:1F (random)" in d2

    s3, _ = _mk_session()
    s3._down_addr6 = bytes.fromhex("0123456789AB")
    d3 = s3._phone_visible_desc("bredr")
    assert "MAC=AB:89:67:45:23:01" in d3
