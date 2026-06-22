import pytest

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.base import (
    BtpService,
    BtpServiceRegistry,
    BtpServiceError,
)


class _FakeService(BtpService):
    SERVICE_ID = op.SERVICE_GAP        # arbitrary non-Core ID for the test

    async def _handle_op_05(self, controller_index: int, data: bytes):
        if data == b"OK":
            return (op.BTP_STATUS_SUCCESS, b"echo:" + data)
        return (op.BTP_STATUS_FAILED, b"")


async def test_service_dispatches_to_matching_handler():
    svc = _FakeService()
    status, response = await svc.dispatch(opcode=0x05, controller_index=0, data=b"OK")
    assert status == op.BTP_STATUS_SUCCESS
    assert response == b"echo:OK"


async def test_service_unknown_opcode_returns_unknown_cmd_status():
    svc = _FakeService()
    status, response = await svc.dispatch(opcode=0x99, controller_index=0, data=b"")
    assert status == op.BTP_STATUS_UNKNOWN_CMD
    assert response == b""


async def test_service_handler_failure_propagates_status():
    svc = _FakeService()
    status, _ = await svc.dispatch(opcode=0x05, controller_index=0, data=b"FAIL")
    assert status == op.BTP_STATUS_FAILED


def test_registry_register_and_lookup():
    reg = BtpServiceRegistry()
    svc = _FakeService()
    reg.register(svc)
    assert reg.get(op.SERVICE_GAP) is svc


def test_registry_register_duplicate_raises():
    reg = BtpServiceRegistry()
    reg.register(_FakeService())
    with pytest.raises(BtpServiceError, match="already registered"):
        reg.register(_FakeService())


def test_registry_get_unknown_service_returns_none():
    reg = BtpServiceRegistry()
    assert reg.get(0xAB) is None


def test_registry_supported_services_returns_id_list():
    reg = BtpServiceRegistry()
    reg.register(_FakeService())
    assert reg.supported_services() == [op.SERVICE_GAP]
