"""LeCoCService skeleton — registration + bound IutActions/tester accessors."""
from unittest.mock import MagicMock

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.base import BtpServiceRegistry
from pybluehost.pts.btp.services.l2cap import LeCoCService


def test_le_coc_service_id_matches_constant():
    assert LeCoCService.SERVICE_ID == op.SERVICE_L2CAP


def test_le_coc_service_registers_in_registry():
    reg = BtpServiceRegistry()
    svc = LeCoCService(actions=MagicMock(), tester=MagicMock())
    reg.register(svc)
    assert reg.get(op.SERVICE_L2CAP) is svc


def test_le_coc_service_stores_actions_and_tester():
    actions = MagicMock()
    tester = MagicMock()
    svc = LeCoCService(actions=actions, tester=tester)
    assert svc._actions is actions
    assert svc._tester is tester
    # Channel registry starts empty.
    assert svc._channels == {}
