import sys

import pytest

from pybluehost.cli._sniffer_arg import SnifferSpec
from pybluehost.core.errors import SnifferUnavailableError
from pybluehost.sniffer.sink import build_virtual_sniffer_sink


@pytest.mark.skipif(sys.platform == "win32", reason="exercise non-Windows guard")
async def test_factory_raises_on_non_windows_for_ellisys():
    spec = SnifferSpec(backend="ellisys", options={})
    with pytest.raises(SnifferUnavailableError, match="Windows"):
        await build_virtual_sniffer_sink(spec)


@pytest.mark.skipif(sys.platform == "win32", reason="exercise non-Windows guard")
async def test_factory_raises_on_non_windows_for_wps():
    spec = SnifferSpec(backend="wps", options={})
    with pytest.raises(SnifferUnavailableError, match="Windows"):
        await build_virtual_sniffer_sink(spec)
