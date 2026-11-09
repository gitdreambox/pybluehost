import argparse
import asyncio
from pathlib import Path

import pytest

from pybluehost.classic.sdp import DataElement
from pybluehost.cli.app.sdp_browser import (
    _format_sdp_value,
    _log_remote_device_snapshot,
    _sdp_browser_main,
    register_sdp_browser_command,
)
from pybluehost.cli._lifecycle import _format_cli_error


def test_sdp_browser_parser_has_target_example_and_trace_options():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd")
    register_sdp_browser_command(subparsers)

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["sdp-browser", "--help"])
    assert exc.value.code == 0
    args = parser.parse_args(
        [
            "sdp-browser",
            "-t",
            "usb:vendor=csr",
            "-a",
            "A0:90:B5:10:40:82",
            "--hci-log",
            "--btsnoop",
            "sdp.cfa",
        ]
    )

    sdp_parser = next(
        action.choices["sdp-browser"]
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    target_action = next(action for action in sdp_parser._actions if "--target" in action.option_strings)
    assert "A0:90:B5:10:40:82" in target_action.help
    assert "A090B5104082" in target_action.help
    uuid_action = next(action for action in sdp_parser._actions if "--uuid" in action.option_strings)
    assert "omit to scan" in uuid_action.help
    assert args.uuid is None
    timeout_action = next(action for action in sdp_parser._actions if "--sdp-timeout" in action.option_strings)
    assert "10" in timeout_action.help
    assert args.sdp_timeout == 10.0
    max_attr_action = next(action for action in sdp_parser._actions if "--max-attribute-bytes" in action.option_strings)
    assert "0x03F0" in max_attr_action.help
    assert args.max_attribute_bytes == 0x03F0
    override_args = parser.parse_args(
        [
            "sdp-browser",
            "-t",
            "usb:vendor=csr",
            "-a",
            "A090B5104082",
            "--max-attribute-bytes",
            "0xffff",
        ]
    )
    assert override_args.max_attribute_bytes == 0xFFFF
    assert args.hci_log is True
    assert args.btsnoop == Path("sdp.cfa")


async def test_sdp_browser_requires_target_for_all_transports(capsys):
    args = argparse.Namespace(transport="virtual", target=None)
    rc = await _sdp_browser_main(args)
    err = capsys.readouterr().err
    assert rc == 2
    assert "--target is required" in err


async def test_sdp_browser_uses_run_app_command(monkeypatch, capsys):
    class FakeL2CAP:
        async def connect_classic_channel(self, handle, psm):
            assert handle == 0x0042
            assert psm == 0x0001
            return object()

    class FakeStack:
        def __init__(self):
            self.l2cap = FakeL2CAP()
            self.authenticated = False
            self.encrypted = False

        async def connect_classic(self, addr):
            assert str(addr) == "A0:90:B5:10:40:82"
            return 0x0042

        async def read_remote_information(self, handle, *, peer_address=None, timeout=2.0):
            from pybluehost.hci.remote_info import RemoteDeviceInformation
            return RemoteDeviceInformation(handle=handle)

        async def authenticate_classic(self, handle):
            assert handle == 0x0042
            self.authenticated = True

        async def enable_classic_encryption(self, handle):
            assert handle == 0x0042
            assert self.authenticated is True
            self.encrypted = True

    async def run_app(transport_arg, main_coro, **kwargs):
        assert transport_arg == "usb:vendor=csr"
        assert kwargs == {"hci_log": True, "btsnoop": Path("sdp.cfa"), "trace_spec": None, "virtual_sniffer": None}
        stack = FakeStack()
        await main_coro(stack, asyncio.Event())
        assert stack.encrypted is True
        return 0

    monkeypatch.setattr("pybluehost.cli.app.sdp_browser.run_app_command", run_app)

    class FakeSDPClient:
        def __init__(self, channel, **kwargs):
            assert channel is not None
            assert kwargs == {
                "request_timeout": 10.0,
                "retries": 0,
                "max_attribute_byte_count": 0x03F0,
            }

        async def search_attributes(self, target, uuid, attr_ids=None):
            assert target is None
            assert attr_ids is None
            if uuid == 0x1002:
                return []
            if uuid != 0x1101:
                return []
            return [{0x0000: 0x00010001, 0x0100: "SPP Echo"}]

    monkeypatch.setattr("pybluehost.cli.app.sdp_browser.SDPClient", FakeSDPClient)

    args = argparse.Namespace(
        transport="usb:vendor=csr",
        target="A0:90:B5:10:40:82",
        uuid=None,
        sdp_timeout=10.0,
        max_attribute_bytes=0x03F0,
        hci_log=True,
        btsnoop=Path("sdp.cfa"),
    )
    rc = await _sdp_browser_main(args)

    captured = capsys.readouterr()
    assert rc == 0
    assert "Connecting to A0:90:B5:10:40:82" in captured.out
    assert "Connected ACL handle=0x0042" in captured.out
    assert "0x0000 (ServiceRecordHandle): 65537" in captured.out
    assert "0x0100 (ServiceName): SPP Echo" in captured.out


async def test_sdp_browser_default_scan_deduplicates_records(monkeypatch, capsys):
    class FakeL2CAP:
        async def connect_classic_channel(self, handle, psm):
            return object()

    class FakeStack:
        l2cap = FakeL2CAP()

        async def connect_classic(self, addr):
            return 0x0042

        async def read_remote_information(self, handle, *, peer_address=None, timeout=2.0):
            from pybluehost.hci.remote_info import RemoteDeviceInformation
            return RemoteDeviceInformation(handle=handle)

        async def authenticate_classic(self, handle):
            pass

        async def enable_classic_encryption(self, handle):
            pass

    async def run_app(_transport_arg, main_coro, **_kwargs):
        await main_coro(FakeStack(), asyncio.Event())
        return 0

    monkeypatch.setattr("pybluehost.cli.app.sdp_browser.run_app_command", run_app)

    class FakeSDPClient:
        def __init__(self, channel, **kwargs):
            pass

        async def search_attributes(self, target, uuid, attr_ids=None):
            if uuid in (0x1101, 0x1105):
                return [{0x0000: 0x00010001, 0x0100: "Same Record"}]
            return []

    monkeypatch.setattr("pybluehost.cli.app.sdp_browser.SDPClient", FakeSDPClient)

    args = argparse.Namespace(
        transport="usb:vendor=csr",
        target="A0:90:B5:10:40:82",
        uuid=None,
        sdp_timeout=10.0,
        max_attribute_bytes=0x03F0,
        hci_log=False,
        btsnoop=None,
    )

    assert await _sdp_browser_main(args) == 0
    out = capsys.readouterr().out
    assert out.count("Record ") == 1
    assert "Same Record" in out
    assert "0x0100 (ServiceName): Same Record" in out


async def test_sdp_browser_accepts_custom_uuid(monkeypatch):
    seen = {}

    class FakeL2CAP:
        async def connect_classic_channel(self, handle, psm):
            return object()

    class FakeStack:
        l2cap = FakeL2CAP()

        async def connect_classic(self, addr):
            return 0x0042

        async def read_remote_information(self, handle, *, peer_address=None, timeout=2.0):
            from pybluehost.hci.remote_info import RemoteDeviceInformation
            return RemoteDeviceInformation(handle=handle)

        async def authenticate_classic(self, handle):
            pass

        async def enable_classic_encryption(self, handle):
            pass

    async def run_app(_transport_arg, main_coro, **_kwargs):
        await main_coro(FakeStack(), asyncio.Event())
        return 0

    monkeypatch.setattr("pybluehost.cli.app.sdp_browser.run_app_command", run_app)

    class FakeSDPClient:
        def __init__(self, channel, **kwargs):
            seen["client_kwargs"] = kwargs
            pass

        async def search_attributes(self, target, uuid, attr_ids=None):
            seen["uuid"] = uuid
            return [{0x0100: "SPP Echo"}]

    monkeypatch.setattr("pybluehost.cli.app.sdp_browser.SDPClient", FakeSDPClient)

    args = argparse.Namespace(
        transport="usb:vendor=csr",
        target="A0:90:B5:10:40:82",
        uuid=0x1101,
        sdp_timeout=10.0,
        max_attribute_bytes=0x03F0,
        hci_log=False,
        btsnoop=None,
    )

    assert await _sdp_browser_main(args) == 0
    assert seen["uuid"] == 0x1101
    assert seen["client_kwargs"] == {
        "request_timeout": 10.0,
        "retries": 0,
        "max_attribute_byte_count": 0x03F0,
    }


async def test_sdp_browser_logs_remote_information_before_authentication(monkeypatch, capsys):
    from pybluehost.hci.remote_info import (
        RemoteDeviceInformation,
        RemoteExtendedFeatures,
        RemoteName,
        RemoteSupportedFeatures,
        RemoteVersionInformation,
    )

    snapshot = RemoteDeviceInformation(
        handle=0x0042,
        remote_name=RemoteName(status=0, name="Remote Device"),
        supported_features=RemoteSupportedFeatures(status=0, lmp_features=bytes.fromhex("ff59000800000000")),
        extended_features=[RemoteExtendedFeatures(0, 1, 2, bytes(8))],
        version_information=RemoteVersionInformation(0, 0x0C, 0x000F, 0x1234),
    )

    class FakeL2CAP:
        async def connect_classic_channel(self, handle, psm):
            return object()

    class FakeStack:
        l2cap = FakeL2CAP()

        def __init__(self):
            self.order = []

        async def connect_classic(self, addr):
            return 0x0042

        async def read_remote_information(self, handle, *, peer_address=None, timeout=2.0):
            assert handle == 0x0042
            assert str(peer_address) == "A0:90:B5:10:40:82"
            return snapshot

        async def authenticate_classic(self, handle):
            self.order.append("authenticate")

        async def enable_classic_encryption(self, handle):
            pass

    async def run_app(_transport_arg, main_coro, **_kwargs):
        await main_coro(FakeStack(), asyncio.Event())
        return 0

    monkeypatch.setattr("pybluehost.cli.app.sdp_browser.run_app_command", run_app)

    class FakeSDPClient:
        def __init__(self, channel, **kwargs):
            pass

        async def search_attributes(self, target, uuid, attr_ids=None):
            return []

    monkeypatch.setattr("pybluehost.cli.app.sdp_browser.SDPClient", FakeSDPClient)
    args = argparse.Namespace(
        transport="virtual", target="A0:90:B5:10:40:82", uuid=0x1101,
        sdp_timeout=10.0, max_attribute_bytes=0x03F0, hci_log=False, btsnoop=None,
    )
    assert await _sdp_browser_main(args) == 0
    out = capsys.readouterr().out
    assert "Remote name: Remote Device" in out
    assert "Remote LMP features: ff59000800000000" in out
    assert "Remote extended features page 1/2: 0000000000000000" in out
    assert "Remote Company_ID: 0x000F (Broadcom Corporation)" in out
    assert "Remote LMP version: 0x0C (Bluetooth 5.3) subversion=0x1234" in out
    assert out.index("Remote Company_ID") < out.index("Authenticated ACL")


async def test_sdp_browser_continues_when_remote_information_raises(monkeypatch, capsys):
    class FakeL2CAP:
        async def connect_classic_channel(self, handle, psm):
            return object()

    class FakeStack:
        def __init__(self):
            self.l2cap = FakeL2CAP()
            self.authenticated = False

        async def connect_classic(self, addr):
            return 0x0042

        async def read_remote_information(self, handle, **kwargs):
            raise RuntimeError("remote information unavailable")

        async def authenticate_classic(self, handle):
            self.authenticated = True

        async def enable_classic_encryption(self, handle):
            pass

    async def run_app(_transport_arg, main_coro, **_kwargs):
        stack = FakeStack()
        await main_coro(stack, asyncio.Event())
        assert stack.authenticated is True
        return 0

    monkeypatch.setattr("pybluehost.cli.app.sdp_browser.run_app_command", run_app)

    class FakeSDPClient:
        def __init__(self, channel, **kwargs):
            pass

        async def search_attributes(self, target, uuid, attr_ids=None):
            return []

    monkeypatch.setattr("pybluehost.cli.app.sdp_browser.SDPClient", FakeSDPClient)
    args = argparse.Namespace(
        transport="virtual", target="A0:90:B5:10:40:82", uuid=0x1101,
        sdp_timeout=10.0, max_attribute_bytes=0x03F0, hci_log=False, btsnoop=None,
    )
    assert await _sdp_browser_main(args) == 0
    # Warnings go to stderr per the project's logging contract (INFO -> stdout,
    # WARNING+ -> stderr); see tests/unit/cli/test_logging.py.
    assert "remote information unavailable" in capsys.readouterr().err


async def test_sdp_browser_survives_a_snapshot_formatting_failure(monkeypatch, capsys):
    from pybluehost.hci.remote_info import (
        RemoteDeviceInformation,
        RemoteExtendedFeatures,
        RemoteName,
        RemoteSupportedFeatures,
        RemoteVersionInformation,
    )

    snapshot = RemoteDeviceInformation(
        handle=0x0042,
        remote_name=RemoteName(status=0, name="Remote Device"),
        supported_features=RemoteSupportedFeatures(status=0, lmp_features=bytes.fromhex("ff59000800000000")),
        extended_features=[RemoteExtendedFeatures(0, 1, 2, bytes(8))],
        version_information=RemoteVersionInformation(0, 0x0C, 0x000F, 0x1234),
    )
    order = []

    def raiser(value):
        raise FileNotFoundError("SIG data missing")

    monkeypatch.setattr("pybluehost.cli.app.sdp_browser.format_company_id", raiser)

    class FakeL2CAP:
        async def connect_classic_channel(self, handle, psm):
            return object()

    class FakeStack:
        def __init__(self):
            self.l2cap = FakeL2CAP()

        async def connect_classic(self, addr):
            return 0x0042

        async def read_remote_information(self, handle, *, peer_address=None, timeout=2.0):
            return snapshot

        async def authenticate_classic(self, handle):
            order.append("authenticate")

        async def enable_classic_encryption(self, handle):
            order.append("encrypt")

    async def run_app(_transport_arg, main_coro, **_kwargs):
        await main_coro(FakeStack(), asyncio.Event())
        return 0

    monkeypatch.setattr("pybluehost.cli.app.sdp_browser.run_app_command", run_app)

    class FakeSDPClient:
        def __init__(self, channel, **kwargs):
            pass

        async def search_attributes(self, target, uuid, attr_ids=None):
            order.append("sdp")
            return []

    monkeypatch.setattr("pybluehost.cli.app.sdp_browser.SDPClient", FakeSDPClient)
    args = argparse.Namespace(
        transport="virtual", target="A0:90:B5:10:40:82", uuid=0x1101,
        sdp_timeout=10.0, max_attribute_bytes=0x03F0, hci_log=False, btsnoop=None,
    )
    assert await _sdp_browser_main(args) == 0
    captured = capsys.readouterr()
    assert order == ["authenticate", "encrypt", "sdp"]
    assert "Remote name: Remote Device" in captured.out
    assert "SIG data missing" in captured.err


def test_sdp_browser_decodes_remote_feature_bits(capsys):
    from pybluehost.hci.remote_info import (
        RemoteDeviceInformation,
        RemoteExtendedFeatures,
        RemoteSupportedFeatures,
    )

    _log_remote_device_snapshot(
        RemoteDeviceInformation(
            handle=0x0042,
            supported_features=RemoteSupportedFeatures(
                status=0, lmp_features=bytes.fromhex("ff59000800000000"),
            ),
            extended_features=[
                RemoteExtendedFeatures(
                    status=0, page_number=1, max_page_number=2,
                    extended_lmp_features=b"\x09" + bytes(7),
                ),
            ],
        )
    )
    out = capsys.readouterr().out
    assert "Remote LMP features: ff59000800000000" in out
    assert (
        "Remote LMP features supported: 3-slot packets, 5-slot packets, "
        "Encryption, Slot offset, Timing accuracy, Role switch, Hold mode, "
        "Sniff mode, Previously used (was Park state), SCO link, HV2 packets, "
        "u-law log synchronous data, Enhanced inquiry scan" in out
    )
    assert "Remote extended features page 1/2: 0900000000000000" in out
    assert (
        "Remote extended features page 1/2 supported: Secure Simple Pairing "
        "(Host Support), Secure Connections (Host Support)" in out
    )


def test_sdp_browser_notes_feature_bits_the_table_cannot_name(capsys):
    from pybluehost.hci.remote_info import (
        RemoteDeviceInformation,
        RemoteSupportedFeatures,
    )

    _log_remote_device_snapshot(
        RemoteDeviceInformation(
            handle=0x0042,
            supported_features=RemoteSupportedFeatures(
                status=0, lmp_features=b"\x00\x00\x00\x01" + bytes(4),
            ),
        )
    )
    out = capsys.readouterr().out
    assert "Remote LMP features supported: none (+1 unnamed bit)" in out


def test_sdp_browser_reports_partial_remote_information(capsys):
    from pybluehost.hci.remote_info import RemoteDeviceInformation

    _log_remote_device_snapshot(
        RemoteDeviceInformation(
            handle=0x0042,
            errors={
                "remote_name": "peer_address_required",
                "version_information": "timed out",
            },
        )
    )
    err = capsys.readouterr().err
    assert "Remote HCI name unavailable: peer_address_required" in err
    assert "Remote HCI version unavailable: timed out" in err


def test_cli_error_format_includes_type_for_empty_message():
    assert _format_cli_error(TimeoutError()) == "TimeoutError"


def test_sdp_value_format_strips_trailing_nul_from_text():
    assert _format_sdp_value("COM6\x00") == "COM6"
    assert _format_sdp_value(DataElement.text("COM6\x00")) == "COM6"
