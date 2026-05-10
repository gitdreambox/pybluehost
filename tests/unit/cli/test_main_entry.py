import pytest
from pybluehost.cli import main


def test_main_no_args_prints_help_returns_0(capsys):
    rc = main([])
    captured = capsys.readouterr()
    assert rc == 0
    assert "usage" in captured.out.lower() or "usage" in captured.err.lower()


def test_main_app_namespace_exists(capsys):
    # Just verify parser accepts 'app --help'
    with pytest.raises(SystemExit) as ei:
        main(["app", "--help"])
    assert ei.value.code == 0


def test_main_tools_namespace_exists():
    with pytest.raises(SystemExit) as ei:
        main(["tools", "--help"])
    assert ei.value.code == 0


def test_main_top_level_fw_no_longer_exists():
    """fw moved to 'tools fw' — top-level should fail."""
    with pytest.raises(SystemExit) as ei:
        main(["fw", "list"])
    assert ei.value.code != 0  # argparse error


def test_main_dispatches_to_command(capsys):
    """main() reaching args.func(args) — the normal dispatch path — returns 0."""
    rc = main(["tools", "decode", "01030c00"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "HCI_Reset" in captured.out


def test_main_app_without_subcommand_returns_2(capsys):
    """Passing 'app' without a sub-command prints app-specific help."""
    rc = main(["app"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "usage: pybluehost app" in captured.out
    assert "ble-scan" in captured.out
    assert "ble-adv" in captured.out
    assert "tools" not in captured.out


def test_main_tools_without_subcommand_returns_2(capsys):
    """Passing 'tools' without a sub-command prints tools-specific help."""
    rc = main(["tools"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "usage: pybluehost tools" in captured.out
    assert "decode" in captured.out
    assert "rpa" in captured.out
    assert "fw" in captured.out
    assert "usb" in captured.out
    assert "ble-scan" not in captured.out


def test_main_list_transports_no_devices(capsys, monkeypatch):
    """--list-transports prints the no-device message and returns 0 when nothing is plugged in."""
    from pybluehost.transport import usb as usb_mod

    monkeypatch.setattr(usb_mod.USBTransport, "list_devices", classmethod(lambda cls: []))
    rc = main(["--list-transports"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "No Bluetooth USB adapters detected." in captured.out


def test_main_list_transports_with_devices(capsys, monkeypatch):
    """--list-transports prints each detected adapter as a usb: spec line."""
    from pybluehost.transport import usb as usb_mod
    from pybluehost.transport.usb import ChipInfo, DeviceCandidate

    chip = ChipInfo(
        vendor="intel", name="AX210", vid=0x8087, pid=0x0032,
        firmware_pattern="ibt-0040-*", transport_class=None,
    )
    candidate = DeviceCandidate(chip_info=chip, bus=1, address=4)

    monkeypatch.setattr(
        usb_mod.USBTransport, "list_devices", classmethod(lambda cls: [candidate])
    )
    rc = main(["--list-transports"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "Detected Bluetooth USB adapters:" in captured.out
    assert "intel" in captured.out
    assert "AX210" in captured.out
    assert "usb:vendor=intel,bus=1,address=4" in captured.out


def test_main_dunder_main_block(monkeypatch):
    """The __main__ guard calls sys.exit(main()) — simulate by exec."""
    import sys
    import pybluehost.cli as cli_mod

    calls = []
    monkeypatch.setattr(sys, "argv", ["pybluehost"])
    monkeypatch.setattr(cli_mod.sys, "exit", lambda code: calls.append(code))

    # Execute only the __main__ block by setting __name__ manually
    exec(  # noqa: S102
        compile(
            "if __name__ == '__main__': sys.exit(main())",
            "<test>",
            "exec",
        ),
        {"__name__": "__main__", "sys": cli_mod.sys, "main": cli_mod.main},
    )
    assert calls == [0]
