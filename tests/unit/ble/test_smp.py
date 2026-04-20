"""Tests for the SMP (Security Manager Protocol) module.

Test vectors from Bluetooth Core Spec v5.4.
"""
from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from pybluehost.ble.smp import (
    AutoAcceptDelegate,
    BondInfo,
    BondStorage,
    JsonBondStorage,
    PairingDelegate,
    SMPCode,
    SMPCrypto,
    SMPEncryptionInformation,
    SMPIdentityAddressInformation,
    SMPIdentityInformation,
    SMPManager,
    SMPMasterIdentification,
    SMPPairingConfirm,
    SMPPairingFailed,
    SMPPairingRandom,
    SMPPairingRequest,
    SMPPairingResponse,
    SMPPdu,
    SMPSecurityRequest,
    SMPSigningInformation,
    decode_smp_pdu,
)
from pybluehost.core.address import BDAddress


# ---------------------------------------------------------------------------
# SMPCode enum
# ---------------------------------------------------------------------------

class TestSMPCode:
    def test_pairing_request_value(self) -> None:
        assert SMPCode.PAIRING_REQUEST == 0x01

    def test_pairing_response_value(self) -> None:
        assert SMPCode.PAIRING_RESPONSE == 0x02

    def test_pairing_confirm_value(self) -> None:
        assert SMPCode.PAIRING_CONFIRM == 0x03

    def test_pairing_random_value(self) -> None:
        assert SMPCode.PAIRING_RANDOM == 0x04

    def test_pairing_failed_value(self) -> None:
        assert SMPCode.PAIRING_FAILED == 0x05

    def test_encryption_information_value(self) -> None:
        assert SMPCode.ENCRYPTION_INFORMATION == 0x06

    def test_master_identification_value(self) -> None:
        assert SMPCode.MASTER_IDENTIFICATION == 0x07

    def test_identity_information_value(self) -> None:
        assert SMPCode.IDENTITY_INFORMATION == 0x08

    def test_identity_address_information_value(self) -> None:
        assert SMPCode.IDENTITY_ADDRESS_INFORMATION == 0x09

    def test_signing_information_value(self) -> None:
        assert SMPCode.SIGNING_INFORMATION == 0x0A

    def test_security_request_value(self) -> None:
        assert SMPCode.SECURITY_REQUEST == 0x0B

    def test_keypress_notification_value(self) -> None:
        assert SMPCode.KEYPRESS_NOTIFICATION == 0x0E


# ---------------------------------------------------------------------------
# SMP PDU encode/decode
# ---------------------------------------------------------------------------

class TestSMPPdu:
    def test_smp_pdu_pairing_request_encode(self) -> None:
        pdu = SMPPairingRequest(
            io_capability=0x03,
            oob_data_flag=0x00,
            auth_req=0x01,
            max_key_size=16,
            init_key_dist=0x01,
            resp_key_dist=0x01,
        )
        raw = pdu.to_bytes()
        assert raw[0] == SMPCode.PAIRING_REQUEST
        assert len(raw) == 7
        assert raw[1] == 0x03  # io_capability
        assert raw[2] == 0x00  # oob
        assert raw[3] == 0x01  # auth_req
        assert raw[4] == 16    # max key size
        assert raw[5] == 0x01  # init key dist
        assert raw[6] == 0x01  # resp key dist

    def test_smp_pdu_pairing_request_decode(self) -> None:
        raw = bytes([0x01, 0x03, 0x00, 0x01, 0x10, 0x01, 0x01])
        pdu = decode_smp_pdu(raw)
        assert isinstance(pdu, SMPPairingRequest)
        assert pdu.io_capability == 0x03
        assert pdu.max_key_size == 16

    def test_smp_pdu_pairing_response_roundtrip(self) -> None:
        pdu = SMPPairingResponse(
            io_capability=0x00,
            oob_data_flag=0x00,
            auth_req=0x05,
            max_key_size=16,
            init_key_dist=0x00,
            resp_key_dist=0x03,
        )
        raw = pdu.to_bytes()
        pdu2 = decode_smp_pdu(raw)
        assert isinstance(pdu2, SMPPairingResponse)
        assert pdu2.auth_req == 0x05
        assert pdu2.resp_key_dist == 0x03

    def test_smp_pdu_pairing_confirm_roundtrip(self) -> None:
        val = bytes(range(16))
        pdu = SMPPairingConfirm(confirm_value=val)
        raw = pdu.to_bytes()
        assert raw[0] == SMPCode.PAIRING_CONFIRM
        assert len(raw) == 17
        pdu2 = decode_smp_pdu(raw)
        assert isinstance(pdu2, SMPPairingConfirm)
        assert pdu2.confirm_value == val

    def test_smp_pdu_pairing_random_roundtrip(self) -> None:
        val = bytes(range(16))
        pdu = SMPPairingRandom(random_value=val)
        raw = pdu.to_bytes()
        assert raw[0] == SMPCode.PAIRING_RANDOM
        pdu2 = decode_smp_pdu(raw)
        assert isinstance(pdu2, SMPPairingRandom)
        assert pdu2.random_value == val

    def test_smp_pdu_pairing_failed_roundtrip(self) -> None:
        pdu = SMPPairingFailed(reason=0x06)
        raw = pdu.to_bytes()
        assert raw == bytes([0x05, 0x06])
        pdu2 = decode_smp_pdu(raw)
        assert isinstance(pdu2, SMPPairingFailed)
        assert pdu2.reason == 0x06

    def test_smp_pdu_encryption_information_roundtrip(self) -> None:
        ltk = bytes(range(16))
        pdu = SMPEncryptionInformation(long_term_key=ltk)
        raw = pdu.to_bytes()
        assert raw[0] == SMPCode.ENCRYPTION_INFORMATION
        pdu2 = decode_smp_pdu(raw)
        assert isinstance(pdu2, SMPEncryptionInformation)
        assert pdu2.long_term_key == ltk

    def test_smp_pdu_master_identification_roundtrip(self) -> None:
        pdu = SMPMasterIdentification(ediv=0x1234, rand=bytes(range(8)))
        raw = pdu.to_bytes()
        assert raw[0] == SMPCode.MASTER_IDENTIFICATION
        pdu2 = decode_smp_pdu(raw)
        assert isinstance(pdu2, SMPMasterIdentification)
        assert pdu2.ediv == 0x1234
        assert pdu2.rand == bytes(range(8))

    def test_smp_pdu_identity_information_roundtrip(self) -> None:
        irk = bytes(range(16))
        pdu = SMPIdentityInformation(irk=irk)
        raw = pdu.to_bytes()
        pdu2 = decode_smp_pdu(raw)
        assert isinstance(pdu2, SMPIdentityInformation)
        assert pdu2.irk == irk

    def test_smp_pdu_identity_address_information_roundtrip(self) -> None:
        pdu = SMPIdentityAddressInformation(
            addr_type=0x00, bd_addr=bytes.fromhex("A1A2A3A4A5A6")
        )
        raw = pdu.to_bytes()
        pdu2 = decode_smp_pdu(raw)
        assert isinstance(pdu2, SMPIdentityAddressInformation)
        assert pdu2.addr_type == 0x00
        assert pdu2.bd_addr == bytes.fromhex("A1A2A3A4A5A6")

    def test_smp_pdu_signing_information_roundtrip(self) -> None:
        csrk = bytes(range(16))
        pdu = SMPSigningInformation(signature_key=csrk)
        raw = pdu.to_bytes()
        pdu2 = decode_smp_pdu(raw)
        assert isinstance(pdu2, SMPSigningInformation)
        assert pdu2.signature_key == csrk

    def test_smp_pdu_security_request_roundtrip(self) -> None:
        pdu = SMPSecurityRequest(auth_req=0x0D)
        raw = pdu.to_bytes()
        assert raw == bytes([0x0B, 0x0D])
        pdu2 = decode_smp_pdu(raw)
        assert isinstance(pdu2, SMPSecurityRequest)
        assert pdu2.auth_req == 0x0D

    def test_decode_unknown_code_raises(self) -> None:
        with pytest.raises((ValueError, KeyError)):
            decode_smp_pdu(bytes([0xFF, 0x00]))


# ---------------------------------------------------------------------------
# SMPCrypto — BT Core Spec test vectors
# ---------------------------------------------------------------------------

class TestSMPCrypto:
    def test_c1(self) -> None:
        """BT Spec v5.4 sample data for c1 (Legacy Confirm)."""
        k = bytes(16)  # all zeros
        r = bytes.fromhex("5783D52156AD6F0E6388274EC6702EE0")
        preq = bytes.fromhex("07071000000110")
        pres = bytes.fromhex("05000800000302")
        iat = 1
        rat = 0
        ia = bytes.fromhex("A1A2A3A4A5A6")
        ra = bytes.fromhex("B1B2B3B4B5B6")
        result = SMPCrypto.c1(k, r, preq, pres, iat, rat, ia, ra)
        assert result == bytes.fromhex("5879c1c6d455dd39718f9b946248d19a")

    def test_s1(self) -> None:
        """BT Spec v5.4 sample data for s1 (Legacy STK)."""
        k = bytes(16)
        r1 = bytes.fromhex("000F0E0D0C0B0A091122334455667788")
        r2 = bytes.fromhex("010203040506070899AABBCCDDEEFF00")
        result = SMPCrypto.s1(k, r1, r2)
        assert result == bytes.fromhex("9a1fe1f0e8b0f49b5b4216ae796da062")

    def test_f4(self) -> None:
        """BT Spec v5.4 sample data for f4 (SC Confirm)."""
        U = bytes.fromhex(
            "20b003d2f297be2c5e2c83a7e9f9a5b9"
            "eff49111acf4fddbcc0301480e359de6"
        )
        V = bytes.fromhex(
            "55188b3d32f6bb9a900afcfbeed4e72a"
            "59cb9ac2f19d7cfb6b4fdd49f47fc5fd"
        )
        X = bytes.fromhex("d5cb8454d177733effffb2ec712baeab")
        Z = 0x00
        result = SMPCrypto.f4(U, V, X, Z)
        assert result == bytes.fromhex("f2c916f107a9bd1cf1eda1bea974872d")

    def test_f5(self) -> None:
        """BT Spec v5.4 sample data for f5 (SC Key Gen)."""
        W = bytes.fromhex(
            "ec0234a357c8ad05341010a60a397d9b"
            "99796b13b4f866f1868d34f373bfa698"
        )
        N1 = bytes.fromhex("d5cb8454d177733effffb2ec712baeab")
        N2 = bytes.fromhex("a6e8e7cc25a75f6e216583f7ff3dc4cf")
        A1 = bytes.fromhex("00561237372600")
        A2 = bytes.fromhex("00a713702dcfc1")
        mac_key, ltk = SMPCrypto.f5(W, N1, N2, A1, A2)
        assert mac_key == bytes.fromhex("b6e4b4603eec848cbc64f040215bea5d")
        assert ltk == bytes.fromhex("30d519df60bb21fc43c81426c805fb83")

    def test_f6(self) -> None:
        """BT Spec v5.4 sample data for f6 (SC DH-Key Check)."""
        W = bytes.fromhex("2965f176a1084a02fd3f6a20ce636e20")
        N1 = bytes.fromhex("d5cb8454d177733effffb2ec712baeab")
        N2 = bytes.fromhex("a6e8e7cc25a75f6e216583f7ff3dc4cf")
        R = bytes.fromhex("12a3343bb453bb5408da42d20c2d0fc8")
        IOcap = bytes.fromhex("010002")
        A1 = bytes.fromhex("00561237372600")
        A2 = bytes.fromhex("00a713702dcfc1")
        result = SMPCrypto.f6(W, N1, N2, R, IOcap, A1, A2)
        assert result == bytes.fromhex("634d0cd5b6900432f0f741873863530a")

    def test_g2(self) -> None:
        """BT Spec v5.4 sample data for g2 (SC Numeric Comparison)."""
        U = bytes.fromhex(
            "20b003d2f297be2c5e2c83a7e9f9a5b9"
            "eff49111acf4fddbcc0301480e359de6"
        )
        V = bytes.fromhex(
            "55188b3d32f6bb9a900afcfbeed4e72a"
            "59cb9ac2f19d7cfb6b4fdd49f47fc5fd"
        )
        X = bytes.fromhex("d5cb8454d177733effffb2ec712baeab")
        Y = bytes.fromhex("a6e8e7cc25a75f6e216583f7ff3dc4cf")
        result = SMPCrypto.g2(U, V, X, Y)
        assert result == 0x2F9ED5BA

    def test_ah(self) -> None:
        """BT Spec v5.4 sample data for ah (RPA hash)."""
        k = bytes.fromhex("ec0234a357c8ad05341010a60a397d9b")
        r = bytes.fromhex("708194")
        result = SMPCrypto.ah(k, r)
        assert result == bytes.fromhex("0dfbaa")

    def test_h6(self) -> None:
        """BT Spec v5.4 sample data for h6."""
        W = bytes.fromhex("ec0234a357c8ad05341010a60a397d9b")
        key_id = b"lebr"
        result = SMPCrypto.h6(W, key_id)
        assert result == bytes.fromhex("2d9ae102e76dc91ce8d3a9e280b16399")

    def test_h7(self) -> None:
        """BT Spec v5.4 sample data for h7."""
        SALT = bytes.fromhex("6c888391aab6e7ca8cbbc3c0d2db3473")
        W = bytes.fromhex("ec0234a357c8ad05341010a60a397d9b")
        result = SMPCrypto.h7(SALT, W)
        assert result == bytes.fromhex("f25c4ff3b6e92139faa2d16456311fd9")


# ---------------------------------------------------------------------------
# BondInfo
# ---------------------------------------------------------------------------

class TestBondInfo:
    def test_bond_info_defaults(self) -> None:
        addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
        bi = BondInfo(peer_address=addr)
        assert bi.ltk is None
        assert bi.irk is None
        assert bi.csrk is None
        assert bi.ediv == 0
        assert bi.rand == 0
        assert bi.key_size == 16
        assert bi.authenticated is False
        assert bi.sc is False

    def test_bond_info_with_ltk(self) -> None:
        addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
        bi = BondInfo(peer_address=addr, ltk=bytes(16), key_size=16)
        assert bi.ltk == bytes(16)


# ---------------------------------------------------------------------------
# BondStorage — JsonBondStorage
# ---------------------------------------------------------------------------

class TestJsonBondStorage:
    async def test_bond_storage_save_load(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "bonds.json"
        storage = JsonBondStorage(path)
        addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
        bi = BondInfo(peer_address=addr, ltk=bytes(16), authenticated=True)
        await storage.save_bond(bi)
        loaded = await storage.load_bond(addr)
        assert loaded is not None
        assert loaded.peer_address == addr
        assert loaded.ltk == bytes(16)
        assert loaded.authenticated is True

    async def test_bond_storage_missing_returns_none(
        self, tmp_path: pathlib.Path
    ) -> None:
        path = tmp_path / "bonds.json"
        storage = JsonBondStorage(path)
        addr = BDAddress.from_string("11:22:33:44:55:66")
        result = await storage.load_bond(addr)
        assert result is None

    async def test_bond_storage_list_bonds(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "bonds.json"
        storage = JsonBondStorage(path)
        addr1 = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
        addr2 = BDAddress.from_string("11:22:33:44:55:66")
        await storage.save_bond(BondInfo(peer_address=addr1))
        await storage.save_bond(BondInfo(peer_address=addr2))
        bonds = await storage.list_bonds()
        addrs = {str(b.peer_address) for b in bonds}
        assert "AA:BB:CC:DD:EE:FF" in addrs
        assert "11:22:33:44:55:66" in addrs

    async def test_bond_storage_delete(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "bonds.json"
        storage = JsonBondStorage(path)
        addr = BDAddress.from_string("AA:BB:CC:DD:EE:FF")
        await storage.save_bond(BondInfo(peer_address=addr, ltk=bytes(16)))
        await storage.delete_bond(addr)
        result = await storage.load_bond(addr)
        assert result is None


# ---------------------------------------------------------------------------
# PairingDelegate — AutoAcceptDelegate
# ---------------------------------------------------------------------------

class TestAutoAcceptDelegate:
    async def test_auto_accept_delegate_confirms_everything(self) -> None:
        delegate = AutoAcceptDelegate()
        assert await delegate.confirm_pairing(0x03, 0x01) is True
        assert await delegate.confirm_passkey(123456) is True
        assert await delegate.confirm_numeric_comparison(999999) is True
        passkey = await delegate.get_passkey()
        assert isinstance(passkey, int)
        assert 0 <= passkey <= 999999


# ---------------------------------------------------------------------------
# SMPManager — basic construction
# ---------------------------------------------------------------------------

class TestSMPManager:
    def test_smp_manager_construction(self) -> None:
        mgr = SMPManager(hci=None, bond_storage=None, delegate=AutoAcceptDelegate())
        assert mgr is not None
