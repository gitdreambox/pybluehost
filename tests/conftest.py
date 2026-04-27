"""Shared pytest fixtures and hooks for PyBlueHost test suite."""
from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register transport-selection CLI options."""
    parser.addoption(
        "--transport",
        action="store",
        default=None,
        help="Primary transport spec: virtual | usb[:vendor=...,bus=N,address=M] | uart:/dev/...",
    )
    parser.addoption(
        "--transport-peer",
        action="store",
        default=None,
        help="Peer transport spec (only affects peer_stack fixture). Same family as --transport.",
    )
    parser.addoption(
        "--list-transports",
        action="store_true",
        default=False,
        help="Print every detected Bluetooth transport adapter, then exit.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers and handle transport diagnostics."""
    # Markers are already declared in pyproject.toml; this hook is for
    # programmatic registration if pyproject.toml is not loaded.
    config.addinivalue_line("markers", "unit: isolated unit tests (no real hardware, no network)")
    config.addinivalue_line("markers", "integration: multi-layer tests using VirtualController + Loopback")
    config.addinivalue_line("markers", "e2e: full-stack Loopback double-stack tests")
    config.addinivalue_line("markers", "btsnoop: btsnoop file replay tests")
    config.addinivalue_line("markers", "hardware: real USB Bluetooth adapter required (skipped in CI)")
    config.addinivalue_line("markers", "slow: tests taking >5s")

    if config.getoption("--list-transports"):
        from pybluehost.transport.usb import USBTransport

        candidates = USBTransport.list_devices()
        if not candidates:
            print("[pybluehost-tests] No Bluetooth USB adapters detected.")
        else:
            print("[pybluehost-tests] Detected Bluetooth USB adapters:")
            for candidate in candidates:
                spec = (
                    f"usb:vendor={candidate.vendor},"
                    f"bus={candidate.bus},"
                    f"address={candidate.address}"
                )
                print(
                    f"  {candidate.vendor:8s} {candidate.name:10s} "
                    f"bus={candidate.bus} address={candidate.address}  ({spec})"
                )
        pytest.exit("--list-transports done", returncode=0)
