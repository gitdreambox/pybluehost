from pybluehost.avdtp.constants import (
    AVDTPSignalID, AVDTPPacketType, AVDTPMessageType,
    AVDTPErrorCode, MediaType, TSEP, ServiceCategory,
    PSM_AVDTP,
)


def test_psm_avdtp_value():
    assert PSM_AVDTP == 0x0019


def test_signal_ids_per_spec():
    # AVDTP v1.3 §8.5 — signal IDs are 6-bit, values 1..13 used
    assert AVDTPSignalID.DISCOVER == 0x01
    assert AVDTPSignalID.GET_CAPABILITIES == 0x02
    assert AVDTPSignalID.SET_CONFIGURATION == 0x03
    assert AVDTPSignalID.GET_CONFIGURATION == 0x04
    assert AVDTPSignalID.RECONFIGURE == 0x05
    assert AVDTPSignalID.OPEN == 0x06
    assert AVDTPSignalID.START == 0x07
    assert AVDTPSignalID.CLOSE == 0x08
    assert AVDTPSignalID.SUSPEND == 0x09
    assert AVDTPSignalID.ABORT == 0x0A
    assert AVDTPSignalID.SECURITY_CONTROL == 0x0B
    assert AVDTPSignalID.GET_ALL_CAPABILITIES == 0x0C
    assert AVDTPSignalID.DELAYREPORT == 0x0D


def test_packet_types():
    assert AVDTPPacketType.SINGLE == 0
    assert AVDTPPacketType.START == 1
    assert AVDTPPacketType.CONTINUE == 2
    assert AVDTPPacketType.END == 3


def test_message_types():
    assert AVDTPMessageType.COMMAND == 0
    assert AVDTPMessageType.GENERAL_REJECT == 1
    assert AVDTPMessageType.RESPONSE_ACCEPT == 2
    assert AVDTPMessageType.RESPONSE_REJECT == 3


def test_tsep_constants():
    assert TSEP.SRC == 0
    assert TSEP.SNK == 1


def test_media_type_audio():
    assert MediaType.AUDIO == 0x00


def test_error_codes_per_spec():
    # AVDTP v1.3 §8.20 — sample a representative set across signaling, payload,
    # capability, and state error ranges.
    assert AVDTPErrorCode.BAD_HEADER_FORMAT == 0x01
    assert AVDTPErrorCode.BAD_LENGTH == 0x11
    assert AVDTPErrorCode.BAD_ACP_SEID == 0x12
    assert AVDTPErrorCode.SEP_IN_USE == 0x13
    assert AVDTPErrorCode.SEP_NOT_IN_USE == 0x14
    assert AVDTPErrorCode.NOT_SUPPORTED_COMMAND == 0x19
    assert AVDTPErrorCode.INVALID_CAPABILITIES == 0x1A
    assert AVDTPErrorCode.UNSUPPORTED_CONFIGURATION == 0x29
    assert AVDTPErrorCode.BAD_STATE == 0x31


def test_service_categories():
    # AVDTP v1.3 §8.21 service capability categories
    assert ServiceCategory.MEDIA_TRANSPORT == 0x01
    assert ServiceCategory.REPORTING == 0x02
    assert ServiceCategory.RECOVERY == 0x03
    assert ServiceCategory.CONTENT_PROTECTION == 0x04
    assert ServiceCategory.HEADER_COMPRESSION == 0x05
    assert ServiceCategory.MULTIPLEXING == 0x06
    assert ServiceCategory.MEDIA_CODEC == 0x07
    assert ServiceCategory.DELAY_REPORTING == 0x08
