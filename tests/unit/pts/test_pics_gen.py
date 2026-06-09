"""Tests for PICS generator."""
import pytest

from pybluehost.pts.pics_gen import generate_pics_draft


def test_generate_pics_returns_dict_per_group():
    """PICS generator returns dict with one key per target group."""
    drafts = generate_pics_draft({})
    assert isinstance(drafts, dict)
    for group in ("HCI", "L2CAP", "GAP", "GATT", "SMP", "SDP", "RFCOMM"):
        assert group in drafts
        assert isinstance(drafts[group], dict)


def test_hci_pics_includes_supported_and_evidence():
    """Each feature entry has standard schema."""
    drafts = generate_pics_draft({})
    hci = drafts["HCI"]
    for feature_name, info in hci.items():
        assert "supported" in info
        assert "evidence" in info
        assert "description" in info
        assert isinstance(info["supported"], bool)


def test_pics_with_empty_capabilities():
    """Empty capability dict defaults all features to unsupported."""
    drafts = generate_pics_draft({})
    for group in ("HCI", "L2CAP", "GAP", "GATT", "SMP", "SDP", "RFCOMM"):
        for info in drafts[group].values():
            assert info["supported"] is False


def test_pics_with_le_capability():
    """When LE is supported, LE-dependent features show as supported."""
    caps = {
        "capability_summary": {
            "le_supported": True,
            "bredr_supported": False,
            "le_central": True,
            "le_peripheral": True,
            "le_sc": True,
        }
    }
    drafts = generate_pics_draft(caps)
    gap = drafts["GAP"]
    assert gap["TSPC_GAP_LE_CENTRAL"]["supported"] is True
    assert gap["TSPC_GAP_LE_PERIPHERAL"]["supported"] is True
    gatt = drafts["GATT"]
    assert gatt["TSPC_GATT_CLIENT"]["supported"] is True
    assert gatt["TSPC_GATT_SERVER"]["supported"] is True
