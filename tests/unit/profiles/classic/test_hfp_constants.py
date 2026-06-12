from pybluehost.profiles.classic._hfp_constants import (
    HFPCodecID, HFPCallState, HFPCallSetupState, HFPIndicator,
    HFFeature, AGFeature,
    HFP_HF_UUID, HFP_AG_UUID, HANDSFREE_UUID,
    HFP_PROFILE_VERSION,
)


def test_hfp_uuids():
    # HFP v1.8 §5.4 service-class assignments
    assert HFP_HF_UUID == 0x111E       # HandsfreeAudioGateway? no — HF role
    assert HFP_AG_UUID == 0x111F       # HandsfreeAudioGateway role
    assert HANDSFREE_UUID == 0x111E    # generic handsfree (same as HF)


def test_hfp_profile_version():
    # HFP v1.8 binary version code per HFP §5.3.1
    assert HFP_PROFILE_VERSION == 0x0108


def test_codec_ids():
    # HFP v1.8 §5.4.2.3
    assert HFPCodecID.CVSD == 1
    assert HFPCodecID.MSBC == 2


def test_call_states():
    # HFP v1.8 §4.34 +CIND ranges
    assert HFPCallState.NO_CALL == 0
    assert HFPCallState.ACTIVE == 1


def test_callsetup_states():
    # HFP v1.8 §4.34 +CIND callsetup ranges
    assert HFPCallSetupState.NONE == 0
    assert HFPCallSetupState.INCOMING == 1
    assert HFPCallSetupState.OUTGOING == 2
    assert HFPCallSetupState.OUTGOING_ALERTING == 3


def test_indicator_table():
    # HFP §4.34 standard indicator names
    assert HFPIndicator.SERVICE == "service"
    assert HFPIndicator.CALL == "call"
    assert HFPIndicator.CALLSETUP == "callsetup"


def test_hf_feature_bits():
    # HFP v1.8 §4.34.1 — HF features bitmask
    assert HFFeature.EC_NR == 1 << 0
    assert HFFeature.THREE_WAY == 1 << 1
    assert HFFeature.CLI == 1 << 2
    assert HFFeature.VOICE_RECOGNITION == 1 << 3
    assert HFFeature.REMOTE_VOLUME_CONTROL == 1 << 4
    assert HFFeature.ENHANCED_CALL_STATUS == 1 << 5
    assert HFFeature.ENHANCED_CALL_CONTROL == 1 << 6
    assert HFFeature.CODEC_NEGOTIATION == 1 << 7
    assert HFFeature.HF_INDICATORS == 1 << 8
    assert HFFeature.ESCO_S4_T2 == 1 << 9


def test_ag_feature_bits():
    # HFP v1.8 §4.34.2 — AG features bitmask
    assert AGFeature.THREE_WAY == 1 << 0
    assert AGFeature.EC_NR == 1 << 1
    assert AGFeature.VOICE_RECOGNITION == 1 << 2
    assert AGFeature.IN_BAND_RING == 1 << 3
    assert AGFeature.VOICE_TAG == 1 << 4
    assert AGFeature.REJECT_CALL == 1 << 5
    assert AGFeature.ENHANCED_CALL_STATUS == 1 << 6
    assert AGFeature.ENHANCED_CALL_CONTROL == 1 << 7
    assert AGFeature.EXTENDED_ERROR == 1 << 8
    assert AGFeature.CODEC_NEGOTIATION == 1 << 9
    assert AGFeature.HF_INDICATORS == 1 << 10
    assert AGFeature.ESCO_S4_T2 == 1 << 11
