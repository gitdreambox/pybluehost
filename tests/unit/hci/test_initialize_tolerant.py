"""HCIController.initialize() gates each command on the Supported_Commands bitmap."""
from __future__ import annotations

import pytest

from pybluehost.hci.capabilities import SupportedCommands
from pybluehost.hci.constants import (
    HCI_LE_SET_RANDOM_ADDRESS,
    HCI_READ_BD_ADDR,
)
from pybluehost.hci.controller import HCIController
from pybluehost.hci.virtual import VirtualController


class _RestrictedVC(VirtualController):
    """A VirtualController whose Supported_Commands bitmap omits a few commands."""

    def __init__(self, *args, omitted_opcodes: list[int] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._omitted_opcodes = set(omitted_opcodes or [])

    def _handle_read_local_supported_commands(self, cmd) -> bytes:
        from pybluehost.hci.capabilities import _OPCODE_BIT_POSITIONS
        bitmap = bytearray(64)
        for opcode, (octet, bit) in _OPCODE_BIT_POSITIONS.items():
            if opcode in self._omitted_opcodes:
                continue
            bitmap[octet] |= 1 << bit
        return b"\x00" + bytes(bitmap)


async def _vc_pair(vc):
    """Wire a custom VirtualController instance to a host transport pipe.

    Mirrors VirtualController.create() exactly — copy what create() does to the
    extent necessary to get a host transport that routes through this vc.
    """
    from pybluehost.hci.virtual import _HCIPipe
    host_t, ctrl_t = _HCIPipe.pair()

    class _VCSink:
        async def on_transport_data(_self, data):
            response = await vc.process(data)
            if response is not None and host_t._sink is not None:
                await host_t._sink.on_transport_data(response)

        async def on_transport_error(_self, error):
            pass

    ctrl_t.set_sink(_VCSink())
    await host_t.open()
    await ctrl_t.open()
    # Mirror create()'s _host_sink wiring so async events work too
    vc._host_sink = host_t._sink
    _orig_set_sink = host_t.set_sink

    def _patched_set_sink(sink):
        _orig_set_sink(sink)
        vc._host_sink = sink

    host_t.set_sink = _patched_set_sink
    return host_t


async def test_initialize_skips_unsupported_optional_commands():
    """A controller that doesn't support LE_Set_Random_Address still initializes."""
    from pybluehost.core.address import BDAddress
    vc = _RestrictedVC(
        address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
        omitted_opcodes=[HCI_LE_SET_RANDOM_ADDRESS],
    )
    host_t = await _vc_pair(vc)
    hci = HCIController(transport=host_t, trace=None, command_timeout=2.0)
    try:
        await hci.initialize()
        assert hci.supported_commands is not None
        assert isinstance(hci.supported_commands, SupportedCommands)
        assert not hci.supported_commands.has(HCI_LE_SET_RANDOM_ADDRESS)
        # Mandatory Read_BD_ADDR still ran
        assert hci.supported_commands.has(HCI_READ_BD_ADDR)
    finally:
        await host_t.close()


async def test_initialize_hard_fails_on_missing_read_bd_addr():
    """Read_BD_ADDR is mandatory — if the controller doesn't support it, init fails."""
    from pybluehost.core.address import BDAddress
    vc = _RestrictedVC(
        address=BDAddress(b"\x01\x02\x03\x04\x05\x06"),
        omitted_opcodes=[HCI_READ_BD_ADDR],
    )
    host_t = await _vc_pair(vc)
    hci = HCIController(transport=host_t, trace=None, command_timeout=2.0)
    try:
        with pytest.raises(RuntimeError, match="Read_BD_ADDR"):
            await hci.initialize()
    finally:
        await host_t.close()


async def test_supported_commands_property_is_none_before_initialize():
    """Before initialize(), the parsed bitmap is None."""
    from pybluehost.core.address import BDAddress
    vc = VirtualController(address=BDAddress(b"\x01\x02\x03\x04\x05\x06"))
    host_t = await _vc_pair(vc)
    hci = HCIController(transport=host_t, trace=None, command_timeout=2.0)
    try:
        assert hci.supported_commands is None
    finally:
        await host_t.close()
