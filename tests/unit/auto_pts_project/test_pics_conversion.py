"""auto_pts_project.pybluehost.pics — per-group PICS dicts + YAML→dict helper."""
import tempfile
from pathlib import Path

import pytest


def test_pics_module_exposes_per_group_dicts():
    """autoptsclient queries module-level PICS_<GROUP> attributes."""
    from auto_pts_project.pybluehost import pics
    for group_name in ("PICS_GAP", "PICS_GATT", "PICS_L2CAP", "PICS_SMP", "PICS_HCI"):
        attr = getattr(pics, group_name, None)
        assert isinstance(attr, dict), f"{group_name} missing or not a dict"
        for k, v in attr.items():
            assert isinstance(v, bool), f"{group_name}[{k!r}] is {type(v).__name__}, expected bool"


def test_pics_gap_contains_known_features():
    """The committed intel-BE200 PICS draft contains the TSPC_GAP_ family."""
    from auto_pts_project.pybluehost import pics
    assert any(k.startswith("TSPC_GAP_") for k in pics.PICS_GAP), \
        f"PICS_GAP missing TSPC_GAP_* features (got {sorted(pics.PICS_GAP)[:5]}...)"


def test_yaml_draft_to_autopts_dict_flattens_correctly():
    """Generator helper converts {Group: {feat: {supported: bool}}} → {feat: bool}."""
    from pybluehost.pts.pics_gen import yaml_draft_to_autopts_dict
    yaml_text = """
GAP:
  TSPC_GAP_FEATURE_A:
    supported: true
    evidence: from capability dump
  TSPC_GAP_FEATURE_B:
    supported: false
    evidence: not supported in v1.0
"""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(yaml_text)
        f.flush()
        path = Path(f.name)
    try:
        result = yaml_draft_to_autopts_dict(path)
    finally:
        path.unlink()
    assert result == {"TSPC_GAP_FEATURE_A": True, "TSPC_GAP_FEATURE_B": False}


def test_yaml_draft_to_autopts_dict_rejects_multiple_top_level_keys():
    from pybluehost.pts.pics_gen import yaml_draft_to_autopts_dict
    yaml_text = "GAP:\n  TSPC_X:\n    supported: true\nGATT:\n  TSPC_Y:\n    supported: true\n"
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(yaml_text)
        f.flush()
        path = Path(f.name)
    try:
        with pytest.raises(ValueError, match="single top-level"):
            yaml_draft_to_autopts_dict(path)
    finally:
        path.unlink()


def test_pics_missing_yaml_returns_empty_dict(monkeypatch):
    """If a group's draft YAML doesn't exist, the PICS_<GROUP> dict is empty
    (operator-friendly default for groups they don't care about)."""
    from auto_pts_project.pybluehost import pics as pics_module
    # Sanity: missing-group helper returns {}
    assert pics_module._load("NONEXISTENT_GROUP") == {}
