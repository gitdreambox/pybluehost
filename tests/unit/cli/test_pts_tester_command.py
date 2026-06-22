import argparse

from pybluehost.cli.app.pts_tester import register_pts_tester_command


def test_register_pts_tester_command():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd")
    register_pts_tester_command(subparsers)
    ns = parser.parse_args([
        "pts-tester", "-t", "virtual",
        "--listen=127.0.0.1:65103",
    ])
    assert ns.cmd == "pts-tester"
    assert ns.listen == "127.0.0.1:65103"


def test_listen_default_is_localhost_65103():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="cmd")
    register_pts_tester_command(subparsers)
    ns = parser.parse_args(["pts-tester", "-t", "virtual"])
    assert ns.listen == "127.0.0.1:65103"
