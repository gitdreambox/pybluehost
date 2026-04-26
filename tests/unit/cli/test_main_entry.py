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
