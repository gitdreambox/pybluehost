import argparse

from pybluehost.cli.app.mitm.cli import register_mitm_command


def test_register_mitm_command_adds_subparser():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd")
    register_mitm_command(subs)
    args = parser.parse_args(
        ["mitm", "--upstream", "virtual", "--downstream", "virtual"]
    )
    assert args.cmd == "mitm"
    assert args.upstream == "virtual"
    assert args.downstream == "virtual"
    assert args.transport_mode == "both"  # 默认值
