"""Smoke tests for stack / peer_stack fixtures."""
from __future__ import annotations

import pytest

from pybluehost.stack import Stack, StackMode


@pytest.mark.asyncio
async def test_stack_fixture_yields_powered_stack(stack):
    assert isinstance(stack, Stack)
    assert stack.is_powered


def test_peer_stack_in_virtual_mode(request, stack, transport_mode):
    if transport_mode != "virtual":
        pytest.skip("This assertion is virtual-specific")
    peer_stack = request.getfixturevalue("peer_stack")
    assert peer_stack is not stack
    assert peer_stack.is_powered
    assert stack.mode == StackMode.VIRTUAL
    assert peer_stack.mode == StackMode.VIRTUAL
