"""Tests for PTSModeConfig dataclass and StackConfig.pts integration."""
import pytest

from pybluehost.pts.config import PTSModeConfig
from pybluehost.stack import StackConfig


def test_pts_mode_config_defaults_are_all_off():
    cfg = PTSModeConfig()
    assert cfg.disable_conn_updates is False
    assert cfg.secure_pair_only is False
    assert cfg.disable_sdp_on_le_pair is False
    assert cfg.smp_options is None
    assert cfg.smp_failure_at is None


def test_stack_config_default_pts_is_none():
    sc = StackConfig()
    assert sc.pts is None


def test_pts_mode_config_can_be_attached():
    cfg = PTSModeConfig(secure_pair_only=True, smp_failure_at="confirm_value")
    sc = StackConfig(pts=cfg)
    assert sc.pts is cfg
    assert sc.pts.secure_pair_only is True
    assert sc.pts.smp_failure_at == "confirm_value"
