"""Unit-test fixtures shared across unit tests."""
import pytest

from tests.fakes.transport import FakeTransport
from tests.fakes.hci import FakeHCIDownstream
from tests.fakes.trace import NullTrace


@pytest.fixture
def fake_transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def fake_hci() -> FakeHCIDownstream:
    return FakeHCIDownstream()


@pytest.fixture
def null_trace() -> NullTrace:
    return NullTrace()
