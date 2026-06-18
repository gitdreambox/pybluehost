from pybluehost.classic.avctp.constants import (
    AVCTPPacketType, AVCTPMessageDirection,
    PSM_AVCTP, AVRCP_PROFILE_UUID, AVRCP_CONTROLLER_UUID, AVRCP_TARGET_UUID,
)


def test_psm_avctp_value():
    assert PSM_AVCTP == 0x0017


def test_packet_types():
    # AVCTP v1.4 §6.1 — 2-bit packet type field
    assert AVCTPPacketType.SINGLE == 0
    assert AVCTPPacketType.START == 1
    assert AVCTPPacketType.CONTINUE == 2
    assert AVCTPPacketType.END == 3


def test_direction_bits():
    # AVCTP v1.4 §6.1.1 — C/R bit
    assert AVCTPMessageDirection.COMMAND == 0
    assert AVCTPMessageDirection.RESPONSE == 1


def test_avrcp_profile_uuids():
    # AVRCP v1.6 §6 service-class assignments
    assert AVRCP_PROFILE_UUID == 0x110E       # AVRCP / "AVRemoteControl"
    assert AVRCP_CONTROLLER_UUID == 0x110F    # AVRCPController
    assert AVRCP_TARGET_UUID == 0x110C        # AVRCPTarget
