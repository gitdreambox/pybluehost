import argparse

from pybluehost.cli._lifecycle import add_trace_arguments


def test_add_trace_arguments_includes_virtual_sniffer():
    p = argparse.ArgumentParser()
    add_trace_arguments(p)
    ns = p.parse_args(["--virtual-sniffer", "ellisys"])
    assert getattr(ns, "virtual_sniffer", None) == "ellisys"


def test_virtual_sniffer_defaults_to_none():
    p = argparse.ArgumentParser()
    add_trace_arguments(p)
    ns = p.parse_args([])
    assert getattr(ns, "virtual_sniffer", "MISSING") is None


def test_bridge_rejects_virtual_sniffer():
    """Bridge mode does not support virtual-sniffer (transport-layer, not hci)."""
    import pytest

    from pybluehost.cli.app.bridge import HCITransportBridge

    class _FakeBackend:
        pass

    with pytest.raises(ValueError, match="not supported in bridge mode"):
        HCITransportBridge(
            _FakeBackend(), protocol="tcp", host="127.0.0.1", port=0,
            virtual_sniffer="ellisys",
        )
