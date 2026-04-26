import argparse
from pybluehost.cli.app.sdp_browser import _sdp_browser_main


async def test_sdp_browser_loopback_prints_records(capsys):
    args = argparse.Namespace(transport="loopback", target=None)
    rc = await _sdp_browser_main(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "SDP" in out or "records" in out.lower()
