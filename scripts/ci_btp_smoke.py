"""CI smoke: spawn pts-tester locally, walk a Core+GAP BTP command sequence.

Doesn't need autoptsserver or a PTS dongle — it's a self-check of the BTP
plumbing (frame codec + service dispatch + Core/GAP/GATT/L2CAP handlers).
"""
from __future__ import annotations

import asyncio
import socket
import subprocess
import sys

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import (
    BTP_HEADER_SIZE, BtpFrame, decode_btp_frame, encode_btp_frame,
)


async def _read_frame(reader: asyncio.StreamReader) -> BtpFrame:
    header = await reader.readexactly(BTP_HEADER_SIZE)
    data_len = int.from_bytes(header[3:5], "little")
    body = await reader.readexactly(data_len) if data_len else b""
    return decode_btp_frame(header + body)


def _expect_success(resp: BtpFrame, req_opcode: int, name: str) -> int:
    """auto-pts framing: success echoes the request opcode; failure is opcode 0x00
    (BTP_STATUS) with a single status byte."""
    if resp.opcode == op.OP_STATUS_RESPONSE:
        print(f"smoke: {name} failed: status 0x{resp.data[0]:02X}", file=sys.stderr)
        return 1
    if resp.opcode != req_opcode:
        print(f"smoke: {name} wrong response opcode 0x{resp.opcode:02X} "
              f"(expected 0x{req_opcode:02X})", file=sys.stderr)
        return 1
    return 0


async def _smoke(port: int) -> int:
    """Returns 0 on success, nonzero on failure."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        # 1. Wait for unsolicited READY event.
        ready = await asyncio.wait_for(_read_frame(reader), timeout=10.0)
        if ready.service != op.SERVICE_CORE or ready.opcode != op.OP_CORE_EVENT_READY:
            print(f"smoke: unexpected first frame {ready}", file=sys.stderr)
            return 1

        # 2. Core Read Supported Services.
        writer.write(encode_btp_frame(BtpFrame(
            service=op.SERVICE_CORE, opcode=op.OP_CORE_READ_SUPPORTED_SERVICES,
            controller_index=op.CONTROLLER_INDEX_NONE, data=b"",
        )))
        await writer.drain()
        resp = await asyncio.wait_for(_read_frame(reader), timeout=5.0)
        if _expect_success(resp, op.OP_CORE_READ_SUPPORTED_SERVICES, "Read Supported Services"):
            return 1
        # Success payload is the services bitfield directly (no status byte):
        # bit 0 = Core, bit 1 = GAP, bit 2 = GATT, bit 3 = L2CAP.
        services_bitfield = resp.data[0]
        for name, bit in [("Core", 0), ("GAP", 1), ("GATT", 2), ("L2CAP", 3)]:
            if not (services_bitfield & (1 << bit)):
                print(f"smoke: {name} service missing from bitfield", file=sys.stderr)
                return 1

        # 3. GAP Set Powered.
        writer.write(encode_btp_frame(BtpFrame(
            service=op.SERVICE_GAP, opcode=op.OP_GAP_SET_POWERED,
            controller_index=0, data=bytes([1]),
        )))
        await writer.drain()
        resp = await asyncio.wait_for(_read_frame(reader), timeout=5.0)
        if _expect_success(resp, op.OP_GAP_SET_POWERED, "GAP Set Powered"):
            return 1

        # 4. GATT Add Service (Battery Service 0x180F).
        body = bytes([op.GATT_SERVICE_PRIMARY, 2]) + bytes.fromhex("0F18")
        writer.write(encode_btp_frame(BtpFrame(
            service=op.SERVICE_GATT, opcode=op.OP_GATT_ADD_SERVICE,
            controller_index=0, data=body,
        )))
        await writer.drain()
        resp = await asyncio.wait_for(_read_frame(reader), timeout=5.0)
        if _expect_success(resp, op.OP_GATT_ADD_SERVICE, "GATT Add Service"):
            return 1

        print(
            "smoke: PASS — Core READY + Read Supported Services "
            "(Core+GAP+GATT+L2CAP advertised) + GAP Set Powered + GATT Add Service"
        )
        return 0
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def main() -> int:
    # Pick a free local port.
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    _, port = s.getsockname()
    s.close()

    proc = subprocess.Popen(
        [sys.executable, "-m", "pybluehost", "app", "pts-tester",
         "-t", "virtual", f"--listen=127.0.0.1:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    # Wait until the tester accepts connections.
    for _ in range(50):
        try:
            probe = socket.socket()
            probe.settimeout(0.2)
            probe.connect(("127.0.0.1", port))
            probe.close()
            break
        except OSError:
            await asyncio.sleep(0.1)
    else:
        print("smoke: tester didn't start listening", file=sys.stderr)
        proc.terminate()
        return 1

    try:
        return await _smoke(port)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
