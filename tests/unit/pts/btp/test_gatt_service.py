"""GattService skeleton — registration + bound IutActions/tester accessors."""
from unittest.mock import MagicMock

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.base import BtpServiceRegistry
from pybluehost.pts.btp.services.gatt import GattService


def test_gatt_service_id_matches_constant():
    assert GattService.SERVICE_ID == op.SERVICE_GATT


def test_gatt_service_registers_in_registry():
    reg = BtpServiceRegistry()
    actions = MagicMock()
    tester = MagicMock()
    svc = GattService(actions=actions, tester=tester)
    reg.register(svc)
    assert reg.get(op.SERVICE_GATT) is svc


def test_gatt_service_stores_actions_and_tester():
    actions = MagicMock()
    tester = MagicMock()
    svc = GattService(actions=actions, tester=tester)
    assert svc._actions is actions
    assert svc._tester is tester
