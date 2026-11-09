"""LE Secure Connections OOB pairing (Core Vol 3 Part H §2.3.5.6.4).

PTS SM/*/SCOB: PTS reads the IUT's OOB block (BTP OOB_SC_GET_LOCAL_DATA 0x19,
WID 147/148) and pushes the Lower Tester's block (OOB_SC_SET_REMOTE_DATA 0x1a,
WID 149). Unlike legacy OOB (shared TK), SC OOB:

- commits C = f4(PKx, PKx, r, 0) to the device's OWN public key out of band;
- drops the over-the-air Pairing Confirm PDU (only Public Key + Random are
  exchanged in band);
- uses fresh Na/Nb for f5 but the OOB randoms for the f6 r-input
  (EA uses rb = responder's OOB random, EB uses ra = initiator's OOB random).

These tests drive a full handshake against a peer that computes every expected
value independently from the spec formula, so a wrong r selection / confirm
formula / PDU sequence fails loudly.
"""
from __future__ import annotations

import pytest

from pybluehost.ble._smp_sc_crypto import compute_dhkey, generate_p256_keypair
from pybluehost.ble._smp_state import (
    _local_sc_address,
    _peer_sc_address,
    _sc_f4,
    _sc_f5,
    _sc_f6,
)
from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import (
    SMPCode,
    SMPManager,
    SMPPairingDHKeyCheck,
    SMPPairingPublicKey,
    SMPPairingRandom,
    SMPPairingRequest,
    SMPPairingResponse,
)
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability

HANDLE = 0x0800
IUT_ADDR = BDAddress(b"\x11\x22\x33\x44\x55\x66")
PEER_ADDR = BDAddress(b"\x01\x02\x03\x04\x05\x06")


def _make_manager(io_caps=IOCapability.DISPLAY_ONLY):
    sent: list[bytes] = []

    async def send(data: bytes) -> None:
        sent.append(data)

    mgr = SMPManager(
        local_io_caps=io_caps,
        bondable=True,
        security_config=SecurityConfig(enable_secure_connections=True),
    )
    mgr.set_local_address(IUT_ADDR)
    mgr.bind_channel(connection_handle=HANDLE, send=send, peer_address=PEER_ADDR)
    return mgr, sent


class _Peer:
    """Simulated Lower Tester with its own keypair + OOB block."""

    def __init__(self, io_caps=IOCapability.KEYBOARD_DISPLAY):
        self.priv, self.pub = generate_p256_keypair()
        self.rand = bytes(range(16))           # this peer's OOB random
        self.conf = _sc_f4(self.pub[:32], self.pub[:32], self.rand, 0)
        self.io_caps = io_caps
        self.oob_flag = 1
        self.auth_req = 0x09                   # bonding + SC

    def public_key_pdu(self) -> bytes:
        return SMPPairingPublicKey(
            public_key_x=self.pub[:32], public_key_y=self.pub[32:],
        ).to_bytes()


def test_get_local_data_consistent_and_commits_to_own_pubkey():
    """WID 147 (conf) and 148 (rand) must return a consistent (r, C) pair, and
    C must equal f4(PKx, PKx, r, 0) over the cached keypair."""
    mgr, _ = _make_manager()
    r1, c1 = mgr.get_oob_sc_local_data()
    r2, c2 = mgr.get_oob_sc_local_data()
    assert (r1, c1) == (r2, c2), "get_local_data must be idempotent per process"
    pub = mgr._oob_sc_local["pub"]
    assert c1 == _sc_f4(pub[:32], pub[:32], r1, 0)


def test_association_model_oob_requires_remote_data_or_peer_flag():
    """The OOB model is selected when we hold the peer's OOB block (remote) or
    the peer advertised OOB — NOT merely because we generated a local block
    (the OOB data flag means "remote OOB data present")."""
    from pybluehost.ble._smp_state import _association_model
    import pybluehost.ble.smp as smp_mod

    mgr, _ = _make_manager()
    mgr.get_oob_sc_local_data()  # local block only

    def _ctx():
        c = smp_mod.SMPPairingContext.create(
            connection_handle=HANDLE, peer_address=PEER_ADDR,
            role=smp_mod.PairingRole.INITIATOR,
        )
        mgr._apply_oob_sc(c)
        c.local_auth_req = 0x09
        c.peer_auth_req = 0x09
        c.security_config = SecurityConfig(enable_secure_connections=True)
        return c

    # Local block alone: not OOB (we have nothing of the peer's).
    assert _association_model(_ctx()) != "oob"
    # Received the peer's OOB block -> OOB.
    c = _ctx()
    mgr.set_oob_sc_remote_data(bytes(16), bytes(16))
    mgr._apply_oob_sc(c)
    assert _association_model(c) == "oob"
    # Or the peer advertised OOB in its flag -> OOB.
    c = _ctx()
    c.peer_oob_data_flag = 1
    assert _association_model(c) == "oob"


@pytest.mark.asyncio
async def test_initiator_full_oob_handshake():
    """IUT=Central initiates SC OOB. Expect: oob flag in Pairing Request, OOB
    keypair reused, NO Confirm PDU, Random right after public key, and an EA the
    peer can reproduce with f6(.., rb=responder's OOB rand, ..)."""
    mgr, sent = _make_manager()
    r_local, c_local = mgr.get_oob_sc_local_data()
    peer = _Peer()
    mgr.set_oob_sc_remote_data(peer.rand, peer.conf)

    fut = await mgr.start_initiator(HANDLE)
    assert sent[0][0] == SMPCode.PAIRING_REQUEST
    assert sent[0][2] == 0x01, "oob_data_flag must be 1 with SC OOB data"

    # Peer (responder) answers: SC + OOB flag.
    await mgr.on_pdu(SMPPairingResponse(
        io_capability=peer.io_caps, oob_data_flag=1, auth_req=peer.auth_req,
        max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=HANDLE)
    assert sent[-1][0] == SMPCode.PAIRING_PUBLIC_KEY
    # The public key sent must be the one our OOB confirm committed to.
    iut_pub = mgr._oob_sc_local["pub"]
    assert sent[-1][1:33] == iut_pub[:32]

    # Peer sends its public key -> IUT must skip Confirm and send Random.
    n_before = len(sent)
    await mgr.on_pdu(peer.public_key_pdu(), connection_handle=HANDLE)
    assert sent[-1][0] == SMPCode.PAIRING_RANDOM, \
        "SC OOB must NOT send a Pairing Confirm; Random follows the public key"
    assert all(sent[i][0] != SMPCode.PAIRING_CONFIRM for i in range(n_before, len(sent)))
    na = sent[-1][1:17]

    # Peer derives the shared secrets independently.
    ctx = mgr.get_context(HANDLE)
    a_addr = _local_sc_address(ctx)   # A = initiator = IUT
    b_addr = _peer_sc_address(ctx)    # B = responder = peer
    dhkey = compute_dhkey(peer.priv, iut_pub)
    nb = bytes([0xA5] * 16)
    mac_key, ltk = _sc_f5(dhkey, na, nb, a_addr, b_addr)

    # Peer sends its Random -> IUT derives f5 and emits EA (DHKey Check).
    await mgr.on_pdu(SMPPairingRandom(random_value=nb).to_bytes(), connection_handle=HANDLE)
    assert sent[-1][0] == SMPCode.PAIRING_DHKEY_CHECK
    ea_sent = sent[-1][1:17]
    io_cap_a = bytes([int(mgr._local_io_caps), 0x01, sent[0][3]])
    ea_expect = _sc_f6(mac_key, na, nb, peer.rand, io_cap_a, a_addr, b_addr)
    assert ea_sent == ea_expect, "EA must use rb = responder's OOB random"

    # Peer answers with EB (ra = initiator's OOB random) -> IUT accepts.
    io_cap_b = bytes([int(peer.io_caps), 0x01, peer.auth_req])
    eb = _sc_f6(mac_key, nb, na, r_local, io_cap_b, b_addr, a_addr)

    class _FakeHCI:
        def __init__(self):
            self.ltk = None

        async def send_command(self, cmd):
            self.ltk = getattr(cmd, "long_term_key", None)

    hci = _FakeHCI()
    mgr.get_context(HANDLE)._hci = hci
    await mgr.on_pdu(SMPPairingDHKeyCheck(dhkey_check=eb).to_bytes(),
                     connection_handle=HANDLE)
    assert hci.ltk == ltk, "initiator must start encryption with the f5 LTK"
    fut.cancel()


@pytest.mark.asyncio
async def test_responder_full_oob_handshake():
    """IUT=Peripheral responds to SC OOB. Expect: oob flag in Pairing Response,
    NO Confirm PDU after public key, Random exchange, and an EB the peer can
    reproduce with f6(.., ra=initiator's OOB rand, ..)."""
    mgr, sent = _make_manager()
    r_local, c_local = mgr.get_oob_sc_local_data()
    peer = _Peer()
    mgr.set_oob_sc_remote_data(peer.rand, peer.conf)

    # Peer (initiator) opens pairing: SC + OOB flag.
    await mgr.on_pdu(SMPPairingRequest(
        io_capability=peer.io_caps, oob_data_flag=1, auth_req=peer.auth_req,
        max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=HANDLE)
    assert sent[0][0] == SMPCode.PAIRING_RESPONSE
    assert sent[0][2] == 0x01, "responder must advertise oob_data_flag=1"

    # Peer sends its public key -> IUT sends its public key, NO Confirm.
    await mgr.on_pdu(peer.public_key_pdu(), connection_handle=HANDLE)
    assert sent[-1][0] == SMPCode.PAIRING_PUBLIC_KEY
    assert all(b[0] != SMPCode.PAIRING_CONFIRM for b in sent), \
        "SC OOB responder must not emit a Pairing Confirm PDU"
    iut_pub = mgr._oob_sc_local["pub"]
    assert sent[-1][1:33] == iut_pub[:32]

    # Peer (initiator) sends its Random Na -> IUT replies with its Random Nb.
    na = bytes([0x5A] * 16)
    await mgr.on_pdu(SMPPairingRandom(random_value=na).to_bytes(), connection_handle=HANDLE)
    assert sent[-1][0] == SMPCode.PAIRING_RANDOM
    nb = sent[-1][1:17]

    # Peer computes secrets independently (A = initiator = peer, B = responder = IUT).
    ctx = mgr.get_context(HANDLE)
    b_addr = _local_sc_address(ctx)   # B = responder = IUT
    a_addr = _peer_sc_address(ctx)    # A = initiator = peer
    dhkey = compute_dhkey(peer.priv, iut_pub)
    mac_key, ltk = _sc_f5(dhkey, na, nb, a_addr, b_addr)

    # Peer sends EA (rb = responder's OOB random = IUT's r_local).
    io_cap_a = bytes([int(peer.io_caps), 0x01, peer.auth_req])
    ea = _sc_f6(mac_key, na, nb, r_local, io_cap_a, a_addr, b_addr)
    n_before = len(sent)
    await mgr.on_pdu(SMPPairingDHKeyCheck(dhkey_check=ea).to_bytes(),
                     connection_handle=HANDLE)
    assert len(sent) == n_before + 1 and sent[-1][0] == SMPCode.PAIRING_DHKEY_CHECK
    # IUT's EB must use ra = initiator's OOB random = peer.rand.
    io_cap_b = bytes([int(mgr._local_io_caps), 0x01, sent[0][3]])
    eb_expect = _sc_f6(mac_key, nb, na, peer.rand, io_cap_b, b_addr, a_addr)
    assert sent[-1][1:17] == eb_expect, "EB must use ra = initiator's OOB random"


@pytest.mark.asyncio
async def test_responder_rejects_wrong_oob_confirm():
    """SCOB BI: if the peer's in-band public key does not match the OOB confirm
    we hold, the responder must abort with Pairing Failed (no further PDUs)."""
    mgr, sent = _make_manager()
    mgr.get_oob_sc_local_data()
    peer = _Peer()
    # Push a confirm that does NOT match the public key the peer will send.
    mgr.set_oob_sc_remote_data(peer.rand, b"\xEE" * 16)

    await mgr.on_pdu(SMPPairingRequest(
        io_capability=peer.io_caps, oob_data_flag=1, auth_req=peer.auth_req,
        max_key_size=16, init_key_dist=0x07, resp_key_dist=0x07,
    ).to_bytes(), connection_handle=HANDLE)
    await mgr.on_pdu(peer.public_key_pdu(), connection_handle=HANDLE)

    assert sent[-1][0] == SMPCode.PAIRING_FAILED, \
        "mismatched OOB confirm must abort the pairing"
