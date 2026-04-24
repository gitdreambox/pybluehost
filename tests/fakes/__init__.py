"""Shared test fakes for PyBlueHost test suite."""
from tests.fakes.transport import FakeTransport
from tests.fakes.hci import FakeHCIDownstream
from tests.fakes.l2cap import FakeChannelEvents
from tests.fakes.trace import NullTrace

__all__ = ["FakeTransport", "FakeHCIDownstream", "FakeChannelEvents", "NullTrace"]
