import pytest
from pybluehost.core.errors import SnifferError, SnifferUnavailableError


def test_sniffer_error_is_exception():
    assert issubclass(SnifferError, Exception)


def test_sniffer_unavailable_inherits_from_sniffer_error():
    assert issubclass(SnifferUnavailableError, SnifferError)


def test_sniffer_unavailable_carries_message():
    exc = SnifferUnavailableError("Windows + Ellisys required")
    assert "Windows" in str(exc)
