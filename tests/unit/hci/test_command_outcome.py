"""Verify the per-command HCI trace added to HCIController.send_command.

Without a command trace, "the controller refused it" and "we never sent it"
are indistinguishable from above: a rejected command only shows up as a status
byte in a reply nobody logs, and the caller may legitimately ignore it. That is
how an entire extended-family Command Disallowed went unnoticed.
"""
from __future__ import annotations

import asyncio
import logging
import struct

import pytest

from pybluehost.hci.constants import HCI_EVENT_PACKET, HCI_RESET, EventCode
from pybluehost.hci.controller import HCIController, _describe_command_outcome
from pybluehost.hci.packets import (
    HCI_Command_Complete_Event,
    HCI_Command_Status_Event,
    HCI_Reset,
)


# ---------------------------------------------------------------------------
# _describe_command_outcome
# ---------------------------------------------------------------------------

def test_command_complete_reports_its_status_byte():
    event = HCI_Command_Complete_Event(
        num_hci_command_packets=1, command_opcode=HCI_RESET, return_parameters=bytes([0x0C])
    )
    assert _describe_command_outcome(event) == "CommandComplete status=0x0C"


def test_command_complete_without_return_parameters_is_reported_as_such():
    event = HCI_Command_Complete_Event(
        num_hci_command_packets=1, command_opcode=HCI_RESET, return_parameters=b""
    )
    assert _describe_command_outcome(event) == "CommandComplete (no return parameters)"


def test_command_status_reports_its_own_status_field():
    event = HCI_Command_Status_Event(status=0x00, num_hci_command_packets=1, command_opcode=HCI_RESET)
    assert _describe_command_outcome(event) == "CommandStatus status=0x00"


def test_an_unexpected_reply_is_named_not_silently_dropped():
    """An unexpected event must still appear in the trace by class name."""

    class Surprise:
        pass

    assert _describe_command_outcome(Surprise()) == "Surprise"


# ---------------------------------------------------------------------------
# send_command logging
# ---------------------------------------------------------------------------

class _ReplyingTransport:
    """Records sent frames and replies to each command with a fixed event."""

    def __init__(self, reply: bytes) -> None:
        self._sink = None
        self._reply = reply
        self.sent: list[bytes] = []

    def set_sink(self, sink) -> None:
        self._sink = sink

    async def send(self, data: bytes) -> None:
        self.sent.append(data)
        await self._sink.on_transport_data(self._reply)

    @property
    def is_open(self) -> bool:
        return True


def _command_complete(opcode: int, status: int) -> bytes:
    params = struct.pack("<BH", 1, opcode) + bytes([status])
    header = struct.pack("<BBB", HCI_EVENT_PACKET, EventCode.COMMAND_COMPLETE, len(params))
    return header + params


async def test_send_command_logs_the_opcode_and_parameters(caplog):
    caplog.set_level(logging.DEBUG, logger="pybluehost.hci")
    transport = _ReplyingTransport(_command_complete(HCI_RESET, 0x00))
    ctrl = HCIController(transport, command_timeout=2.0)

    await ctrl.send_command(HCI_Reset())

    msgs = [r.getMessage() for r in caplog.records]
    assert any(m.startswith(f"HCI cmd 0x{HCI_RESET:04X} params=") for m in msgs), msgs


async def test_send_command_logs_a_rejected_status(caplog):
    """The whole point of the trace: a rejection must be visible."""
    caplog.set_level(logging.DEBUG, logger="pybluehost.hci")
    transport = _ReplyingTransport(_command_complete(HCI_RESET, 0x0C))
    ctrl = HCIController(transport, command_timeout=2.0)

    await ctrl.send_command(HCI_Reset())

    msgs = [r.getMessage() for r in caplog.records]
    assert any(m == f"HCI cmd 0x{HCI_RESET:04X} -> CommandComplete status=0x0C" for m in msgs), msgs


async def test_send_command_logs_a_timeout(caplog):
    """A command that is never answered is otherwise equally invisible."""
    caplog.set_level(logging.DEBUG, logger="pybluehost.hci")

    class _SilentTransport:
        def set_sink(self, sink) -> None:
            pass

        async def send(self, data: bytes) -> None:
            pass

        @property
        def is_open(self) -> bool:
            return True

    ctrl = HCIController(_SilentTransport(), command_timeout=0.05)

    from pybluehost.core.errors import CommandTimeoutError

    with pytest.raises(CommandTimeoutError):
        await ctrl.send_command(HCI_Reset())

    msgs = [r.getMessage() for r in caplog.records]
    assert any(m == f"HCI cmd 0x{HCI_RESET:04X} -> TIMEOUT" for m in msgs), msgs
