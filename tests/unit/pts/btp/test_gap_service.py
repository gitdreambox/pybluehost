"""GapService skeleton — registration + bound IutActions/tester accessors."""
from unittest.mock import MagicMock

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.services.base import BtpServiceRegistry
from pybluehost.pts.btp.services.gap import GapService


def test_gap_service_id_matches_constant():
    assert GapService.SERVICE_ID == op.SERVICE_GAP


def test_gap_service_registers_in_registry():
    reg = BtpServiceRegistry()
    actions = MagicMock()
    tester = MagicMock()
    svc = GapService(actions=actions, tester=tester)
    reg.register(svc)
    assert reg.get(op.SERVICE_GAP) is svc


def test_gap_service_stores_actions_and_tester():
    actions = MagicMock()
    tester = MagicMock()
    svc = GapService(actions=actions, tester=tester)
    assert svc._actions is actions
    assert svc._tester is tester
