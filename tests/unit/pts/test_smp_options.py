"""Tests for smp_options byte override."""
import pytest

from pybluehost.pts.config import PTSModeConfig
from pybluehost.stack import Stack, StackConfig


async def test_smp_options_validation_length():
    """SMP options must be exactly 6 bytes."""
    with pytest.raises(ValueError, match="6 bytes"):
        await Stack.virtual(config=StackConfig(
            pts=PTSModeConfig(smp_options=b"\x01\x02\x03")  # Too short
        ))


async def test_smp_options_none_means_no_override():
    """When smp_options=None, normal SMP config applies."""
    cfg = StackConfig(pts=PTSModeConfig(smp_options=None))
    stack = await Stack.virtual(config=cfg)
    try:
        # Stack builds successfully with no SMP override
        assert stack.config.pts.smp_options is None
    finally:
        await stack.close()


async def test_smp_options_exact_six_bytes_accepted():
    """Valid 6-byte smp_options are accepted at build."""
    valid_bytes = bytes.fromhex("04000D100303")  # Valid pairing request body
    cfg = StackConfig(pts=PTSModeConfig(smp_options=valid_bytes))
    stack = await Stack.virtual(config=cfg)
    try:
        assert stack.config.pts.smp_options == valid_bytes
    finally:
        await stack.close()
