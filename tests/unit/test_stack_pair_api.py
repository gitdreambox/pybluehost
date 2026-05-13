"""Stack.pair() and Stack.encrypt() public APIs + StackConfig fields."""
from __future__ import annotations

import pytest

from pybluehost.ble.smp import JsonBondStorage
from pybluehost.stack import Stack, StackConfig


async def test_stack_config_new_fields_defaults():
    cfg = StackConfig()
    assert cfg.bondable is True
    assert cfg.auto_encrypt_on_bonded_reconnect is True


async def test_stack_config_new_fields_can_be_overridden():
    cfg = StackConfig(bondable=False, auto_encrypt_on_bonded_reconnect=False)
    assert cfg.bondable is False
    assert cfg.auto_encrypt_on_bonded_reconnect is False


async def test_stack_pair_raises_when_no_le_connection(tmp_path):
    storage = JsonBondStorage(tmp_path / "bonds.json")
    cfg = StackConfig(bond_storage=storage)
    stack = await Stack.virtual(config=cfg)
    try:
        # No LE connection has been established; SMP can't bind without one
        with pytest.raises(RuntimeError):
            await stack.pair(handle=0x0040, timeout=0.5)
    finally:
        await stack.close()
