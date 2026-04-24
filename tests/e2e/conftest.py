"""Fixtures for full-stack Loopback E2E tests."""
from __future__ import annotations

import pytest

from pybluehost.stack import Stack, StackConfig, StackMode


@pytest.fixture
async def single_loopback_stack():
    """Single Loopback stack for lifecycle testing."""
    stack = await Stack.loopback(config=StackConfig())
    yield stack
    await stack.close()
