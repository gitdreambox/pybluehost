import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from pybluehost.pts.actions import IutActions


class _Scanner:
    def __init__(self):
        self.on_result = MagicMock()
        self.start = AsyncMock()

    def __getattr__(self, name):
        return MagicMock()


@pytest.mark.asyncio
async def test_pts_scan_disables_duplicate_filtering():
    """Duplicate filtering de-duplicates by address, which suppresses the scan
    response that follows a device's advertising report — the two halves can
    then never be merged (GAP/BROB/OBSV/BV-05/06 verify the scan response)."""
    scanner = _Scanner()
    gap = SimpleNamespace(ble_scanner=scanner, ble_privacy=None)
    actions = IutActions.__new__(IutActions)
    actions._stack = SimpleNamespace(gap=gap)

    await actions.scan(active=True)

    cfg = scanner.start.await_args.args[0]
    assert cfg.active is True
    assert cfg.filter_duplicates is False
