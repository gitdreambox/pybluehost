"""Tests for Stack.read_remote_information()."""
from __future__ import annotations

import asyncio
import contextlib
import struct
import time

import pytest

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import EventCode
from pybluehost.hci.packets import HCI_Command_Status_Event, HCIEvent
from pybluehost.stack import Stack, _hci_status_text

PEER = "1A:8D:8D:1B:F5:6B"
FEATURES = bytes.fromhex("ff59000800000000")
ALL_KEYS = (
    "remote_name",
    "supported_features",
    "extended_features",
    "version_information",
)


class FakeHCI:
    """Models ``HCIController`` as the queries use it.

    A real controller replies to every command with a
    ``HCI_Command_Status_Event`` (or ``HCI_Command_Complete_Event``) whose
    *status byte* carries the rejection — it never raises on a non-zero status.
    """

    def __init__(
        self,
        *,
        name: bool = True,
        supported: bool = True,
        extended: bool = True,
        version: bool = True,
        reject_status: int | None = None,
        completion_status: int = 0,
        completion_handle: int | None = None,
        completion_peer: bytes | None = None,
        truncate: int | None = None,
        defer: bool = False,
    ) -> None:
        self.commands: list = []
        self.enabled = {"name": name, "supported": supported, "extended": extended, "version": version}
        self.listeners: list = []
        self.reject_status = reject_status
        self.completion_status = completion_status
        self.completion_handle = completion_handle
        self.completion_peer = completion_peer
        self.truncate = truncate
        self.defer = defer
        self.on_hci_event_listener = self._register

    def _register(self, listener):
        self.listeners.append(listener)
        return lambda: None

    async def send_command(self, command):
        self.commands.append(command)
        opcode = command.opcode
        if self.reject_status is not None:
            return HCI_Command_Status_Event(
                status=self.reject_status,
                num_hci_command_packets=1,
                command_opcode=opcode,
            )
        if self.defer:
            await asyncio.sleep(0)
        if opcode == 0x0419 and self.enabled["name"]:
            self._emit_remote_name(command.parameters[:6])
        elif opcode == 0x041B and self.enabled["supported"]:
            self._emit_event(
                EventCode.READ_REMOTE_SUPPORTED_FEATURES_COMPLETE,
                self._completion(
                    bytes([self.completion_status])
                    + struct.pack("<H", self._handle(command)) + FEATURES
                ),
            )
        elif opcode == 0x041C and self.enabled["extended"]:
            self._emit_event(
                EventCode.READ_REMOTE_EXTENDED_FEATURES_COMPLETE,
                self._completion(
                    bytes([self.completion_status]) + struct.pack("<H", self._handle(command))
                    + b"\x01\x02" + FEATURES
                ),
            )
        elif opcode == 0x041D and self.enabled["version"]:
            self._emit_event(
                EventCode.READ_REMOTE_VERSION_COMPLETE,
                self._completion(
                    bytes([self.completion_status]) + struct.pack("<H", self._handle(command))
                    + struct.pack("<BHH", 0x0C, 2, 3)
                ),
            )
        return HCI_Command_Status_Event(
            status=0, num_hci_command_packets=1, command_opcode=opcode,
        )

    def _handle(self, command) -> int:
        if self.completion_handle is not None:
            return self.completion_handle
        return struct.unpack_from("<H", command.parameters, 0)[0]

    def _completion(self, parameters: bytes) -> bytes:
        return parameters if self.truncate is None else parameters[: self.truncate]

    def _emit_remote_name(self, peer):
        echoed = self.completion_peer if self.completion_peer is not None else peer
        self._emit_event(
            EventCode.REMOTE_NAME_REQUEST_COMPLETE,
            self._completion(
                bytes([self.completion_status]) + echoed + b"Remote Device".ljust(248, b"\x00")
            ),
        )

    def _emit_event(self, code, parameters):
        event = HCIEvent(event_code=int(code), parameters=parameters)
        for listener in list(self.listeners):
            listener(event)


class RemovingHCI(FakeHCI):
    """FakeHCI whose removal callable actually deregisters, like the real one."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.removals: list[int] = []

    def _register(self, listener):
        self.listeners.append(listener)

        def remove() -> None:
            with contextlib.suppress(ValueError):
                self.listeners.remove(listener)
            self.removals.append(len(self.listeners))

        return remove


def make_stack(fake_hci: FakeHCI | None) -> Stack:
    stack = Stack()
    stack._hci = fake_hci
    return stack


async def test_read_remote_information_issues_all_four_commands_in_order():
    hci = FakeHCI()
    stack = make_stack(hci)
    peer = BDAddress.from_string(PEER)
    snapshot = await stack.read_remote_information(0x0042, peer_address=peer, timeout=0.1)
    assert [command.opcode for command in hci.commands] == [0x0419, 0x041B, 0x041C, 0x041D]
    assert snapshot.remote_name.name == "Remote Device"
    assert snapshot.supported_features.lmp_features == FEATURES
    assert snapshot.extended_features[0].page_number == 1
    assert snapshot.extended_features[0].max_page_number == 2
    assert snapshot.extended_features[0].extended_lmp_features == FEATURES
    assert snapshot.version_information.lmp_version == 0x0C
    assert snapshot.version_information.company_id == 2
    assert snapshot.version_information.lmp_subversion == 3
    assert snapshot.errors == {}


async def test_read_remote_information_continues_after_each_failure():
    hci = FakeHCI(name=False, supported=False, extended=False, version=False)
    stack = make_stack(hci)
    peer = BDAddress.from_string(PEER)
    snapshot = await stack.read_remote_information(0x0042, peer_address=peer, timeout=0.01)
    assert [command.opcode for command in hci.commands] == [0x0419, 0x041B, 0x041C, 0x041D]
    assert set(snapshot.errors) == set(ALL_KEYS)


async def test_read_remote_information_skips_name_without_peer_address():
    hci = FakeHCI()
    stack = make_stack(hci)
    snapshot = await stack.read_remote_information(0x0042, timeout=0.1)
    assert [command.opcode for command in hci.commands] == [0x041B, 0x041C, 0x041D]
    assert snapshot.errors["remote_name"] == "peer_address_required"


async def test_read_remote_information_requires_an_hci_transport():
    stack = make_stack(None)
    with pytest.raises(RuntimeError, match="Stack is not initialized"):
        await stack.read_remote_information(0x0042)


async def test_records_non_zero_completion_status():
    hci = FakeHCI(completion_status=0x05)
    stack = make_stack(hci)
    peer = BDAddress.from_string(PEER)
    snapshot = await stack.read_remote_information(0x0042, peer_address=peer, timeout=0.1)
    assert [command.opcode for command in hci.commands] == [0x0419, 0x041B, 0x041C, 0x041D]
    assert snapshot.remote_name is None
    assert snapshot.supported_features is None
    assert snapshot.extended_features == []
    assert snapshot.version_information is None
    expected = _hci_status_text(0x05)
    assert snapshot.errors == {key: expected for key in ALL_KEYS}


async def test_reports_controller_rejection_without_waiting_for_completion():
    hci = FakeHCI(reject_status=0x0C)
    stack = make_stack(hci)
    peer = BDAddress.from_string(PEER)
    started = time.monotonic()
    snapshot = await stack.read_remote_information(0x0042, peer_address=peer, timeout=0.3)
    elapsed = time.monotonic() - started
    expected = _hci_status_text(0x0C)
    assert snapshot.errors == {key: expected for key in ALL_KEYS}
    assert all("timed out" not in message for message in snapshot.errors.values())
    assert [command.opcode for command in hci.commands] == [0x0419, 0x041B, 0x041C, 0x041D]
    assert elapsed < 0.6, f"rejection waited for the completion timeout ({elapsed:.2f}s)"


async def test_ignores_a_completion_for_another_handle():
    hci = FakeHCI(completion_handle=0x0043)
    stack = make_stack(hci)
    snapshot = await stack.read_remote_information(0x0042, timeout=0.05)
    assert snapshot.supported_features is None
    assert "timed out" in snapshot.errors["supported_features"]


async def test_ignores_a_failed_completion_for_another_handle():
    # A non-zero status must not be accepted on its own: the echoed handle still
    # has to match, otherwise one request steals another link's failure.
    hci = FakeHCI(completion_status=0x05, completion_handle=0x0043)
    stack = make_stack(hci)
    snapshot = await stack.read_remote_information(0x0042, timeout=0.05)
    assert snapshot.supported_features is None
    assert "timed out" in snapshot.errors["supported_features"]


async def test_ignores_a_failed_completion_for_another_peer():
    hci = FakeHCI(
        completion_status=0x05,
        completion_peer=bytes.fromhex("001122334455"),
    )
    stack = make_stack(hci)
    peer = BDAddress.from_string(PEER)
    snapshot = await stack.read_remote_information(0x0042, peer_address=peer, timeout=0.05)
    assert snapshot.remote_name is None
    assert "timed out" in snapshot.errors["remote_name"]


async def test_reports_a_failed_completion_whose_handle_is_zeroed():
    # A controller that failed the link-level operation may leave the echoed
    # handle zeroed; the status byte is then the only usable information.
    hci = FakeHCI(completion_status=0x05, completion_handle=0x0000)
    stack = make_stack(hci)
    snapshot = await stack.read_remote_information(0x0042, timeout=0.05)
    assert snapshot.supported_features is None
    assert snapshot.errors["supported_features"] == _hci_status_text(0x05)


async def test_reports_a_failed_completion_whose_address_is_zeroed():
    hci = FakeHCI(completion_status=0x05, completion_peer=bytes(6))
    stack = make_stack(hci)
    peer = BDAddress.from_string(PEER)
    snapshot = await stack.read_remote_information(0x0042, peer_address=peer, timeout=0.05)
    assert snapshot.remote_name is None
    assert snapshot.errors["remote_name"] == _hci_status_text(0x05)


async def test_reports_a_truncated_completion_instead_of_timing_out():
    hci = FakeHCI(truncate=1)
    stack = make_stack(hci)
    snapshot = await stack.read_remote_information(0x0042, timeout=0.05)
    assert snapshot.supported_features is None
    assert "truncated" in snapshot.errors["supported_features"]


async def test_concurrent_reads_do_not_resolve_each_others_waiters():
    # Both calls share one controller, so every listener sees every completion.
    # Deferred emission keeps both calls in flight when the first event lands.
    hci = FakeHCI(defer=True)
    stack_a = make_stack(hci)
    stack_b = make_stack(hci)
    peer = BDAddress.from_string(PEER)
    snapshot_a, snapshot_b = await asyncio.gather(
        stack_a.read_remote_information(0x0042, peer_address=peer, timeout=0.1),
        stack_b.read_remote_information(0x0043, peer_address=peer, timeout=0.1),
    )
    assert snapshot_a.supported_features is not None
    assert snapshot_b.supported_features is not None
    assert snapshot_a.supported_features.lmp_features == FEATURES
    assert snapshot_b.supported_features.lmp_features == FEATURES
    assert snapshot_a.errors == {}
    assert snapshot_b.errors == {}


async def test_defers_completion_until_after_the_command_returns():
    hci = FakeHCI(defer=True)
    stack = make_stack(hci)
    peer = BDAddress.from_string(PEER)
    snapshot = await stack.read_remote_information(0x0042, peer_address=peer, timeout=0.1)
    assert snapshot.remote_name.name == "Remote Device"
    assert snapshot.supported_features.lmp_features == FEATURES
    assert snapshot.extended_features[0].max_page_number == 2
    assert snapshot.version_information.company_id == 2
    assert snapshot.errors == {}


async def test_read_remote_information_does_not_leave_listeners_registered():
    hci = RemovingHCI()
    stack = make_stack(hci)
    peer = BDAddress.from_string(PEER)
    await stack.read_remote_information(0x0042, peer_address=peer, timeout=0.1)
    # One listener per query, all four queries reached, none left behind.
    assert hci.removals == [0, 0, 0, 0]
    assert hci.listeners == []
