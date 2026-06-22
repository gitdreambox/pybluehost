"""Core BTP service tests — upstream-aligned (LOG_MESSAGE + READ_BTP_MTU, no RESET_BOARD)."""
import pytest

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.base import BtpService, BtpServiceRegistry
from pybluehost.pts.btp.services.core import CoreService, BTP_MTU


class _DummyGapService(BtpService):
    SERVICE_ID = op.SERVICE_GAP


async def test_read_supported_commands_returns_bitfield():
    reg = BtpServiceRegistry()
    core = CoreService(registry=reg)
    reg.register(core)
    status, data = await core.dispatch(
        opcode=op.OP_CORE_READ_SUPPORTED_COMMANDS,
        controller_index=op.CONTROLLER_INDEX_NONE, data=b"",
    )
    assert status == op.BTP_STATUS_SUCCESS
    # Core supports opcodes 0x01..0x06 → bits 0..5 → 0b00111111 = 0x3F
    assert data == bytes([0x3F])


async def test_read_supported_services_returns_registry_bitfield():
    reg = BtpServiceRegistry()
    core = CoreService(registry=reg)
    reg.register(core)
    reg.register(_DummyGapService())
    status, data = await core.dispatch(
        opcode=op.OP_CORE_READ_SUPPORTED_SERVICES,
        controller_index=op.CONTROLLER_INDEX_NONE, data=b"",
    )
    assert status == op.BTP_STATUS_SUCCESS
    # Core=0x00 (bit 0) + GAP=0x01 (bit 1) → 0b00000011 = 0x03
    assert data == bytes([0x03])


async def test_register_known_service():
    reg = BtpServiceRegistry()
    reg.register(_DummyGapService())
    core = CoreService(registry=reg)
    reg.register(core)
    status, data = await core.dispatch(
        opcode=op.OP_CORE_REGISTER,
        controller_index=op.CONTROLLER_INDEX_NONE,
        data=bytes([op.SERVICE_GAP]),
    )
    assert status == op.BTP_STATUS_SUCCESS


async def test_register_unknown_service_fails():
    reg = BtpServiceRegistry()
    core = CoreService(registry=reg)
    reg.register(core)
    status, _ = await core.dispatch(
        opcode=op.OP_CORE_REGISTER,
        controller_index=op.CONTROLLER_INDEX_NONE,
        data=bytes([0xAB]),       # not registered
    )
    assert status == op.BTP_STATUS_FAILED


async def test_unregister_known_service():
    reg = BtpServiceRegistry()
    reg.register(_DummyGapService())
    core = CoreService(registry=reg)
    reg.register(core)
    status, _ = await core.dispatch(
        opcode=op.OP_CORE_UNREGISTER,
        controller_index=op.CONTROLLER_INDEX_NONE,
        data=bytes([op.SERVICE_GAP]),
    )
    assert status == op.BTP_STATUS_SUCCESS


async def test_log_message_accepts_arbitrary_text_and_acks_success():
    """LOG_MESSAGE (upstream 0x05) — client sends a log string; tester ACKs."""
    reg = BtpServiceRegistry()
    core = CoreService(registry=reg)
    reg.register(core)
    status, response = await core.dispatch(
        opcode=op.OP_CORE_LOG_MESSAGE,
        controller_index=op.CONTROLLER_INDEX_NONE,
        data=b"hello from autoptsclient",
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert response == b""


async def test_log_message_accepts_empty_payload():
    reg = BtpServiceRegistry()
    core = CoreService(registry=reg)
    reg.register(core)
    status, _ = await core.dispatch(
        opcode=op.OP_CORE_LOG_MESSAGE,
        controller_index=op.CONTROLLER_INDEX_NONE,
        data=b"",
    )
    assert status == op.BTP_STATUS_SUCCESS


async def test_read_btp_mtu_returns_u16_le():
    """READ_BTP_MTU (upstream 0x06) — tester returns its MTU as u16 LE."""
    reg = BtpServiceRegistry()
    core = CoreService(registry=reg)
    reg.register(core)
    status, response = await core.dispatch(
        opcode=op.OP_CORE_READ_BTP_MTU,
        controller_index=op.CONTROLLER_INDEX_NONE, data=b"",
    )
    assert status == op.BTP_STATUS_SUCCESS
    assert len(response) == 2
    mtu = int.from_bytes(response, "little")
    assert mtu == BTP_MTU


def test_btp_mtu_default_is_reasonable():
    """The default MTU should be enough for a full BTP frame (5-byte header + 1024 payload)."""
    assert BTP_MTU >= 5 + 1024
    assert BTP_MTU <= 0xFFFF


async def test_core_event_ready_payload_format():
    """Core READY event payload (Core opcode 0x80)."""
    reg = BtpServiceRegistry()
    core = CoreService(registry=reg)
    payload = core.make_ready_event_payload(version_major=1, version_minor=0)
    assert len(payload) >= 2
    assert payload[0] == 1
    assert payload[1] == 0
