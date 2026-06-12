"""Tests for HCI SCO Data Packet encode/decode — Bluetooth Core §5.4.3."""
import pytest

from pybluehost.hci.packets import HCISCOData
from pybluehost.hci.sco_constants import (
    SCO_TRANSPORT_HCI, SCO_PACKET_STATUS_OK, SCO_PACKET_STATUS_INVALID,
)


def test_sco_data_to_bytes_layout():
    pkt = HCISCOData(
        handle=0x0042, packet_status=SCO_PACKET_STATUS_OK,
        data=bytes([0xAA, 0xBB, 0xCC]),
    )
    raw = pkt.to_bytes()
    # byte 0: handle low = 0x42
    # byte 1: handle high (high 4 bits = 0) << 0 | PSF=00 << 4 | RFU << 6
    #         → handle high 0x00, PSF=00 → 0x00
    # byte 2: length = 3
    assert raw[0] == 0x42
    assert raw[1] == 0x00
    assert raw[2] == 0x03
    assert raw[3:] == bytes([0xAA, 0xBB, 0xCC])
    assert len(raw) == 6


def test_sco_data_handle_high_bits_encoded():
    pkt = HCISCOData(handle=0x0F42, packet_status=0, data=b"\x00")
    raw = pkt.to_bytes()
    # handle 0x0F42: low byte 0x42, high nibble 0x0F → byte 1 bits 0..3 = 0xF
    assert raw[0] == 0x42
    assert (raw[1] & 0x0F) == 0x0F


def test_sco_data_psf_encoded():
    pkt = HCISCOData(handle=0x0001, packet_status=SCO_PACKET_STATUS_INVALID, data=b"")
    raw = pkt.to_bytes()
    # PSF in bits 4..5 of byte 1; INVALID=1 → bit 4 set → 0x10
    assert raw[1] == 0x10


def test_sco_data_from_bytes_round_trip():
    original = HCISCOData(handle=0x0F42, packet_status=0, data=b"\xDE\xAD\xBE\xEF")
    decoded = HCISCOData.from_bytes(original.to_bytes())
    assert decoded.handle == 0x0F42
    assert decoded.packet_status == 0
    assert decoded.data == b"\xDE\xAD\xBE\xEF"


def test_sco_data_from_bytes_too_short_raises():
    with pytest.raises(ValueError, match="too short"):
        HCISCOData.from_bytes(b"\x42\x00")    # missing length byte


def test_sco_data_length_mismatch_raises():
    # length byte says 5 but only 2 bytes of payload
    raw = bytes([0x42, 0x00, 0x05, 0xAA, 0xBB])
    with pytest.raises(ValueError, match="length"):
        HCISCOData.from_bytes(raw)


def test_sco_constants():
    assert SCO_TRANSPORT_HCI == 0x03
    assert SCO_PACKET_STATUS_OK == 0
    assert SCO_PACKET_STATUS_INVALID == 1
