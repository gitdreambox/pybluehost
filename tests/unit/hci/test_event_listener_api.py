"""Tests for the HCIController generic removable raw event-listener hook.

The hook's distinguishing capability is that it observes *every* raw HCI
event — including the command/flow-control events that are consumed by the
controller's own bookkeeping and never reach the single upstream callback.
Listeners stay registered until the callable returned from
``on_hci_event_listener()`` is invoked.
"""
from __future__ import annotations

import asyncio

from pybluehost.hci.constants import EventCode
from pybluehost.hci.controller import HCIController
from pybluehost.hci.packets import HCIEvent, HCI_Command_Complete_Event
from tests.fakes.transport import FakeTransport


def make_controller() -> HCIController:
    return HCIController(FakeTransport())


async def test_hci_event_listener_receives_raw_event_before_upstream():
    controller = make_controller()
    order: list[str] = []
    seen_by_listener: list[HCIEvent] = []

    def listener(received: HCIEvent) -> None:
        order.append("listener")
        seen_by_listener.append(received)

    async def upstream(received: HCIEvent) -> None:
        order.append("upstream")
        assert received is seen_by_listener[0]

    controller.set_upstream(on_hci_event=upstream)
    remove = controller.on_hci_event_listener(listener)
    await controller.on_transport_data(
        HCIEvent(
            event_code=int(EventCode.READ_REMOTE_VERSION_COMPLETE),
            parameters=b"\x00\x42\x00",
        ).to_bytes()
    )
    await asyncio.sleep(0)

    assert order == ["listener", "upstream"]
    assert seen_by_listener[0].event_code == int(EventCode.READ_REMOTE_VERSION_COMPLETE)
    remove()


async def test_hci_event_listener_sees_events_that_never_reach_upstream():
    controller = make_controller()
    seen_by_listener: list[int] = []
    seen_by_upstream: list[int] = []

    def listener(event: HCIEvent) -> None:
        seen_by_listener.append(event.event_code)

    async def upstream(event: HCIEvent) -> None:
        seen_by_upstream.append(event.event_code)

    controller.set_upstream(on_hci_event=upstream)
    controller.on_hci_event_listener(listener)

    # Command Complete (opcode 0x0C03) — consumed by _handle_event's early return.
    await controller.on_transport_data(
        HCI_Command_Complete_Event(
            num_hci_command_packets=1, command_opcode=0x0C03, return_parameters=b"\x00"
        ).to_bytes()
    )
    # Number Of Completed Packets — likewise consumed by an early return.
    await controller.on_transport_data(
        HCIEvent(
            event_code=int(EventCode.NUM_COMPLETED_PACKETS),
            parameters=b"\x01\x01\x00\x01\x00",
        ).to_bytes()
    )

    assert seen_by_listener == [
        int(EventCode.COMMAND_COMPLETE),
        int(EventCode.NUM_COMPLETED_PACKETS),
    ]
    assert seen_by_upstream == []


async def test_hci_event_listener_can_be_removed():
    controller = make_controller()
    seen: list[HCIEvent] = []
    remove = controller.on_hci_event_listener(seen.append)

    await controller.on_transport_data(
        HCIEvent(event_code=int(EventCode.READ_REMOTE_VERSION_COMPLETE), parameters=b"").to_bytes()
    )
    await asyncio.sleep(0)
    assert len(seen) == 1

    remove()
    remove()  # idempotent: a second removal is a no-op
    await controller.on_transport_data(
        HCIEvent(event_code=int(EventCode.READ_REMOTE_VERSION_COMPLETE), parameters=b"").to_bytes()
    )
    await asyncio.sleep(0)
    assert len(seen) == 1


async def test_hci_event_listener_exception_does_not_break_upstream():
    controller = make_controller()
    seen: list[str] = []

    def broken_listener(received: HCIEvent) -> None:
        raise RuntimeError("listener failed")

    async def upstream(received: HCIEvent) -> None:
        seen.append("upstream")

    controller.set_upstream(on_hci_event=upstream)
    controller.on_hci_event_listener(broken_listener)
    await controller.on_transport_data(
        HCIEvent(event_code=int(EventCode.READ_REMOTE_VERSION_COMPLETE), parameters=b"").to_bytes()
    )
    await asyncio.sleep(0)
    assert seen == ["upstream"]


async def test_hci_event_listener_first_raising_does_not_skip_second():
    controller = make_controller()
    seen: list[str] = []

    def first(event: HCIEvent) -> None:
        raise RuntimeError("boom")

    def second(event: HCIEvent) -> None:
        seen.append("second")

    controller.on_hci_event_listener(first)
    controller.on_hci_event_listener(second)
    await controller.on_transport_data(
        HCIEvent(event_code=int(EventCode.READ_REMOTE_VERSION_COMPLETE), parameters=b"").to_bytes()
    )
    await asyncio.sleep(0)
    assert seen == ["second"]


async def test_hci_event_listener_async_body_runs():
    controller = make_controller()
    ran: list[bool] = []

    async def listener(event: HCIEvent) -> None:
        ran.append(True)

    controller.on_hci_event_listener(listener)
    await controller.on_transport_data(
        HCIEvent(event_code=int(EventCode.READ_REMOTE_VERSION_COMPLETE), parameters=b"").to_bytes()
    )
    await asyncio.sleep(0)
    assert ran == [True]


async def test_hci_event_listener_self_removal_does_not_skip_sibling():
    controller = make_controller()
    seen: list[str] = []
    remove_first = None

    def first(event: HCIEvent) -> None:
        remove_first()

    def second(event: HCIEvent) -> None:
        seen.append("second")

    remove_first = controller.on_hci_event_listener(first)
    controller.on_hci_event_listener(second)
    await controller.on_transport_data(
        HCIEvent(event_code=int(EventCode.READ_REMOTE_VERSION_COMPLETE), parameters=b"").to_bytes()
    )
    await asyncio.sleep(0)
    assert seen == ["second"]
