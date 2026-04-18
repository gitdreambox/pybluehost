"""Tests for HCIUserChannelTransport (Linux-only AF_BLUETOOTH hci_user_channel)."""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux only")

from pybluehost.transport.hci_user_channel import HCIUserChannelTransport


def test_import_on_linux():
    transport = HCIUserChannelTransport(hci_index=0)
    assert transport is not None
    assert not transport.is_open


def test_transport_info():
    transport = HCIUserChannelTransport(hci_index=0)
    info = transport.info
    assert info.type == "hci_user_channel"
    assert "hci0" in info.description


def test_transport_info_custom_index():
    transport = HCIUserChannelTransport(hci_index=2)
    info = transport.info
    assert "hci2" in info.description


def test_default_hci_index():
    transport = HCIUserChannelTransport()
    assert transport._hci_index == 0
