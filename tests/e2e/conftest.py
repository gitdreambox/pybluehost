"""Fixtures for full-stack virtual E2E tests."""
from __future__ import annotations

import pytest

from pybluehost.stack import Stack, StackConfig


@pytest.fixture
async def single_virtual_stack():
    """Single virtual stack for lifecycle testing."""
    stack = await Stack.virtual(config=StackConfig())
    yield stack
    await stack.close()
