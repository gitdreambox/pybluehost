"""FakeHCIDownstream — captures commands and ACL sends; returns success CCEs."""
from __future__ import annotations

from pybluehost.hci.packets import HCICommand, HCI_Command_Complete_Event
from pybluehost.hci.constants import ErrorCode


class FakeHCIDownstream:
    """Fake HCI downstream SAP — captures commands and ACL sends."""

    def __init__(self, auto_reply: bool = True) -> None:
        self.commands: list[HCICommand] = []
        self.acl_sent: list[tuple[int, int, bytes]] = []
        self._auto_reply = auto_reply

    async def send_command(self, cmd: HCICommand) -> HCI_Command_Complete_Event:
        self.commands.append(cmd)
        if self._auto_reply:
            return HCI_Command_Complete_Event(
                num_hci_command_packets=1,
                command_opcode=cmd.opcode,
                return_parameters=bytes([ErrorCode.SUCCESS]),
            )
        raise TimeoutError("FakeHCI: auto_reply disabled")

    async def send_acl_data(self, handle: int, pb_flag: int, data: bytes) -> None:
        self.acl_sent.append((handle, pb_flag, data))

    def clear(self) -> None:
        self.commands.clear()
        self.acl_sent.clear()

    def last_command_opcode(self) -> int | None:
        return self.commands[-1].opcode if self.commands else None
