"""Tests for sc_only_mode activation and pts.secure_pair_only wiring."""
import pytest

from pybluehost.ble.security import SecurityConfig
from pybluehost.core.errors import ConfigurationError
from pybluehost.pts.config import PTSModeConfig
from pybluehost.stack import Stack, StackConfig


async def test_secure_pair_only_propagates_to_security_sc_only_mode():
    """When pts.secure_pair_only=True, Stack._build sets sc_only_mode=True."""
    pts = PTSModeConfig(secure_pair_only=True)
    cfg = StackConfig(pts=pts)
    stack = await Stack.virtual(config=cfg)
    try:
        assert stack.config.security.sc_only_mode is True
        assert stack.config.security.enable_secure_connections is True
    finally:
        await stack.close()


async def test_secure_pair_only_off_leaves_security_sc_only_unchanged():
    """When pts=None (default), security.sc_only_mode stays False."""
    cfg = StackConfig()
    stack = await Stack.virtual(config=cfg)
    try:
        assert stack.config.security.sc_only_mode is False
    finally:
        await stack.close()


async def test_smp_options_length_validation():
    """SMP options must be exactly 6 bytes; otherwise raise ValueError at build."""
    with pytest.raises(ValueError, match="6 bytes"):
        await Stack.virtual(config=StackConfig(
            pts=PTSModeConfig(smp_options=b"\x01\x02")  # Too short
        ))


async def test_smp_failure_at_unknown_stage_raises():
    """Unknown smp_failure_at stage must raise at build time."""
    with pytest.raises(ValueError, match="unknown smp_failure_at"):
        await Stack.virtual(config=StackConfig(
            pts=PTSModeConfig(smp_failure_at="nonexistent_stage")
        ))


def test_pts_none_means_no_sc_only_by_default():
    """Verify sc_only_mode field defaults to False without PTS config."""
    cfg = StackConfig()
    assert cfg.security.sc_only_mode is False
