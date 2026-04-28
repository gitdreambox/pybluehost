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
