"""AVRCP v1.6 §6.7 REGISTER_NOTIFICATION + event responses.

All notifications ride the VENDOR_DEPENDENT AV/C opcode with the
Bluetooth SIG company ID and the metadata PDU subtype REGISTER_NOTIFICATION.
"""
from __future__ import annotations

import struct

from pybluehost.avrcp.constants import (
    AVCCtype, AVCOpCode, AVCSubunitType,
    AVRCPEventID, AVRCPMetadataPDU,
    AVRCP_BT_SIG_COMPANY_ID,
)
from pybluehost.avrcp.frame import AVCFrame


def _bt_sig_company_bytes() -> bytes:
    return struct.pack(">I", AVRCP_BT_SIG_COMPANY_ID & 0xFFFFFF)[1:]


def _vdu_operands(*, pdu_id: int, parameters: bytes) -> bytes:
    """Build the vendor-dependent operand block: company_id + PDU header + params."""
    return (
        _bt_sig_company_bytes()
        + bytes([pdu_id & 0xFF, 0x00])
        + struct.pack(">H", len(parameters))
        + parameters
    )


def build_register_notification_command(
    *,
    event_id: int,
    playback_interval: int = 0,
) -> AVCFrame:
    """AVRCP v1.6 §6.7 REGISTER_NOTIFICATION command (NOTIFY ctype)."""
    params = bytes([event_id & 0xFF]) + struct.pack(">I", playback_interval & 0xFFFFFFFF)
    return AVCFrame(
        ctype=AVCCtype.NOTIFY,
        subunit_type=AVCSubunitType.PANEL,
        subunit_id=0,
        opcode=AVCOpCode.VENDOR_DEPENDENT,
        operands=_vdu_operands(
            pdu_id=AVRCPMetadataPDU.REGISTER_NOTIFICATION,
            parameters=params,
        ),
    )


def build_notification_interim_response(
    *, event_id: int, event_payload: bytes,
) -> AVCFrame:
    """INTERIM response — sent immediately when REGISTER_NOTIFICATION arrives,
    carries the current event value."""
    return AVCFrame(
        ctype=AVCCtype.INTERIM,
        subunit_type=AVCSubunitType.PANEL,
        subunit_id=0,
        opcode=AVCOpCode.VENDOR_DEPENDENT,
        operands=_vdu_operands(
            pdu_id=AVRCPMetadataPDU.REGISTER_NOTIFICATION,
            parameters=bytes([event_id & 0xFF]) + event_payload,
        ),
    )


def build_notification_changed_response(
    *, event_id: int, event_payload: bytes,
) -> AVCFrame:
    """CHANGED response — sent later when the registered event actually fires."""
    return AVCFrame(
        ctype=AVCCtype.CHANGED,
        subunit_type=AVCSubunitType.PANEL,
        subunit_id=0,
        opcode=AVCOpCode.VENDOR_DEPENDENT,
        operands=_vdu_operands(
            pdu_id=AVRCPMetadataPDU.REGISTER_NOTIFICATION,
            parameters=bytes([event_id & 0xFF]) + event_payload,
        ),
    )


def parse_notification_response(frame: AVCFrame) -> tuple[AVCCtype, int, bytes]:
    """Returns (ctype, event_id, event_payload) from a notification response."""
    if frame.opcode != AVCOpCode.VENDOR_DEPENDENT:
        raise ValueError("not a VENDOR_DEPENDENT frame")
    if len(frame.operands) < 8:
        raise ValueError("notification response operands too short")
    company = frame.operands[0:3]
    if company != _bt_sig_company_bytes():
        raise ValueError(
            f"unexpected company id {company.hex()}, expected BT SIG 0x001958"
        )
    pdu_id = frame.operands[3]
    if pdu_id != AVRCPMetadataPDU.REGISTER_NOTIFICATION:
        raise ValueError(
            f"unexpected PDU id 0x{pdu_id:02X}, expected REGISTER_NOTIFICATION"
        )
    param_len = struct.unpack(">H", frame.operands[5:7])[0]
    params = bytes(frame.operands[7:7 + param_len])
    if len(params) < 1:
        raise ValueError("notification response missing event_id")
    return frame.ctype, params[0], params[1:]
