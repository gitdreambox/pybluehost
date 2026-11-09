"""Auto-encrypt on bonded reconnect."""
from __future__ import annotations

import asyncio
import struct

import pytest

from pybluehost.ble.smp import BondInfo, JsonBondStorage
from pybluehost.core.address import AddressType, BDAddress
from pybluehost.stack import Stack, StackConfig


async def test_le_connection_complete_triggers_start_encryption_when_bonded(tmp_path, monkeypatch):
    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
    ))
    cfg = StackConfig(bond_storage=storage)
    stack = await Stack.virtual(config=cfg)
    try:
        sent: list = []
        original = stack._hci.send_command

        async def _capture(cmd):
            sent.append(cmd)
            return await original(cmd)

        monkeypatch.setattr(stack._hci, "send_command", _capture)

        # Inject a synthetic LE_Connection_Complete (role=0x00 = Central) to peer
        from pybluehost.hci.constants import EventCode, LEMetaSubEvent
        from pybluehost.hci.packets import HCI_LE_Meta_Event

        # subevent_parameters layout (LE_CONNECTION_COMPLETE):
        #   [0]     status (1 byte)
        #   [1:3]   connection_handle (2 bytes, LE)
        #   [3]     role (1 byte): 0x00 = Central
        #   [4]     peer_address_type (1 byte)
        #   [5:11]  peer_bd_addr (6 bytes)
        #   [11:13] conn_interval (2 bytes)
        #   [13:15] conn_latency (2 bytes)
        #   [15:17] supervision_timeout (2 bytes)
        #   [17]    master_clock_accuracy (1 byte)
        subevent_params = (
            bytes([0x00])                            # status = SUCCESS
            + struct.pack("<H", 0x0040)              # handle = 0x0040
            + bytes([0x00])                          # role = Central
            + bytes([0x00])                          # peer_address_type = public
            + peer.to_hci()                          # peer_bd_addr (HCI order)
            + struct.pack("<HHH", 0x0028, 0, 0x0048) # interval, latency, timeout
            + bytes([0])                             # master_clock_accuracy
        )
        evt = HCI_LE_Meta_Event(
            subevent_code=int(LEMetaSubEvent.LE_CONNECTION_COMPLETE),
            subevent_parameters=subevent_params,
        )
        await stack._on_hci_event(evt)
        await asyncio.sleep(0.05)

        from pybluehost.hci.packets import HCI_LE_Start_Encryption_Command
        assert any(isinstance(c, HCI_LE_Start_Encryption_Command) for c in sent), (
            "expected auto Start_Encryption command on LE_Connection_Complete with bonded peer"
        )
    finally:
        await stack.close()


async def test_le_connection_complete_resolves_rpa_bond_for_auto_encrypt(tmp_path, monkeypatch):
    storage = JsonBondStorage(tmp_path / "bonds.json")
    identity = BDAddress.from_string("01:02:03:04:05:06")
    irk = bytes.fromhex("00112233445566778899aabbccddeeff")

    from pybluehost.ble.gap import PrivacyManager

    # Build the RPA the way the privacy manager does (spec byte order); it is an
    # on-air (HCI-order) address, so construct the BDAddress with from_hci.
    rpa = BDAddress.from_hci(
        PrivacyManager.generate_rpa(irk, random_bytes=bytes.fromhex("412345")),
        type=AddressType.RANDOM,
    )
    await storage.save_bond(BondInfo(
        peer_address=identity,
        address_type=int(identity.type),
        ltk=b"\xCC" * 16,
        irk=irk,
        ediv=7,
        rand=b"\x01" * 8,
        sc=False,  # legacy bond: resumes (SC bonds intentionally skip the resume)
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        sent: list = []
        original = stack._hci.send_command

        async def _capture(cmd):
            sent.append(cmd)
            return await original(cmd)

        monkeypatch.setattr(stack._hci, "send_command", _capture)

        from pybluehost.hci.constants import LEMetaSubEvent
        from pybluehost.hci.packets import HCI_LE_Meta_Event, HCI_LE_Start_Encryption_Command

        subevent_params = (
            bytes([0x00])
            + struct.pack("<H", 0x0040)
            + bytes([0x00])
            + bytes([int(AddressType.RANDOM)])
            + rpa.to_hci()
            + struct.pack("<HHH", 0x0028, 0, 0x0048)
            + bytes([0])
        )
        evt = HCI_LE_Meta_Event(
            subevent_code=int(LEMetaSubEvent.LE_CONNECTION_COMPLETE),
            subevent_parameters=subevent_params,
        )
        await stack._on_hci_event(evt)
        await asyncio.sleep(0.05)

        assert any(isinstance(c, HCI_LE_Start_Encryption_Command) for c in sent)
    finally:
        await stack.close()


async def test_central_reconnect_skips_resume_for_sc_bond(tmp_path, monkeypatch):
    """SM/*/SCOB: an SC bond (EDIV=0/RAND=0) must NOT trigger the central
    auto-resume. SC test rounds pair FRESH via an explicit Pairing Request;
    resuming with the stale bond races that pairing and drops the link
    (supervision timeout 0x08) before round 2 can pair.

    The encrypt-pending flag must STAY set, though: the link is still expected
    to reach an encrypted state, and the gate that holds indications until then
    (GAP.TS Table 4.20 step 9A.4/9B.4) reads it. Clearing it made the
    Central-role SC cases report an unencrypted IND#1 to the Upper Tester
    (GAP/SEC/SEM/BV-63/64/67)."""
    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0, rand=b"\x00" * 8, sc=True,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        from unittest.mock import AsyncMock
        send = AsyncMock()
        monkeypatch.setattr(stack._hci, "send_command", send)

        from pybluehost.hci.constants import LEMetaSubEvent
        from pybluehost.hci.packets import HCI_LE_Meta_Event, HCI_LE_Start_Encryption_Command
        params = (
            bytes([0x00]) + struct.pack("<H", 0x0040) + bytes([0x00]) + bytes([0x00])
            + peer.to_hci() + struct.pack("<HHH", 0x0028, 0, 0x0048) + bytes([0])
        )
        evt = HCI_LE_Meta_Event(
            subevent_code=int(LEMetaSubEvent.LE_CONNECTION_COMPLETE),
            subevent_parameters=params,
        )
        await stack._on_hci_event(evt)
        await asyncio.sleep(0.05)
        assert not any(isinstance(c, HCI_LE_Start_Encryption_Command) for c in send.call_args_list), (
            "SC bond must not auto-resume; the explicit fresh pairing re-encrypts"
        )
        assert stack.is_le_encrypt_pending(0x0040), (
            "encryption is still expected on this link, so indications must be held"
        )
    finally:
        await stack.close()


async def test_no_auto_encrypt_when_config_disabled(tmp_path, monkeypatch):
    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=1, rand=b"\xDD" * 8,
    ))
    cfg = StackConfig(bond_storage=storage, auto_encrypt_on_bonded_reconnect=False)
    stack = await Stack.virtual(config=cfg)
    try:
        sent: list = []
        original = stack._hci.send_command

        async def _capture(cmd):
            sent.append(cmd)
            return await original(cmd)

        monkeypatch.setattr(stack._hci, "send_command", _capture)

        from pybluehost.hci.constants import LEMetaSubEvent
        from pybluehost.hci.packets import HCI_LE_Meta_Event, HCI_LE_Start_Encryption_Command

        subevent_params = (
            bytes([0x00])
            + struct.pack("<H", 0x0040)
            + bytes([0x00])
            + bytes([0x00])
            + peer.to_hci()
            + struct.pack("<HHH", 0x0028, 0, 0x0048)
            + bytes([0])
        )
        evt = HCI_LE_Meta_Event(
            subevent_code=int(LEMetaSubEvent.LE_CONNECTION_COMPLETE),
            subevent_parameters=subevent_params,
        )
        await stack._on_hci_event(evt)
        await asyncio.sleep(0.05)

        assert not any(isinstance(c, HCI_LE_Start_Encryption_Command) for c in sent)
    finally:
        await stack.close()


def _peripheral_conn_complete(peer: BDAddress) -> "object":
    """Synthetic LE_Connection_Complete with role=0x01 (Peripheral)."""
    import struct as _s
    from pybluehost.hci.constants import LEMetaSubEvent
    from pybluehost.hci.packets import HCI_LE_Meta_Event

    params = (
        bytes([0x00])                            # status = SUCCESS
        + _s.pack("<H", 0x0040)                  # handle
        + bytes([0x01])                          # role = Peripheral
        + bytes([0x00])                          # peer_address_type = public
        + peer.to_hci()                          # peer_bd_addr
        + _s.pack("<HHH", 0x0028, 0, 0x0048)     # interval, latency, timeout
        + bytes([0])                             # master_clock_accuracy
    )
    return HCI_LE_Meta_Event(
        subevent_code=int(LEMetaSubEvent.LE_CONNECTION_COMPLETE),
        subevent_parameters=params,
    )


async def test_central_bonded_reconnect_marks_encrypt_pending_synchronously(tmp_path, monkeypatch):
    """PTS GAP/SEC/SEM/BV-62 (Central): an indication PTS sends immediately after
    the reconnect must be held back. That requires ``_le_encrypt_pending`` to be
    set *synchronously* at LE Connection Complete — before the auto-encrypt task
    (which awaits the bond lookup) ever runs — else the IND arrives while the flag
    is still clear and leaks to the Upper Tester (WID 236 FAIL)."""
    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        # Suppress the actual Start_Encryption command; we only care about the flag.
        from unittest.mock import AsyncMock
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())

        from pybluehost.hci.constants import LEMetaSubEvent
        from pybluehost.hci.packets import HCI_LE_Meta_Event
        params = (
            bytes([0x00]) + struct.pack("<H", 0x0040) + bytes([0x00]) + bytes([0x00])
            + peer.to_hci() + struct.pack("<HHH", 0x0028, 0, 0x0048) + bytes([0])
        )
        evt = HCI_LE_Meta_Event(
            subevent_code=int(LEMetaSubEvent.LE_CONNECTION_COMPLETE),
            subevent_parameters=params,
        )
        await stack._on_hci_event(evt)
        # NO sleep: the flag must be set synchronously, before the create_task'd
        # auto-encrypt coroutine gets a chance to run.
        assert stack.is_le_encrypt_pending(0x0040), (
            "encrypt-pending must be set synchronously at Connection Complete so a "
            "promptly-arriving indication is held, not leaked"
        )
    finally:
        await stack.close()


async def test_central_reconnect_no_bond_clears_optimistic_pending(tmp_path, monkeypatch):
    """The optimistic pending flag must be cleared once the (empty) bond lookup
    completes, so a non-bonded peer's notifications are not held forever."""
    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")  # not bonded
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        from unittest.mock import AsyncMock
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())

        from pybluehost.hci.constants import LEMetaSubEvent
        from pybluehost.hci.packets import HCI_LE_Meta_Event
        params = (
            bytes([0x00]) + struct.pack("<H", 0x0040) + bytes([0x00]) + bytes([0x00])
            + peer.to_hci() + struct.pack("<HHH", 0x0028, 0, 0x0048) + bytes([0])
        )
        evt = HCI_LE_Meta_Event(
            subevent_code=int(LEMetaSubEvent.LE_CONNECTION_COMPLETE),
            subevent_parameters=params,
        )
        await stack._on_hci_event(evt)
        await asyncio.sleep(0.05)  # let the auto-encrypt task run the (empty) lookup
        assert not stack.is_le_encrypt_pending(0x0040), (
            "no bond -> optimistic pending must be cleared so notifications flow"
        )
    finally:
        await stack.close()


async def test_peripheral_bonded_reconnect_sends_security_request(tmp_path, monkeypatch):
    """GAP/SEC/SEM round-2: a bonded Peripheral-role reconnect must send an SMP
    Security Request so the central re-encrypts (the central waits for it)."""
    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        from unittest.mock import AsyncMock
        req_sec = AsyncMock()
        monkeypatch.setattr(stack._smp, "request_security", req_sec)

        await stack._on_hci_event(_peripheral_conn_complete(peer))
        await asyncio.sleep(0.05)

        req_sec.assert_awaited()
        args, kwargs = req_sec.await_args
        assert args[0] == 0x0040
        auth_req = kwargs["auth_req"]
        # Bonding set; MITM must NOT be forced (Level-2 Just Works bonds can't
        # satisfy a MITM request -> central would ignore the Security Request).
        assert auth_req & 0x01
        assert not (auth_req & 0x04), "Security Request must not force MITM"
    finally:
        await stack.close()


async def test_peripheral_reconnect_no_bond_sends_no_security_request(tmp_path, monkeypatch):
    """No stored bond -> no Security Request (fresh GATT/SR peer unaffected)."""
    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")  # not bonded
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        from unittest.mock import AsyncMock
        req_sec = AsyncMock()
        monkeypatch.setattr(stack._smp, "request_security", req_sec)

        await stack._on_hci_event(_peripheral_conn_complete(peer))
        await asyncio.sleep(0.05)

        req_sec.assert_not_awaited()
    finally:
        await stack.close()


async def test_pin_or_key_missing_reports_a_lost_bond(tmp_path, monkeypatch):
    """GAP/SEC/AUT/BV-21/22: the peer refuses to encrypt with the LTK it
    distributed earlier ("PIN or Key Missing", HCI 0x06), so its half of the
    bond is gone. We must forget ours and tell the upper layer — that event is
    the entire pass verdict of both cases."""
    from unittest.mock import AsyncMock

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        lost: list = []
        stack.on_bond_lost(lambda h, p: lost.append((h, p)))
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())

        await stack._on_hci_event(_peripheral_conn_complete(peer))
        await stack._on_encryption_change(0x0040, 0x06, 0)

        assert lost, "a lost bond must be reported"
        handle, reported = lost[0]
        assert handle == 0x0040
        assert str(reported) == str(peer)
        assert await storage.load_bond(peer) is None, "the stale bond must be dropped"
    finally:
        await stack.close()


def _central_conn_complete(peer: BDAddress, handle: int = 0x0040) -> "object":
    """Synthetic LE_Connection_Complete with role=0x00 (Central)."""
    import struct as _s
    from pybluehost.hci.constants import LEMetaSubEvent
    from pybluehost.hci.packets import HCI_LE_Meta_Event

    params = (
        bytes([0x00])                            # status = SUCCESS
        + _s.pack("<H", handle)                  # handle
        + bytes([0x00])                          # role = Central
        + bytes([0x00])                          # peer_address_type = public
        + peer.to_hci()                          # peer_bd_addr
        + _s.pack("<HHH", 0x0028, 0, 0x0048)     # interval, latency, timeout
        + bytes([0])                             # master_clock_accuracy
    )
    return HCI_LE_Meta_Event(
        subevent_code=int(LEMetaSubEvent.LE_CONNECTION_COMPLETE),
        subevent_parameters=params,
    )


async def test_central_key_missing_repair_triggers_a_fresh_pairing(tmp_path, monkeypatch):
    """GAP/SEC/AUT/BV-24 phase 2 (Central): we resume encryption from the bond
    stored in phase 1, but the LT dropped its copy at disconnect and answers
    the encryption attempt with "PIN or Key Missing" (0x06). The bond is dead
    on the peer side, so the only way to restore security is a fresh pairing —
    Core Vol 3 Part H §3.6.1 sanctions pairing as the response to a Security
    Request, and the family (BV-20 step 1B.3, BV-19) explicitly allows the IUT
    to re-pair. Without the repair the LT waits for encryption forever and the
    case stalls in INDCSV."""
    from unittest.mock import AsyncMock

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0, rand=b"\x00" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        lost: list = []
        stack.on_bond_lost(lambda h, p: lost.append((h, p)))
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        repair = AsyncMock()
        monkeypatch.setattr(stack._smp, "start_initiator", repair)

        await stack._on_hci_event(_central_conn_complete(peer))
        await stack._on_encryption_change(0x0040, 0x06, 0)
        await asyncio.sleep(0)  # let the fire-and-forget repair task run

        assert lost, "the lost bond must still be reported (BV-21 verdict)"
        repair.assert_awaited_once_with(0x0040, peer_sec_req_auth_req=None)
    finally:
        await stack.close()


async def test_resume_failure_on_any_status_triggers_hinted_repair(tmp_path, monkeypatch):
    """GAP.TS 4.7.5.1.2 step 6A (BV-25/26/27/28 family): the LT fails the
    IUT's post-reconnect encryption attempt on purpose and then expects a
    fresh pairing. On this rig the failure has been observed as status 0x08
    (LL response timeout), not the 0x06 the bond-lost branch keys on — the
    resume watcher must treat ANY failure status as "pair again", and carry
    the Security Request's auth level (MITM) into the fresh pairing so the
    re-pair is authenticated (the whole point of the family)."""
    from unittest.mock import AsyncMock

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0, rand=b"\x00" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        repair = AsyncMock()
        monkeypatch.setattr(stack._smp, "start_initiator", repair)

        await stack._on_hci_event(_central_conn_complete(peer))
        await stack._resume_encryption_with_bond(
            0x0040, await storage.load_bond(peer), 0x0D)
        await stack._on_encryption_change(0x0040, 0x08, 0)
        await asyncio.sleep(0.1)  # watcher tick

        repair.assert_awaited_once_with(0x0040, peer_sec_req_auth_req=0x0D)
    finally:
        await stack.close()


async def test_resume_success_does_not_repair(tmp_path, monkeypatch):
    """A bond resume that completes (Encryption_Change enabled) must not spawn
    a repair pairing — the fresh-pairing path is only for failures."""
    from unittest.mock import AsyncMock

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0, rand=b"\x00" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        repair = AsyncMock()
        monkeypatch.setattr(stack._smp, "start_initiator", repair)

        await stack._on_hci_event(_central_conn_complete(peer))
        await stack._resume_encryption_with_bond(
            0x0040, await storage.load_bond(peer), 0x0D)
        await stack._on_encryption_change(0x0040, 0x00, 1)
        await asyncio.sleep(0.1)  # watcher tick

        repair.assert_not_awaited()
    finally:
        await stack.close()


async def test_resume_on_dropped_link_does_not_repair(tmp_path, monkeypatch):
    """If the link drops while the resume outcome is pending there is nothing
    to pair on — the watcher must bail out (and release the pending marker so
    it cannot leak onto a recycled connection handle)."""
    from unittest.mock import AsyncMock

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0, rand=b"\x00" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        repair = AsyncMock()
        monkeypatch.setattr(stack._smp, "start_initiator", repair)

        await stack._on_hci_event(_central_conn_complete(peer))
        await stack._resume_encryption_with_bond(
            0x0040, await storage.load_bond(peer), 0x0D)
        stack._le_peer_addrs.pop(0x0040)  # disconnection
        await asyncio.sleep(0.1)  # watcher tick

        repair.assert_not_awaited()
        assert 0x0040 not in stack._le_encrypt_pending
    finally:
        await stack.close()


async def test_resume_silent_stall_repairs_after_timeout(tmp_path, monkeypatch):
    """Some LTs "fail" the encryption by never answering the LL procedure, so
    no Encryption_Change ever arrives. When the watch window lapses with the
    link still up and unencrypted, that is a failed attempt too — pair again."""
    from unittest.mock import AsyncMock

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0, rand=b"\x00" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    stack._resume_watch_timeout = 0.05
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        repair = AsyncMock()
        monkeypatch.setattr(stack._smp, "start_initiator", repair)

        await stack._on_hci_event(_central_conn_complete(peer))
        await stack._resume_encryption_with_bond(
            0x0040, await storage.load_bond(peer), 0x0D)
        await asyncio.sleep(0.3)  # watcher timeout is 0.05 s

        repair.assert_awaited_once_with(0x0040, peer_sec_req_auth_req=0x0D)
    finally:
        await stack.close()


async def test_bonded_context_does_not_block_the_repair(tmp_path, monkeypatch):
    """BV-27's actual flow: the preamble pairing completes (the SMP context
    sits in BONDED) and *then* the LT fails the encryption. The finished
    context must not block the fresh pairing a repair spawns — only a pairing
    genuinely mid-flight may."""
    from unittest.mock import AsyncMock

    from pybluehost.ble.smp import SMPState

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0, rand=b"\x00" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        repair = AsyncMock()
        monkeypatch.setattr(stack._smp, "start_initiator", repair)

        await stack._on_hci_event(_central_conn_complete(peer))

        # A finished context (as after the preamble pairing) must not block.
        class _FakeCtx:
            class state_machine:  # noqa: N801
                state = SMPState.BONDED

        monkeypatch.setattr(stack._smp, "get_context", lambda h: _FakeCtx())
        assert stack._pairing_in_flight(0x0040) is False

        # A mid-flight context must block.
        _FakeCtx.state_machine.state = SMPState.CONFIRMING
        assert stack._pairing_in_flight(0x0040) is True

        # And the watcher end-to-end still repairs through a BONDED context.
        _FakeCtx.state_machine.state = SMPState.BONDED
        await stack._resume_encryption_with_bond(
            0x0040, await storage.load_bond(peer), 0x0D)
        await stack._on_encryption_change(0x0040, 0x08, 0)
        await asyncio.sleep(0.1)
        repair.assert_awaited_once_with(0x0040, peer_sec_req_auth_req=0x0D)
    finally:
        await stack.close()


async def test_pairing_encryption_failure_while_central_repairs_instead_of_aborting(monkeypatch):
    """GAP/SEC/SEM/BV-45 steps 5-6B: the LT fails the encryption phase on
    purpose (observed on this rig as Encryption_Change 0x08 right after the
    DHKey check). The IUT must NOT terminate the pairing — no Pairing Failed
    to the peer, which would kill the link the alternative-6B re-pairing
    needs — it starts a fresh pairing on the live link, carrying its own
    auth level (mode 1 level 4 = MITM) into the new attempt."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from pybluehost.ble.smp import SMPEvent, SMPState

    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    stack = await Stack.virtual()
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        repair = AsyncMock()
        monkeypatch.setattr(stack._smp, "start_initiator", repair)

        fake_ctx = SimpleNamespace(
            state_machine=SimpleNamespace(state=SMPState.DHKEY_CHECK,
                                          fire=AsyncMock()),
            pairing_complete=None,
            local_auth_req=0x0D,
        )
        monkeypatch.setattr(stack._smp, "get_context", lambda h: fake_ctx)

        await stack._on_hci_event(_central_conn_complete(peer))
        await stack._on_encryption_change(0x0040, 0x08, 0)
        await asyncio.sleep(0.05)  # let the repair task run

        repair.assert_awaited_once_with(0x0040, peer_sec_req_auth_req=0x0D)
        fake_ctx.state_machine.fire.assert_not_awaited()
        assert stack._pairing_repairs[0x0040] == 1
    finally:
        await stack.close()


async def test_pairing_encryption_failure_budget_exhausted_fires_terminal_failure(monkeypatch):
    """After the repair budget is spent the failure degenerates to today's
    behavior: the state machine is told (terminal Pairing Failed 0x08) and no
    further repair pairing is spawned."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from pybluehost.ble.smp import SMPEvent, SMPState

    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    stack = await Stack.virtual()
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        repair = AsyncMock()
        monkeypatch.setattr(stack._smp, "start_initiator", repair)
        stack._pairing_repairs[0x0040] = 2

        fake_ctx = SimpleNamespace(
            state_machine=SimpleNamespace(state=SMPState.DHKEY_CHECK,
                                          fire=AsyncMock()),
            pairing_complete=None,
            local_auth_req=0x0D,
        )
        monkeypatch.setattr(stack._smp, "get_context", lambda h: fake_ctx)

        await stack._on_hci_event(_central_conn_complete(peer))
        await stack._on_encryption_change(0x0040, 0x08, 0)
        await asyncio.sleep(0.05)

        repair.assert_not_awaited()
        fake_ctx.state_machine.fire.assert_awaited_once_with(
            SMPEvent.ENCRYPTION_CHANGE_FAILED)
    finally:
        await stack.close()


async def test_pairing_encryption_failure_as_peripheral_fires_terminal_failure(monkeypatch):
    """A peripheral cannot initiate pairing (Core Vol 3 Part H §3.2), so the
    repair path is central-only — the peripheral still terminates via the
    state machine."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from pybluehost.ble.smp import SMPEvent, SMPState

    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    stack = await Stack.virtual()
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        repair = AsyncMock()
        monkeypatch.setattr(stack._smp, "start_initiator", repair)

        fake_ctx = SimpleNamespace(
            state_machine=SimpleNamespace(state=SMPState.RANDOM_EXCHANGE,
                                          fire=AsyncMock()),
            pairing_complete=None,
            local_auth_req=0x0D,
        )
        monkeypatch.setattr(stack._smp, "get_context", lambda h: fake_ctx)

        await stack._on_hci_event(_peripheral_conn_complete(peer))
        await stack._on_encryption_change(0x0040, 0x08, 0)

        repair.assert_not_awaited()
        fake_ctx.state_machine.fire.assert_awaited_once_with(
            SMPEvent.ENCRYPTION_CHANGE_FAILED)
    finally:
        await stack.close()


async def test_pairing_repair_budget_resets_on_disconnect(monkeypatch):
    """The per-handle repair budget must not leak onto a recycled connection
    handle — the disconnect clears it like the other per-handle state."""
    from unittest.mock import AsyncMock

    from pybluehost.hci.constants import ErrorCode
    from pybluehost.hci.packets import HCI_Disconnection_Complete_Event

    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    stack = await Stack.virtual()
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        await stack._on_hci_event(_central_conn_complete(peer))
        stack._pairing_repairs[0x0040] = 1

        await stack._on_hci_event(HCI_Disconnection_Complete_Event(
            status=ErrorCode.SUCCESS,
            connection_handle=0x0040,
            reason=ErrorCode.REMOTE_USER_TERMINATED,
        ))
        assert 0x0040 not in stack._pairing_repairs
    finally:
        await stack.close()


async def test_pairing_encryption_failure_skips_repair_when_resume_watch_owns_handle(monkeypatch):
    """When the bond-resume watcher is armed on the handle it owns the failure
    (GAP/SEC/AUT BV-24 phase 2) — the pairing-repair path must not also fire,
    or two fresh pairings would race on the same link."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from pybluehost.ble.smp import SMPEvent, SMPState

    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    stack = await Stack.virtual()
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        repair = AsyncMock()
        monkeypatch.setattr(stack._smp, "start_initiator", repair)
        stack._resume_watch.add(0x0040)

        fake_ctx = SimpleNamespace(
            state_machine=SimpleNamespace(state=SMPState.DHKEY_CHECK,
                                          fire=AsyncMock()),
            pairing_complete=None,
            local_auth_req=0x0D,
        )
        monkeypatch.setattr(stack._smp, "get_context", lambda h: fake_ctx)

        await stack._on_hci_event(_central_conn_complete(peer))
        await stack._on_encryption_change(0x0040, 0x08, 0)
        await asyncio.sleep(0.05)

        repair.assert_not_awaited()
        fake_ctx.state_machine.fire.assert_awaited_once_with(
            SMPEvent.ENCRYPTION_CHANGE_FAILED)
    finally:
        await stack.close()


async def test_resume_watch_and_key_missing_branch_do_not_double_repair(
        tmp_path, monkeypatch):
    """A 0x06 failure during a watched resume must produce exactly one repair
    (the watcher's, carrying the hint) while the Key-Missing branch still
    reports the lost bond."""
    from unittest.mock import AsyncMock

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0, rand=b"\x00" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        lost: list = []
        stack.on_bond_lost(lambda h, p: lost.append((h, p)))
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        repair = AsyncMock()
        monkeypatch.setattr(stack._smp, "start_initiator", repair)

        await stack._on_hci_event(_central_conn_complete(peer))
        await stack._resume_encryption_with_bond(
            0x0040, await storage.load_bond(peer), 0x0D)
        await stack._on_encryption_change(0x0040, 0x06, 0)
        await asyncio.sleep(0.1)  # watcher tick

        assert lost, "Key Missing still reports the lost bond (BV-21/22)"
        repair.assert_awaited_once_with(0x0040, peer_sec_req_auth_req=0x0D)
    finally:
        await stack.close()


async def test_peripheral_key_missing_does_not_repair(tmp_path, monkeypatch):
    """A peripheral must not answer Key Missing with a Pairing Request — that
    direction is a protocol violation (Core Vol 3 Part H §3.2); the peripheral
    only reports the lost bond and waits for the central to re-pair."""
    from unittest.mock import AsyncMock

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0, rand=b"\x00" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        lost: list = []
        stack.on_bond_lost(lambda h, p: lost.append((h, p)))
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        repair = AsyncMock()
        monkeypatch.setattr(stack._smp, "start_initiator", repair)

        await stack._on_hci_event(_peripheral_conn_complete(peer))
        await stack._on_encryption_change(0x0040, 0x06, 0)
        await asyncio.sleep(0)

        assert lost, "the lost bond must still be reported (BV-22 verdict)"
        repair.assert_not_awaited()
    finally:
        await stack.close()


async def test_pairing_request_after_security_request_reports_bond_lost(tmp_path, monkeypatch):
    """GAP/SEC/AUT/BV-22: the central answers our Security Request with a
    Pairing Request — it has no usable bond for us. The SMP bond-lost signal
    must reach the stack's ``on_bond_lost`` listeners (the BTP BOND_LOST
    event auto-pts waits on in WID 143) and purge the stale bond. The
    responder pairing that triggered it still proceeds (no initiator spawn).
    """
    from unittest.mock import AsyncMock

    from pybluehost.core.types import IOCapability
    from pybluehost.ble.smp import SMPPairingRequest

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0, rand=b"\x00" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        lost: list = []
        stack.on_bond_lost(lambda h, p: lost.append((h, p)))
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        repair = AsyncMock()
        monkeypatch.setattr(stack._smp, "start_initiator", repair)

        await stack._on_hci_event(_peripheral_conn_complete(peer))
        await asyncio.sleep(0)  # let the auto Security Request task run
        repair.assert_not_awaited()

        await stack._smp.on_pdu(SMPPairingRequest(
            io_capability=IOCapability.KEYBOARD_DISPLAY, oob_data_flag=0,
            auth_req=0x09, max_key_size=16,
            init_key_dist=0x00, resp_key_dist=0x02,
        ).to_bytes(), connection_handle=0x0040)
        await asyncio.sleep(0)  # let the purge task run

        assert lost, "SecReq answered by a Pairing Request must report the lost bond"
        handle, reported = lost[0]
        assert handle == 0x0040
        assert str(reported) == str(peer)
        assert await storage.load_bond(peer) is None, "the stale bond must be dropped"
        repair.assert_not_awaited(), "responder pairing is already running"
    finally:
        await stack.close()


async def test_successful_encryption_does_not_report_a_lost_bond(tmp_path, monkeypatch):
    """status 0x00 must not be mistaken for a lost bond."""
    from unittest.mock import AsyncMock

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        lost: list = []
        stack.on_bond_lost(lambda h, p: lost.append((h, p)))
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())

        await stack._on_hci_event(_peripheral_conn_complete(peer))
        await stack._on_encryption_change(0x0040, 0x00, 1)

        assert lost == []
        assert await storage.load_bond(peer) is not None
    finally:
        await stack.close()


async def test_security_request_resumes_encryption_from_a_legacy_bond(tmp_path, monkeypatch):
    """GAP/SEC/AUT/BV-13 step 2 (Central): the LT's Security Request asks for a
    level an existing bond already covers, so the IUT must *encrypt the link*
    with that LTK — not pair again, and not sit idle."""
    from unittest.mock import AsyncMock

    from pybluehost.ble.smp import SMPSecurityRequest
    from pybluehost.hci.packets import HCI_LE_Start_Encryption_Command

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        sent: list = []

        async def _capture(cmd):
            sent.append(cmd)

        monkeypatch.setattr(stack._hci, "send_command", _capture)
        stack._le_peer_addrs[0x0040] = peer

        await stack._smp.on_pdu(
            SMPSecurityRequest(auth_req=0x01).to_bytes(), connection_handle=0x0040,
        )

        starts = [c for c in sent if isinstance(c, HCI_LE_Start_Encryption_Command)]
        assert starts, "a covering bond means encrypt with it, not pair again"
        assert starts[0].long_term_key == b"\xCC" * 16
        assert starts[0].encrypted_diversifier == 0x1234
        assert starts[0].random_number == b"\xDD" * 8
    finally:
        await stack.close()


async def test_security_request_resumes_encryption_from_an_sc_bond(tmp_path, monkeypatch):
    """The SC-bond carve-out in _auto_encrypt_on_reconnect exists because *we*
    jump the gun on connect and race the peer's fresh pairing. A Security
    Request has no such race — the peer is asking — so SC bonds resume too.
    Without this, the pre-existing-bond GAP/SEC/AUT cases never encrypt."""
    from pybluehost.ble.smp import SMPSecurityRequest
    from pybluehost.hci.packets import HCI_LE_Start_Encryption_Command

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0, rand=b"\x00" * 8, sc=True,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        sent: list = []

        async def _capture(cmd):
            sent.append(cmd)

        monkeypatch.setattr(stack._hci, "send_command", _capture)
        stack._le_peer_addrs[0x0040] = peer

        await stack._smp.on_pdu(
            SMPSecurityRequest(auth_req=0x01).to_bytes(), connection_handle=0x0040,
        )

        starts = [c for c in sent if isinstance(c, HCI_LE_Start_Encryption_Command)]
        assert starts, "SC bonds resume on a Security Request (no pairing race here)"
        assert starts[0].long_term_key == b"\xCC" * 16
    finally:
        await stack.close()


async def test_security_request_resume_does_not_re_encrypt_an_encrypted_link(
    tmp_path, monkeypatch,
):
    from pybluehost.ble.smp import SMPSecurityRequest
    from pybluehost.hci.packets import HCI_LE_Start_Encryption_Command

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        sent: list = []

        async def _capture(cmd):
            sent.append(cmd)

        monkeypatch.setattr(stack._hci, "send_command", _capture)
        stack._le_peer_addrs[0x0040] = peer
        stack._le_encrypted[0x0040] = True

        await stack._smp.on_pdu(
            SMPSecurityRequest(auth_req=0x01).to_bytes(), connection_handle=0x0040,
        )

        assert not [c for c in sent if isinstance(c, HCI_LE_Start_Encryption_Command)]
    finally:
        await stack.close()


async def test_encryption_change_event_carries_peer_and_sec_level(tmp_path, monkeypatch):
    """GATT/SR/GAR/BV-11/12 (bond-assuming EATT cases): on a bonded reconnect the
    link is encrypted by resuming the stored LTK — no pairing runs, so the
    pairing-driven SEC_LEVEL_CHANGED path never fires. auto-pts advances its
    `conn.sec_level` model only via BTP SEC_LEVEL_CHANGED, so without an event
    the EATT-listen WID waits 30s and the case aborts even though the link is
    encrypted. The stack's "encrypted" connection event must carry the peer
    address and the security level so pts-tester can emit that BTP event."""
    from unittest.mock import AsyncMock

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        events: list = []
        stack.on_connection_event(events.append)
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())

        await stack._on_hci_event(_peripheral_conn_complete(peer))
        await stack._on_encryption_change(0x0040, 0x00, 1)

        encrypted = [e for e in events if e.state == "encrypted"]
        assert encrypted, "an encrypted connection event must be emitted"
        assert str(encrypted[-1].peer_address) == str(peer)
        # No SMP context exists on a bond-resume (no pairing this connection)
        # → unauthenticated → level 2.
        assert encrypted[-1].sec_level == 2
    finally:
        await stack.close()


async def test_bond_resume_encryption_marks_gatt_gate_authenticated(tmp_path, monkeypatch):
    """GAP/SEC/AUT/BV-24 phase 2: the LT's Security Request is met by resuming
    the stored bond (no pairing runs, so no SMP context exists), the encryption
    succeeds, and the LT immediately re-issues its service request. The GATT
    server gate must take authenticated/key_size from the *bond* — deriving
    them from the (absent) pairing context leaves authenticated=False, the
    read_authn read still gets ErrRsp 0x05 after a successful encryption, and
    the LT aborts the case."""
    from unittest.mock import AsyncMock

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
        authenticated=True, sc=True,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        events: list = []
        stack.on_connection_event(events.append)
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        stack._gatt_server = AsyncMock()
        gate = stack._gatt_server.set_connection_security

        await stack._on_hci_event(_central_conn_complete(peer))
        await stack._resume_encryption_with_bond(
            0x0040, await storage.load_bond(peer), 0x0D)
        await stack._on_encryption_change(0x0040, 0x00, 1)
        await asyncio.sleep(0.05)  # let the resume watcher observe success

        gate.assert_called_once_with(
            0x0040, encrypted=True, authenticated=True, key_size=16)
        encrypted = [e for e in events if e.state == "encrypted"]
        assert encrypted[-1].sec_level == 3
    finally:
        await stack.close()


async def test_bond_resume_unauthenticated_bond_keeps_gate_unauthenticated(tmp_path, monkeypatch):
    """A legacy, unauthenticated bond resume encrypts the link but must not
    raise the gate above what the bond can prove: authenticated=False and the
    bond's negotiated key_size flow into the GATT server gate."""
    from unittest.mock import AsyncMock

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
        authenticated=False, key_size=7,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        stack._gatt_server = AsyncMock()
        gate = stack._gatt_server.set_connection_security

        await stack._on_hci_event(_central_conn_complete(peer))
        await stack._resume_encryption_with_bond(0x0040, await storage.load_bond(peer))
        await stack._on_encryption_change(0x0040, 0x00, 1)
        await asyncio.sleep(0.05)

        gate.assert_called_once_with(
            0x0040, encrypted=True, authenticated=False, key_size=7)
    finally:
        await stack.close()


async def test_pairing_context_still_wins_over_the_resume_bond(tmp_path, monkeypatch):
    """When a pairing did run on this connection its context describes the link
    better than the resume stash — the stash is only a fallback for the
    context-less bond-resume path."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
        authenticated=False, key_size=7,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        stack._gatt_server = AsyncMock()
        gate = stack._gatt_server.set_connection_security
        # A fresh pairing left an authenticated context behind.
        fake_ctx = SimpleNamespace(
            local_auth_req=0x0D, peer_auth_req=0x0D, peer_max_key_size=16,
            state_machine=SimpleNamespace(fire=AsyncMock()),
        )
        monkeypatch.setattr(stack._smp, "get_context", lambda handle: fake_ctx)

        await stack._on_hci_event(_central_conn_complete(peer))
        stack._le_resume_bonds[0x0040] = await storage.load_bond(peer)
        await stack._on_encryption_change(0x0040, 0x00, 1)

        gate.assert_called_once_with(
            0x0040, encrypted=True, authenticated=True, key_size=16)
    finally:
        await stack.close()


async def test_resume_bond_stash_lifecycle(tmp_path, monkeypatch):
    """The stash must not leak onto a recycled connection handle — but it must
    SURVIVE a failed encryption: the disconnect handler needs it to recognize
    "the resume was rejected and the link died" (the reconnect-and-repair
    trigger). It is cleared by success and by the link dropping."""
    from unittest.mock import AsyncMock

    from pybluehost.hci.constants import ErrorCode
    from pybluehost.hci.packets import HCI_Disconnection_Complete_Event

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        # The failure lets the resume watcher spawn a repair pairing; swallow it.
        monkeypatch.setattr(stack._smp, "start_initiator", AsyncMock())

        await stack._on_hci_event(_central_conn_complete(peer))
        await stack._resume_encryption_with_bond(0x0040, await storage.load_bond(peer))
        await stack._on_encryption_change(0x0040, 0x08, 0)
        assert 0x0040 in stack._le_resume_bonds

        # The link drops: the stash goes with it.
        await stack._on_hci_event(HCI_Disconnection_Complete_Event(
            status=ErrorCode.SUCCESS,
            connection_handle=0x0040,
            reason=ErrorCode.REMOTE_USER_TERMINATED,
        ))
        assert 0x0040 not in stack._le_resume_bonds
    finally:
        await stack.close()


async def test_auto_encrypt_resume_failure_repairs_with_hinted_pairing(tmp_path, monkeypatch):
    """GAP/SEC/AUT/BV-19: the LT deliberately fails the IUT's post-reconnect
    encryption (TS step 3b) and then expects the IUT to re-pair on its own
    (step 4). The reconnection auto-encrypt must therefore be watched like the
    Security-Request resume: on failure, start a fresh *authenticated* pairing
    while the link is still alive — on this rig the LT stalls the LL procedure
    and the link dies with it shortly after."""
    from unittest.mock import AsyncMock

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
        authenticated=True,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        repair = AsyncMock()
        monkeypatch.setattr(stack._smp, "start_initiator", repair)

        await stack._on_hci_event(_central_conn_complete(peer))
        await asyncio.sleep(0.1)  # auto-encrypt task sends + arms the watcher
        await stack._on_encryption_change(0x0040, 0x08, 0)
        await asyncio.sleep(0.1)  # watcher tick

        repair.assert_awaited_once_with(0x0040, peer_sec_req_auth_req=0x0D)
    finally:
        await stack.close()


async def test_auto_encrypt_resume_success_does_not_repair(tmp_path, monkeypatch):
    """A plain bonded reconnect that encrypts fine must stay exactly as it was
    — the watcher only exists for the failed attempt."""
    from unittest.mock import AsyncMock

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        repair = AsyncMock()
        monkeypatch.setattr(stack._smp, "start_initiator", repair)

        await stack._on_hci_event(_central_conn_complete(peer))
        await asyncio.sleep(0.1)
        await stack._on_encryption_change(0x0040, 0x00, 1)
        await asyncio.sleep(0.1)

        repair.assert_not_awaited()
    finally:
        await stack.close()


async def test_rejected_resume_reconnects_and_pairs_afresh(tmp_path, monkeypatch):
    """This rig's LTs fail a bond resume by rejecting the LL procedure and
    dropping the link moments later (GAP/SEC/AUT/BV-24/27: the LT deliberately
    fails the IUT's re-encryption, then expects user-interaction pairing and a
    service-request retry — GAP.TS Tables 4.31/4.32 steps 6A/7-11). A dead
    link cannot be repaired in place: reconnect to the bonded peer and pair
    afresh on the new link."""
    from unittest.mock import AsyncMock

    from pybluehost.hci.constants import ErrorCode, LEMetaSubEvent
    from pybluehost.hci.packets import HCI_Disconnection_Complete_Event, HCI_LE_Meta_Event

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
        authenticated=True,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        repair = AsyncMock()
        monkeypatch.setattr(stack._smp, "start_initiator", repair)
        connect_gatt = AsyncMock(return_value=0x0041)
        monkeypatch.setattr(stack, "connect_gatt", connect_gatt)

        await stack._on_hci_event(_central_conn_complete(peer))
        await stack._resume_encryption_with_bond(
            0x0040, await storage.load_bond(peer), 0x0D)
        await stack._on_encryption_change(0x0040, 0x08, 0)
        await asyncio.sleep(0.1)  # watcher ticks; link still up → in-place repair path
        repair.assert_awaited_once_with(0x0040, peer_sec_req_auth_req=0x0D)

        # ...and the repair's fresh pairing ALSO gets rejected, killing the link.
        repair.reset_mock()
        await stack._on_hci_event(HCI_Disconnection_Complete_Event(
            status=ErrorCode.SUCCESS,
            connection_handle=0x0040,
            reason=ErrorCode.REMOTE_USER_TERMINATED,
        ))
        await asyncio.sleep(0.1)
        connect_gatt.assert_awaited()

        # The reconnect landed: a new connection event to the same peer must
        # pair afresh instead of resuming the (just-rejected) bond again.
        params = (
            bytes([0x00]) + struct.pack("<H", 0x0041) + bytes([0x00]) + bytes([0x00])
            + peer.to_hci() + struct.pack("<HHH", 0x0028, 0, 0x0048) + bytes([0])
        )
        await stack._on_hci_event(HCI_LE_Meta_Event(
            subevent_code=int(LEMetaSubEvent.LE_CONNECTION_COMPLETE),
            subevent_parameters=params,
        ))
        await asyncio.sleep(0.1)
        repair.assert_awaited_with(0x0041, peer_sec_req_auth_req=0x0D)
    finally:
        await stack.close()


async def test_resume_reconnect_is_capped_per_peer(tmp_path, monkeypatch):
    """A peer that keeps rejecting must not be retried forever — two
    reconnect attempts, then the stack stays dead."""
    from unittest.mock import AsyncMock

    from pybluehost.hci.constants import ErrorCode
    from pybluehost.hci.packets import HCI_Disconnection_Complete_Event

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    stack._resume_watch_timeout = 0.02
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        monkeypatch.setattr(stack._smp, "start_initiator", AsyncMock())
        connect_gatt = AsyncMock(return_value=0x0041)
        monkeypatch.setattr(stack, "connect_gatt", connect_gatt)

        for attempt in range(4):
            handle = 0x0040 + attempt
            await stack._on_hci_event(_central_conn_complete(peer, handle=handle))
            await asyncio.sleep(0.05)  # auto-encrypt + watcher arm
            await stack._on_encryption_change(handle, 0x08, 0)
            await stack._on_hci_event(HCI_Disconnection_Complete_Event(
                status=ErrorCode.SUCCESS,
                connection_handle=handle,
                reason=ErrorCode.REMOTE_USER_TERMINATED,
            ))
            await asyncio.sleep(0.05)

        assert connect_gatt.await_count == 2
    finally:
        await stack.close()


async def test_clean_resume_disconnect_does_not_reconnect(tmp_path, monkeypatch):
    """A clean resume followed by a scripted disconnect never reconnects on its
    own — the next connection is the test script's business (WID 78)."""
    from unittest.mock import AsyncMock

    from pybluehost.hci.constants import ErrorCode
    from pybluehost.hci.packets import HCI_Disconnection_Complete_Event

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0x1234, rand=b"\xDD" * 8,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        monkeypatch.setattr(stack._smp, "start_initiator", AsyncMock())
        connect_gatt = AsyncMock(return_value=0x0041)
        monkeypatch.setattr(stack, "connect_gatt", connect_gatt)

        await stack._on_hci_event(_central_conn_complete(peer))
        await asyncio.sleep(0.1)  # auto-encrypt armed, then:
        await stack._on_encryption_change(0x0040, 0x00, 1)  # success — stash cleared
        await stack._on_hci_event(HCI_Disconnection_Complete_Event(
            status=ErrorCode.SUCCESS,
            connection_handle=0x0040,
            reason=ErrorCode.REMOTE_USER_TERMINATED,
        ))
        await asyncio.sleep(0.1)
        connect_gatt.assert_not_awaited()
    finally:
        await stack.close()


async def test_central_peer_abort_drop_does_not_autoreconnect(tmp_path, monkeypatch):
    """GAP/SEC/AUT/BV-25 regression: a scripted Pairing Failed after the
    preamble is NOT proof that the LT waits for an IUT reconnect. BV-27 and
    BV-25 have the same on-air fingerprint, and auto-reconnecting on it made
    BV-25 stall. Leave reconnection to the WID-driven test script; an explicit
    rejected bond-resume still has its own reconnect-and-repair path."""
    from unittest.mock import AsyncMock

    from pybluehost.hci.constants import ErrorCode
    from pybluehost.hci.packets import HCI_Disconnection_Complete_Event

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0, rand=b"\x00" * 8, sc=True,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        monkeypatch.setattr(stack._smp, "start_initiator", AsyncMock())
        connect_gatt = AsyncMock(return_value=0x0041)
        monkeypatch.setattr(stack, "connect_gatt", connect_gatt)

        await stack._on_hci_event(_central_conn_complete(peer))
        await asyncio.sleep(0.05)
        # BV-25 emits this same scripted abort before its WID-driven reconnect.
        stack._smp._emit_pairing_failed(0x0040, 0x08)
        await stack._on_hci_event(HCI_Disconnection_Complete_Event(
            status=ErrorCode.SUCCESS,
            connection_handle=0x0040,
            reason=ErrorCode.REMOTE_USER_TERMINATED,
        ))
        await asyncio.sleep(0.1)
        connect_gatt.assert_not_awaited()
    finally:
        await stack.close()


async def test_peer_drop_after_a_clean_pairing_does_not_autoreconnect(tmp_path, monkeypatch):
    """GAP/SEC/SEM/BV-45: the pairing AND the encryption both succeed, then the
    LT drops the link — and immediately scripts its own reconnect (WID 78).
    Racing that with an auto-reconnect wedges the controller's single
    initiator slot (pending 0x200D vs the WID's connect -> 0x0C / Connection
    Complete 0x02) and the WID connect fails. Only a peer that ABORTED the
    pairing before dropping (the BV-27 fingerprint) earns an auto-reconnect;
    a clean-pairing drop is the LT's own business."""
    from unittest.mock import AsyncMock

    from pybluehost.hci.constants import ErrorCode
    from pybluehost.hci.packets import HCI_Disconnection_Complete_Event

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    await storage.save_bond(BondInfo(
        peer_address=peer, address_type=0,
        ltk=b"\xCC" * 16, ediv=0, rand=b"\x00" * 8, sc=True,
    ))
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        monkeypatch.setattr(stack._smp, "start_initiator", AsyncMock())
        connect_gatt = AsyncMock(return_value=0x0042)
        monkeypatch.setattr(stack, "connect_gatt", connect_gatt)

        await stack._on_hci_event(_central_conn_complete(peer))
        await asyncio.sleep(0.05)
        # No peer Pairing Failed: the pairing completed cleanly and the LT
        # simply hung up (Encryption_Change status=0x00, ltk_stored, 0x13).
        await stack._on_hci_event(HCI_Disconnection_Complete_Event(
            status=ErrorCode.SUCCESS,
            connection_handle=0x0040,
            reason=ErrorCode.REMOTE_USER_TERMINATED,
        ))
        await asyncio.sleep(0.1)
        connect_gatt.assert_not_awaited()
    finally:
        await stack.close()


async def test_peer_drop_without_bond_does_not_autoreconnect(tmp_path, monkeypatch):
    """A fresh (unbonded) central link dropping is the LT's business —
    GATT/CL discovery rounds reconnect via WIDs, not on our own."""
    from unittest.mock import AsyncMock

    from pybluehost.hci.constants import ErrorCode
    from pybluehost.hci.packets import HCI_Disconnection_Complete_Event

    storage = JsonBondStorage(tmp_path / "bonds.json")
    peer = BDAddress(b"\x01\x02\x03\x04\x05\x06")
    stack = await Stack.virtual(config=StackConfig(bond_storage=storage))
    try:
        monkeypatch.setattr(stack._hci, "send_command", AsyncMock())
        connect_gatt = AsyncMock(return_value=0x0041)
        monkeypatch.setattr(stack, "connect_gatt", connect_gatt)

        await stack._on_hci_event(_central_conn_complete(peer))
        await asyncio.sleep(0.05)
        await stack._on_hci_event(HCI_Disconnection_Complete_Event(
            status=ErrorCode.SUCCESS,
            connection_handle=0x0040,
            reason=ErrorCode.REMOTE_USER_TERMINATED,
        ))
        await asyncio.sleep(0.1)
        connect_gatt.assert_not_awaited()
    finally:
        await stack.close()
