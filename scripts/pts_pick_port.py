#!/usr/bin/env python
"""Resolve a usable TCP port for the PTS harness (server port / XML-RPC callback).

After a Windows reboot Hyper-V/winNAT reserves random ephemeral TCP ranges
(``netsh int ipv4 show excludedportrange protocol=tcp``).  A port inside one of
those ranges fails to bind with ``WinError 10013`` — the autoptsserver dies right
after printing "Serving on port N ..." (its exit code is still 0, so a wrapper
sees nothing wrong), and autoptsclient's LT1-callback socket dies the same way
while every case then times out.

Do not parse the netsh listing: its headings are localized and the ranges move
between boots.  Instead, ask the OS directly by trying to bind — that is the
exact condition that matters.

Usage:
    python scripts/pts_pick_port.py 65000          # print a usable server port
    python scripts/pts_pick_port.py 60000 --span 200

Exit status is 0 when a port was found (printed on stdout, no other output, so
it is safe to use in a command substitution), 1 otherwise.
"""
from __future__ import annotations

import argparse
import socket
import sys


def _bindable(port: int) -> bool:
    """True when the harness could bind this port on the wildcard address.

    ``SO_EXCLUSIVEADDRUSE`` is deliberately NOT set: autoptsserver binds with
    the plain socket default, so an already-listening port must read as busy
    here too (``Get-NetTCPConnection -State Listen`` would agree).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("", port))
    except OSError:
        return False
    finally:
        sock.close()
    return True


def pick(preferred: int, span: int = 1000) -> int | None:
    """Return ``preferred`` if bindable, else the nearest bindable port.

    Searches upward first (keep the usual direction), then downward — Windows
    tends to reserve *consecutive* blocks, so a reboot can swallow everything
    from 64975 to 65274 and leave 65000 with no free port above it at all.
    """
    if not 1 <= preferred <= 65535:
        raise ValueError(f"port out of range: {preferred}")
    if _bindable(preferred):
        return preferred
    for delta in range(1, span + 1):
        for port in (preferred + delta, preferred - delta):
            if 1 <= port <= 65535 and _bindable(port):
                return port
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preferred", type=int, help="port to try first")
    parser.add_argument("--span", type=int, default=1000,
                        help="how far to search from <preferred> (default 1000)")
    args = parser.parse_args(argv)

    port = pick(args.preferred, args.span)
    if port is None:
        print(f"pts_pick_port: no bindable port within +/-{args.span} "
              f"of {args.preferred}", file=sys.stderr)
        return 1
    print(port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
