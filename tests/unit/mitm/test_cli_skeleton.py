import argparse

from pybluehost.cli.app.mitm.cli import register_mitm_command
from pybluehost.cli.app.mitm.controllers import open_controller_pair


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


async def test_open_controller_pair_virtual():
    pair = await open_controller_pair("virtual", "virtual")
    try:
        assert pair.upstream is not None
        assert pair.downstream is not None
        # 上下游都应完成 initialize()(buffer 大小被填充)
        for ctrl in (pair.upstream, pair.downstream):
            assert (
                ctrl.le_acl_packet_length is not None
                or ctrl.acl_packet_length is not None
            )
    finally:
        await pair.close()
