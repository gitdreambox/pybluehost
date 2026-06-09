"""Tests for disable_sdp_on_le_pair guard."""
import pytest

from pybluehost.pts.config import PTSModeConfig
from pybluehost.stack import Stack, StackConfig


async def test_disable_sdp_on_le_pair_flag_reachable():
    """disable_sdp_on_le_pair flag can be set and read."""
    pts = PTSModeConfig(disable_sdp_on_le_pair=True)
    cfg = StackConfig(pts=pts)
    stack = await Stack.virtual(config=cfg)
    try:
        assert stack.config.pts is not None
        assert stack.config.pts.disable_sdp_on_le_pair is True
    finally:
        await stack.close()


async def test_disable_sdp_on_le_pair_off_by_default():
    """disable_sdp_on_le_pair defaults to False."""
    cfg = StackConfig()
    stack = await Stack.virtual(config=cfg)
    try:
        assert stack.config.pts is None or stack.config.pts.disable_sdp_on_le_pair is False
    finally:
        await stack.close()


async def test_disable_sdp_on_le_pair_with_other_flags():
    """disable_sdp_on_le_pair works alongside other flags."""
    pts = PTSModeConfig(
        disable_sdp_on_le_pair=True,
        secure_pair_only=True,
    )
    cfg = StackConfig(pts=pts)
    stack = await Stack.virtual(config=cfg)
    try:
        assert stack.config.pts.disable_sdp_on_le_pair is True
        assert stack.config.pts.secure_pair_only is True
        # sc_only_mode should be wired by secure_pair_only
        assert stack.config.security.sc_only_mode is True
    finally:
        await stack.close()
