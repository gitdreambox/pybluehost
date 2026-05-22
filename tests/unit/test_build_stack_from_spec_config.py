"""Unit tests for build_stack_from_spec(config=) kwarg."""
from __future__ import annotations

import pytest

from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import JsonBondStorage
from pybluehost.stack import StackConfig

from tests._transport_resolve import build_stack_from_spec


@pytest.mark.asyncio
async def test_build_stack_from_spec_virtual_with_config_threads_config(tmp_path):
    cfg = StackConfig(
        bond_storage=JsonBondStorage(tmp_path / "bonds.json"),
        security=SecurityConfig(enable_secure_connections=True),
    )
    stack = await build_stack_from_spec("virtual", config=cfg)
    try:
        assert stack._config is cfg
    finally:
        await stack.close()


@pytest.mark.asyncio
async def test_build_stack_from_spec_virtual_without_config_uses_default():
    """No config supplied: backward-compatible — Stack still constructs."""
    stack = await build_stack_from_spec("virtual")
    try:
        assert stack._virtual_controller is not None
    finally:
        await stack.close()


@pytest.mark.asyncio
async def test_build_stack_from_spec_unknown_transport_raises():
    """Sanity: unknown spec still rejected even with config supplied."""
    cfg = StackConfig()
    with pytest.raises(Exception):
        await build_stack_from_spec("bogus:foo", config=cfg)
