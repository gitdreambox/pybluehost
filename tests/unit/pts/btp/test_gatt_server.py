import pytest
from unittest.mock import MagicMock

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.gatt import GattService


class _FakeActions:
    def __init__(self):
        self.calls = []


def _make_svc():
    return GattService(actions=_FakeActions(), tester=MagicMock())


@pytest.mark.asyncio
async def test_add_service_returns_handle():
    svc = _make_svc()
    body = bytes([op.GATT_SERVICE_PRIMARY, 2]) + bytes.fromhex("0F18")
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_ADD_SERVICE, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    handle = int.from_bytes(data, "little")
    assert handle >= 0x0001


@pytest.mark.asyncio
async def test_add_service_two_distinct_handles():
    svc = _make_svc()
    body1 = bytes([op.GATT_SERVICE_PRIMARY, 2]) + bytes.fromhex("0F18")
    body2 = bytes([op.GATT_SERVICE_PRIMARY, 2]) + bytes.fromhex("0A18")
    _, d1 = await svc.dispatch(opcode=op.OP_GATT_ADD_SERVICE, controller_index=0, data=body1)
    _, d2 = await svc.dispatch(opcode=op.OP_GATT_ADD_SERVICE, controller_index=0, data=body2)
    assert int.from_bytes(d1, "little") != int.from_bytes(d2, "little")


@pytest.mark.asyncio
async def test_add_characteristic_requires_existing_service():
    svc = _make_svc()
    body = (0x9999).to_bytes(2, "little") + bytes([0x02, 0x01, 2]) + bytes.fromhex("1929")
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_ADD_CHARACTERISTIC, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_add_characteristic_returns_value_handle():
    svc = _make_svc()
    svc_body = bytes([op.GATT_SERVICE_PRIMARY, 2]) + bytes.fromhex("0F18")
    _, svc_resp = await svc.dispatch(opcode=op.OP_GATT_ADD_SERVICE, controller_index=0, data=svc_body)
    parent_handle = int.from_bytes(svc_resp, "little")
    char_body = (
        parent_handle.to_bytes(2, "little")
        + bytes([op.GATT_CHRC_PROP_READ | op.GATT_CHRC_PROP_NOTIFY])
        + bytes([op.GATT_PERM_READ])
        + bytes([2]) + bytes.fromhex("1929")
    )
    status, data = await svc.dispatch(
        opcode=op.OP_GATT_ADD_CHARACTERISTIC, controller_index=0, data=char_body,
    )
    assert status == op.BTP_STATUS_SUCCESS
    char_handle = int.from_bytes(data, "little")
    assert char_handle > parent_handle


@pytest.mark.asyncio
async def test_add_descriptor_attaches_to_char():
    svc = _make_svc()
    svc_body = bytes([op.GATT_SERVICE_PRIMARY, 2]) + bytes.fromhex("0F18")
    _, svc_resp = await svc.dispatch(opcode=op.OP_GATT_ADD_SERVICE, controller_index=0, data=svc_body)
    svc_h = int.from_bytes(svc_resp, "little")
    char_body = svc_h.to_bytes(2, "little") + bytes([0x10, 0x01, 2]) + bytes.fromhex("1929")
    _, char_resp = await svc.dispatch(opcode=op.OP_GATT_ADD_CHARACTERISTIC, controller_index=0, data=char_body)
    char_h = int.from_bytes(char_resp, "little")
    desc_body = char_h.to_bytes(2, "little") + bytes([0x03, 2]) + bytes.fromhex("0229")
    status, desc_resp = await svc.dispatch(opcode=op.OP_GATT_ADD_DESCRIPTOR, controller_index=0, data=desc_body)
    assert status == op.BTP_STATUS_SUCCESS
    desc_h = int.from_bytes(desc_resp, "little")
    assert desc_h > char_h


@pytest.mark.asyncio
async def test_add_service_rejects_bad_uuid_length():
    svc = _make_svc()
    body = bytes([op.GATT_SERVICE_PRIMARY, 7]) + bytes(7)
    status, _ = await svc.dispatch(
        opcode=op.OP_GATT_ADD_SERVICE, controller_index=0, data=body,
    )
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_set_value_updates_attribute():
    svc = _make_svc()
    svc_body = bytes([0, 2]) + bytes.fromhex("0F18")
    _, svc_resp = await svc.dispatch(opcode=op.OP_GATT_ADD_SERVICE, controller_index=0, data=svc_body)
    svc_h = int.from_bytes(svc_resp, "little")
    char_body = svc_h.to_bytes(2, "little") + bytes([0x02, 0x01, 2]) + bytes.fromhex("1929")
    _, char_resp = await svc.dispatch(opcode=op.OP_GATT_ADD_CHARACTERISTIC, controller_index=0, data=char_body)
    char_h = int.from_bytes(char_resp, "little")

    set_body = char_h.to_bytes(2, "little") + (1).to_bytes(2, "little") + b"\x55"
    status, _ = await svc.dispatch(opcode=op.OP_GATT_SET_VALUE, controller_index=0, data=set_body)
    assert status == op.BTP_STATUS_SUCCESS
    assert svc._all_attrs[char_h].value == b"\x55"


@pytest.mark.asyncio
async def test_set_value_unknown_handle_fails():
    svc = _make_svc()
    body = (0xFFFF).to_bytes(2, "little") + (1).to_bytes(2, "little") + b"\x01"
    status, _ = await svc.dispatch(opcode=op.OP_GATT_SET_VALUE, controller_index=0, data=body)
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_start_server_registers_services_with_stack():
    class _FakeGattServer:
        def __init__(self):
            self.added = []

        def add_service(self, svc_def):
            self.added.append(svc_def)
            return svc_def

    class _FakeStack:
        def __init__(self):
            self.gatt_server = _FakeGattServer()

    class _StackActions:
        def __init__(self):
            self._stack = _FakeStack()
            self.calls = []

    actions = _StackActions()
    svc = GattService(actions=actions, tester=MagicMock())
    # Build a tiny service
    body = bytes([0, 2]) + bytes.fromhex("0F18")
    await svc.dispatch(opcode=op.OP_GATT_ADD_SERVICE, controller_index=0, data=body)
    status, _ = await svc.dispatch(opcode=op.OP_GATT_START_SERVER, controller_index=0, data=b"")
    assert status == op.BTP_STATUS_SUCCESS
    assert len(actions._stack.gatt_server.added) == 1
    added_svc = actions._stack.gatt_server.added[0]
    # ServiceDefinition.uuid is a UUID16 object for 2-byte BTP UUID.
    from pybluehost.core.uuid import UUID16
    assert isinstance(added_svc.uuid, UUID16)
    assert added_svc.uuid.value == 0x180F


@pytest.mark.asyncio
async def test_start_server_no_stack_fails():
    svc = GattService(actions=_FakeActions(), tester=MagicMock())   # no _stack
    body = bytes([0, 2]) + bytes.fromhex("0F18")
    await svc.dispatch(opcode=op.OP_GATT_ADD_SERVICE, controller_index=0, data=body)
    status, _ = await svc.dispatch(opcode=op.OP_GATT_START_SERVER, controller_index=0, data=b"")
    assert status == op.BTP_STATUS_FAILED


@pytest.mark.asyncio
async def test_reset_server_clears_pending_db():
    svc = _make_svc()
    body = bytes([0, 2]) + bytes.fromhex("0F18")
    await svc.dispatch(opcode=op.OP_GATT_ADD_SERVICE, controller_index=0, data=body)
    assert len(svc._services) == 1
    status, _ = await svc.dispatch(opcode=op.OP_GATT_RESET_SERVER, controller_index=0, data=b"")
    assert status == op.BTP_STATUS_SUCCESS
    assert svc._services == []
    assert svc._all_attrs == {}
