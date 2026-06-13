from pybluehost.profiles.classic._hsp_constants import (
    HEADSET_UUID, HSP_HS_UUID, HSP_AG_UUID,
    HSP_PROFILE_VERSION,
    HSP_HS_RFCOMM_CHANNEL, HSP_AG_RFCOMM_CHANNEL,
    HSP_AT_VGS, HSP_AT_VGM, HSP_AT_CKPD,
    HSP_DEFAULT_GAIN, HSP_GAIN_MAX,
)


def test_hsp_uuids():
    assert HEADSET_UUID == 0x1108        # generic Headset
    assert HSP_HS_UUID == 0x1131         # HS role (v1.2)
    assert HSP_AG_UUID == 0x1112         # AG role


def test_hsp_profile_version():
    # HSP v1.2 = 0x0102
    assert HSP_PROFILE_VERSION == 0x0102


def test_rfcomm_channels():
    # BlueZ default conventions used by Plan A.5
    assert HSP_HS_RFCOMM_CHANNEL == 5
    assert HSP_AG_RFCOMM_CHANNEL == 12


def test_at_command_names():
    assert HSP_AT_VGS == "+VGS"
    assert HSP_AT_VGM == "+VGM"
    assert HSP_AT_CKPD == "+CKPD"


def test_gain_constants():
    # HSP §5.4 — gain values 0..15
    assert HSP_DEFAULT_GAIN == 7
    assert HSP_GAIN_MAX == 15
