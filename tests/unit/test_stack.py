"""Tests for Stack, StackConfig, StackMode."""
from __future__ import annotations

import pytest

from pybluehost.core.types import IOCapability
from pybluehost.stack import Stack, StackConfig, StackMode


# ---------------------------------------------------------------------------
# StackConfig + StackMode
# ---------------------------------------------------------------------------

def test_default_config():
    config = StackConfig()
    assert config.device_name == "PyBlueHost"
    assert config.command_timeout == 5.0
    assert config.le_io_capability == IOCapability.NO_INPUT_NO_OUTPUT
    assert config.classic_io_capability == IOCapability.DISPLAY_YES_NO
    assert config.appearance == 0x0000
    assert config.trace_sinks == []


def test_custom_config():
    config = StackConfig(device_name="MyDevice", command_timeout=10.0)
    assert config.device_name == "MyDevice"
    assert config.command_timeout == 10.0


def test_stack_mode_enum():
    assert StackMode.LIVE == "live"
    assert StackMode.VIRTUAL == "virtual"
    assert StackMode.REPLAY == "replay"


def test_stack_config_security_field():
    from pybluehost.ble.security import SecurityConfig

    config = StackConfig()
    assert isinstance(config.security, SecurityConfig)


# ---------------------------------------------------------------------------
# Stack lifecycle (virtual)
# ---------------------------------------------------------------------------

async def test_stack_virtual_creates_powered_stack():
    stack = await Stack.virtual()
    assert stack.is_powered
    assert stack.mode == StackMode.VIRTUAL
    await stack.close()


async def test_stack_virtual_has_local_address():
    stack = await Stack.virtual()
    assert stack.local_address is not None
    await stack.close()


async def test_stack_power_off_on():
    stack = await Stack.virtual()
    assert stack.is_powered
    await stack.power_off()
    assert not stack.is_powered
    await stack.power_on()
    assert stack.is_powered
    await stack.close()


async def test_stack_context_manager():
    async with await Stack.virtual() as stack:
        assert stack.is_powered
    assert not stack.is_powered


async def test_stack_exposes_layers():
    stack = await Stack.virtual()
    assert stack.hci is not None
    assert stack.l2cap is not None
    assert stack.gap is not None
    assert stack.gatt_server is not None
    assert stack.trace is not None
    assert stack.sdp is not None
    assert stack.rfcomm is not None
    await stack.close()


async def test_stack_gap_has_subsystems():
    stack = await Stack.virtual()
    assert stack.gap.ble_advertiser is not None
    assert stack.gap.ble_scanner is not None
    assert stack.gap.ble_connections is not None
    assert stack.gap.classic_discovery is not None
    assert stack.gap.classic_ssp is not None
    assert stack.gap.whitelist is not None
    await stack.close()
