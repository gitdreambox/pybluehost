#!/usr/bin/env python
"""Resolve the two BE200 roles for a PTS run: which is the IUT, which is the PTS dongle.

The two BE200s are indistinguishable by name and their libusb enumeration order
swaps on replug/reboot, so both ``pts_run_batch.sh`` and ``pts_harvest.sh`` used
to hardcode an occurrence (``usb:8087:0036#1``) and an instance path
(``USB_INTEL:Free:6&1687A1FD&0&3``).  When a replug flips either one,
autoptsserver silently binds the *IUT* dongle and every case dies at ~13 s with
``USBAccessDeniedError`` from pts-tester — which looks like a stack bug but is
not.  Both stale defaults have already cost a debugging round.

This resolves the roles from the live hardware instead, keyed on the IUT's
Bluetooth address (stable per device, unlike the enumeration index):

    BD_ADDR                -> the IUT dongle (read with HCI Read_BD_ADDR)
    libusb port_numbers    -> the other dongle's hub port
    Windows PnP instance   -> the ``<hub>&0&<port>`` suffix autoptsserver wants

Output is shell-assignable so a wrapper can ``eval`` it::

    IUT_TRANSPORT=usb:8087:0036#1
    PTS_DONGLE=USB_INTEL:Free:6&1687A1FD&0&3

The PTS dongle's instance path comes from PnP alone, so it resolves even while
autoptsserver holds that dongle open.  Only the IUT has to be free to open,
which holds between cases — probe before spawning a run, not during one.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import subprocess
import sys

VID, PID = 0x8087, 0x0036
DEFAULT_IUT_ADDRESS = "A0:85:27:2F:60:15"
INSTANCE_RE = re.compile(
    r"USB\\VID_%04X&PID_%04X\\(?P<hub>[^\\]+)&0&(?P<port>\d+)" % (VID, PID),
    re.IGNORECASE,
)


def _libusb_backend():
    import usb.backend.libusb1

    try:
        import libusb_package

        path = libusb_package.find_library("libusb-1.0")
    except ImportError:
        path = None
    return usb.backend.libusb1.get_backend(find_library=lambda _n: path)


def _devices() -> list[dict]:
    """Enumerate the BE200s in the order pybluehost's ``occurrence=`` uses."""
    import usb.core

    backend = _libusb_backend()
    found = []
    for index, dev in enumerate(
        usb.core.find(find_all=True, idVendor=VID, idProduct=PID, backend=backend), 1
    ):
        ports = list(getattr(dev, "port_numbers", None) or [])
        found.append({"occurrence": index, "port": ports[-1] if ports else None})
    return found


def _instance_ports() -> dict[int, str]:
    """Map hub port number -> ``<hub>&0&<port>`` suffix, via PnP."""
    script = (
        "Get-PnpDevice -PresentOnly -EA SilentlyContinue | "
        "Where-Object { $_.InstanceId -match 'VID_%04X&PID_%04X' } | "
        "Select-Object -ExpandProperty InstanceId" % (VID, PID)
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=60, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"# powershell query failed: {exc}", file=sys.stderr)
        return {}

    ports: dict[int, str] = {}
    for line in out.splitlines():
        m = INSTANCE_RE.search(line.strip())
        if m:
            ports[int(m.group("port"))] = f"{m.group('hub')}&0&{m.group('port')}"
    return ports


def _addresses(occurrences: list[int]) -> dict[int, str]:
    """Map occurrence -> BD_ADDR for every BE200 that can be opened right now."""
    from pybluehost.stack import Stack

    async def read(occurrence: int) -> tuple[int, str | None]:
        try:
            stack = await Stack.from_usb(vid=VID, pid=PID, occurrence=occurrence)
        except Exception:  # noqa: BLE001 — busy dongle is an expected outcome
            return occurrence, None
        try:
            return occurrence, str(stack._local_address)
        finally:
            await stack.close()

    async def run() -> dict[int, str]:
        pairs = await asyncio.gather(*(read(o) for o in occurrences))
        return {occ: addr for occ, addr in pairs if addr}

    return asyncio.run(run())


def resolve(iut_address: str) -> tuple[str, str]:
    """Return ``(iut_transport, pts_dongle_spec)`` for the live rig."""
    devices = _devices()
    if len(devices) < 2:
        raise RuntimeError(f"expected 2 BE200s, found {len(devices)}")

    wanted = iut_address.replace("-", ":").strip().upper()
    addrs = _addresses([d["occurrence"] for d in devices])

    iut = next(
        (occ for occ, addr in addrs.items() if addr.replace("-", ":").upper() == wanted),
        None,
    )
    if iut is None:
        seen = ", ".join(f"#{occ}={addr}" for occ, addr in sorted(addrs.items())) or "none"
        raise RuntimeError(
            f"no BE200 reports the IUT address {iut_address} "
            f"(openable: {seen}; a dongle held by a stray pts-tester shows up as unopenable)"
        )

    others = [d for d in devices if d["occurrence"] != iut]
    if not others:
        raise RuntimeError("could not identify the non-IUT BE200")

    ports = _instance_ports()
    for dev in others:
        suffix = ports.get(dev["port"])
        if suffix:
            print(
                f"# IUT = occurrence {iut} ({addrs[iut]}); "
                f"PTS dongle = occurrence {dev['occurrence']} (port {dev['port']})",
                file=sys.stderr,
            )
            return f"usb:{VID:04X}:{PID:04X}#{iut}", f"USB_INTEL:Free:{suffix}"
    raise RuntimeError(
        "could not map the non-IUT BE200 to a Windows instance path "
        f"(PnP ports known: {sorted(ports)})"
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--iut-address", default=DEFAULT_IUT_ADDRESS,
                   help="BD_ADDR of the IUT dongle (default: %(default)s)")
    args = p.parse_args()

    try:
        iut_transport, dongle = resolve(args.iut_address)
    except RuntimeError as exc:
        print(f"resolve failed: {exc}", file=sys.stderr)
        return 1

    print(f"IUT_TRANSPORT={iut_transport}")
    print(f"PTS_DONGLE={dongle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
