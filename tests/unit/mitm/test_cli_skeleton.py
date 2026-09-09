import argparse

from pybluehost.cli.app.mitm.cli import register_mitm_command
from pybluehost.cli.app.mitm.controllers import open_controller_pair


def test_register_mitm_command_adds_scan_and_relay():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(required=True)
    register_mitm_command(sub)
    args = parser.parse_args(["mitm", "relay", "--upstream", "x", "--downstream", "y"])
    assert args.upstream == "x" and args.mode == "both"
    args2 = parser.parse_args(["mitm", "scan", "--upstream", "x"])
    assert args2.br_rounds == 2


async def test_open_controller_pair_virtual():
    pair = await open_controller_pair("virtual", "virtual")
    try:
        assert pair.upstream is not None
        assert pair.downstream is not None
        # both upstream and downstream should have completed initialize() (buffer sizes filled)
        for ctrl in (pair.upstream, pair.downstream):
            assert (
                ctrl.le_acl_packet_length is not None
                or ctrl.acl_packet_length is not None
            )
    finally:
        await pair.close()
