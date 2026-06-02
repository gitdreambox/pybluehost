import argparse

import pytest

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


from pybluehost.cli.app.mitm.controllers import open_controller_pair


@pytest.mark.asyncio
async def test_open_controller_pair_virtual():
    pair = await open_controller_pair("virtual", "virtual")
    try:
        assert pair.upstream is not None
        assert pair.downstream is not None
        assert pair.downstream.le_acl_packet_length is not None or \
               pair.downstream.acl_packet_length is not None
    finally:
        await pair.close()
