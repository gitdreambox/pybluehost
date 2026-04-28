import argparse
from pybluehost.cli.app.sdp_browser import _sdp_browser_main


async def test_sdp_browser_requires_target_for_all_transports(capsys):
    args = argparse.Namespace(transport="virtual", target=None)
    rc = await _sdp_browser_main(args)
    err = capsys.readouterr().err
    assert rc == 2
    assert "--target is required" in err
