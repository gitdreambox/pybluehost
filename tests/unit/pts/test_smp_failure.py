"""Tests for smp_failure_at injection."""
import pytest

from pybluehost.pts.config import PTSModeConfig
from pybluehost.stack import Stack, StackConfig


async def test_smp_failure_at_valid_stages():
    """Valid smp_failure_at stages are accepted."""
    valid_stages = [
        "pairing_request",
        "pairing_response",
        "confirm_value",
        "random_value",
        "key_distribution",
    ]
    for stage in valid_stages:
        cfg = StackConfig(pts=PTSModeConfig(smp_failure_at=stage))
        stack = await Stack.virtual(config=cfg)
        try:
            assert stack.config.pts.smp_failure_at == stage
        finally:
            await stack.close()


async def test_smp_failure_at_unknown_stage_raises():
    """Unknown smp_failure_at stage raises ValueError at build."""
    with pytest.raises(ValueError, match="unknown smp_failure_at"):
        await Stack.virtual(config=StackConfig(
            pts=PTSModeConfig(smp_failure_at="nonexistent_stage")
        ))


async def test_smp_failure_at_with_reason_code():
    """smp_failure_at can include hex reason code."""
    cfg = StackConfig(pts=PTSModeConfig(smp_failure_at="05:confirm_value"))
    stack = await Stack.virtual(config=cfg)
    try:
        assert stack.config.pts.smp_failure_at == "05:confirm_value"
    finally:
        await stack.close()


async def test_smp_failure_at_invalid_reason_code_accepted():
    """Invalid reason code is parsed but SMP will validate at injection time."""
    # Stack accepts any format "XX:stage"; SMP will parse on use
    cfg = StackConfig(pts=PTSModeConfig(smp_failure_at="ZZ:confirm_value"))
    stack = await Stack.virtual(config=cfg)
    try:
        # Stack accepts it (SMP will fail if called with this)
        assert stack.config.pts.smp_failure_at == "ZZ:confirm_value"
    finally:
        await stack.close()
