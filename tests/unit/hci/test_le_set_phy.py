"""HCI_LE_Set_PHY command + LE_PHY_Update_Complete subevent parsing.

Wire layout verified against Bluetooth Core Spec 5.4 Vol 4 Part E
§7.8.49 (command) and §7.7.65.12 (event).
"""
from __future__ import annotations

import pytest

from pybluehost.hci.constants import HCI_LE_SET_PHY, LEPhy, LEPhyMask
from pybluehost.hci.packets import (
    HCI_LE_Set_PHY,
    LEPhyUpdateComplete,
    decode_hci_packet,
    parse_le_phy_update_complete,
)


def test_opcode_value():
    # OGF 0x08 << 10 | OCF 0x32 = 0x2032
    assert HCI_LE_SET_PHY == 0x2032


def test_encode_request_2m_both_directions():
    cmd = HCI_LE_Set_PHY(
        connection_handle=0x0040,
        all_phys=0x00,
        tx_phys=LEPhyMask.LE_2M,
        rx_phys=LEPhyMask.LE_2M,
        phy_options=0,
    )
    data = cmd.to_bytes()
    assert data[0] == 0x01            # H4 command type
    assert data[1:3] == bytes([0x32, 0x20])  # opcode LE-byte order
    assert data[3] == 7               # parameter length
    # 2 handle + 1 all_phys + 1 tx + 1 rx + 2 opts
    assert data[4:6] == bytes([0x40, 0x00])
    assert data[6] == 0x00            # all_phys
    assert data[7] == LEPhyMask.LE_2M
    assert data[8] == LEPhyMask.LE_2M
    assert data[9:11] == bytes([0x00, 0x00])


def test_encode_no_preference_lets_controller_choose():
    cmd = HCI_LE_Set_PHY(
        connection_handle=0x0001, all_phys=0x03,
        tx_phys=0, rx_phys=0, phy_options=0,
    )
    data = cmd.to_bytes()
    # all_phys bit 0 and bit 1 set → host has no preference for TX or RX
    assert data[6] == 0x03
    # TX/RX bitmasks are then ignored by controller (per spec); we just
    # round-trip whatever the caller passed.
    assert data[7] == 0x00
    assert data[8] == 0x00


def test_encode_or_of_masks_for_multiple_pref():
    cmd = HCI_LE_Set_PHY(
        connection_handle=0x0010, all_phys=0x00,
        tx_phys=LEPhyMask.LE_1M | LEPhyMask.LE_2M,
        rx_phys=LEPhyMask.LE_1M | LEPhyMask.LE_2M,
        phy_options=0,
    )
    data = cmd.to_bytes()
    assert data[7] == 0x03  # 1M | 2M
    assert data[8] == 0x03


def test_decode_roundtrip():
    raw = bytes([
        0x01,                          # HCI command
        0x32, 0x20,                    # opcode LE
        0x07,                          # length
        0x40, 0x00,                    # handle 0x0040
        0x00,                          # all_phys
        LEPhyMask.LE_2M,               # tx
        LEPhyMask.LE_2M,               # rx
        0x00, 0x00,                    # phy_options
    ])
    pkt = decode_hci_packet(raw)
    assert isinstance(pkt, HCI_LE_Set_PHY)
    assert pkt.connection_handle == 0x0040
    assert pkt.all_phys == 0
    assert pkt.tx_phys == LEPhyMask.LE_2M
    assert pkt.rx_phys == LEPhyMask.LE_2M


def test_phy_mask_constants():
    # Bitmask layout: bit 0 = 1M, 1 = 2M, 2 = Coded. Spec §7.8.49.
    assert LEPhyMask.LE_1M == 0x01
    assert LEPhyMask.LE_2M == 0x02
    assert LEPhyMask.LE_CODED == 0x04


def test_phy_value_constants():
    # Single-value encoding used by LE_PHY_Update_Complete. Spec §7.7.65.12.
    assert LEPhy.LE_1M == 0x01
    assert LEPhy.LE_2M == 0x02
    assert LEPhy.LE_CODED == 0x03


def test_parse_phy_update_complete_2m_negotiated():
    # status=0, handle=0x0040, tx=2M, rx=2M
    body = bytes([0x00, 0x40, 0x00, 0x02, 0x02])
    parsed = parse_le_phy_update_complete(body)
    assert parsed == LEPhyUpdateComplete(
        status=0, connection_handle=0x0040,
        tx_phy=LEPhy.LE_2M, rx_phy=LEPhy.LE_2M,
    )


def test_parse_phy_update_complete_asymmetric():
    # status=0, handle=0x0001, tx=2M, rx=1M (asymmetric PHY allowed)
    body = bytes([0x00, 0x01, 0x00, LEPhy.LE_2M, LEPhy.LE_1M])
    parsed = parse_le_phy_update_complete(body)
    assert parsed.tx_phy == LEPhy.LE_2M
    assert parsed.rx_phy == LEPhy.LE_1M


def test_parse_phy_update_complete_failure_status_preserved():
    # status=0x1F (Unspecified Error) — handler should still parse so the
    # caller can surface the failure code.
    body = bytes([0x1F, 0x40, 0x00, 0x00, 0x00])
    parsed = parse_le_phy_update_complete(body)
    assert parsed.status == 0x1F
    assert parsed.connection_handle == 0x0040


def test_parse_phy_update_complete_short_payload_raises():
    with pytest.raises(ValueError):
        parse_le_phy_update_complete(bytes([0x00, 0x40, 0x00]))
