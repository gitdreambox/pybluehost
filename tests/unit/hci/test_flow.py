"""Tests for HCI flow control: CommandFlowController, ACLFlowController."""

import asyncio

import pytest

from pybluehost.hci.flow import CommandFlowController, ACLFlowController
from pybluehost.hci.packets import HCI_Command_Complete_Event


@pytest.mark.asyncio
async def test_command_flow_single_credit():
    ctrl = CommandFlowController(initial_credits=1)
    await asyncio.wait_for(ctrl.acquire(), timeout=0.1)


@pytest.mark.asyncio
async def test_command_flow_blocks_at_zero_credits():
    ctrl = CommandFlowController(initial_credits=1)
    await ctrl.acquire()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(ctrl.acquire(), timeout=0.05)


@pytest.mark.asyncio
async def test_command_flow_release_unblocks():
    ctrl = CommandFlowController(initial_credits=1)
    await ctrl.acquire()
    ctrl.release(1)
    await asyncio.wait_for(ctrl.acquire(), timeout=0.1)


@pytest.mark.asyncio
async def test_command_flow_multiple_credits():
    ctrl = CommandFlowController(initial_credits=3)
    await ctrl.acquire()
    await ctrl.acquire()
    await ctrl.acquire()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(ctrl.acquire(), timeout=0.05)


@pytest.mark.asyncio
async def test_command_flow_future_resolve():
    ctrl = CommandFlowController(initial_credits=1)
    await ctrl.acquire()
    fut = ctrl.register(opcode=0x0C03)
    event = HCI_Command_Complete_Event(
        num_hci_command_packets=1,
        command_opcode=0x0C03,
        return_parameters=b"\x00",
    )
    ctrl.resolve(0x0C03, event)
    result = await asyncio.wait_for(fut, timeout=0.1)
    assert result is event


@pytest.mark.asyncio
async def test_command_flow_resolve_unknown_opcode():
    """Resolving unknown opcode should not raise."""
    ctrl = CommandFlowController(initial_credits=1)
    ctrl.resolve(0xFFFF, HCI_Command_Complete_Event(
        num_hci_command_packets=1, command_opcode=0xFFFF, return_parameters=b"\x00"
    ))


def test_acl_flow_configure():
    ctrl = ACLFlowController()
    ctrl.configure(num_buffers=10, buffer_size=251)
    assert ctrl.available == 10
    assert ctrl.buffer_size == 251


@pytest.mark.asyncio
async def test_acl_flow_acquire_and_return():
    ctrl = ACLFlowController()
    ctrl.configure(num_buffers=2, buffer_size=251)
    await ctrl.acquire(handle=0x0001)
    await ctrl.acquire(handle=0x0001)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(ctrl.acquire(handle=0x0001), timeout=0.05)
    ctrl.on_num_completed({0x0001: 1})
    await asyncio.wait_for(ctrl.acquire(handle=0x0001), timeout=0.1)


@pytest.mark.asyncio
async def test_acl_flow_not_configured_raises():
    ctrl = ACLFlowController()
    with pytest.raises(RuntimeError, match="not configured"):
        await ctrl.acquire(handle=0x0001)


def test_acl_segment():
    ctrl = ACLFlowController()
    ctrl.configure(num_buffers=10, buffer_size=4)
    data = bytes(range(10))
    segments = ctrl.segment(data)
    assert len(segments) == 3  # 4 + 4 + 2
    assert b"".join(segments) == data


def test_acl_segment_exact():
    ctrl = ACLFlowController()
    ctrl.configure(num_buffers=10, buffer_size=5)
    data = bytes(range(10))
    segments = ctrl.segment(data)
    assert len(segments) == 2
    assert b"".join(segments) == data


def test_acl_flow_available_unconfigured():
    ctrl = ACLFlowController()
    assert ctrl.available == 0
    assert ctrl.buffer_size == 0
