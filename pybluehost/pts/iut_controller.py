"""JSON-line TCP controller for driving PyBlueHost as a PTS IUT."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any

from pybluehost.core.address import BDAddress
from pybluehost.pts.actions import IutActions

logger = logging.getLogger(__name__)


COMMANDS = (
    "status",
    "advertise",
    "stop-advertise",
    "connectable",
    "discoverable",
    "connect",
    "pair",
    "l2cap-connect",
    "l2cap-le-listen",
    "l2cap-le-connect",
)
_PTS_SDP_HANDLE_ATTR = "_pts_sdp_record_handle"


def _ok(**fields: Any) -> dict[str, Any]:
    return {"ok": True, **fields}


def _parse_bool(value: Any, *, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() not in {"0", "false", "off", "no"}


def _parse_int(value: Any, *, name: str) -> int:
    if value is None:
        raise ValueError(f"{name} is required")
    if isinstance(value, int):
        return value
    return int(str(value), 0)


def _parse_float(value: Any, *, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value))


def _last_handle(actions: IutActions) -> int | None:
    return actions.status().last_handle


def _find_handle(actions: IutActions, addr: BDAddress, *, transport: str) -> int | None:
    for conn in actions.status().connections.values():
        if conn.peer == addr and conn.transport == transport:
            return conn.handle
    return None


def _find_classic_handle(actions: IutActions, addr: BDAddress) -> int | None:
    return _find_handle(actions, addr, transport="classic")


def _find_le_handle(actions: IutActions, addr: BDAddress) -> int | None:
    return _find_handle(actions, addr, transport="le")


def _any_active_handle(actions: IutActions) -> int | None:
    """Handle of any currently-open link, preferring a real Classic connection.

    PTS-initiated incoming ACL links are recorded with peer=None (the connection
    event carries no peer address) and may be mislabeled transport="le", so
    address/transport lookup never matches them. During a PTS test the link to
    drive is that single active connection.
    """
    connections = actions.status().connections
    if not connections:
        return None
    for conn in connections.values():
        if conn.transport == "classic":
            return conn.handle
    return next(iter(connections.values())).handle


def ensure_pts_sdp_records(stack: Any) -> int:
    """Register a minimal SDP record matching the default SDP PTS PIXIT."""
    existing = getattr(stack, _PTS_SDP_HANDLE_ATTR, None)
    if existing is not None:
        return existing

    from pybluehost.classic.sdp import DataElement, ServiceRecord

    record = ServiceRecord()
    record.attributes[0x0001] = DataElement.sequence([DataElement.uuid16(0x0100)])
    record.attributes[0x0004] = DataElement.sequence([
        DataElement.sequence([DataElement.uuid16(0x0100)]),
    ])
    record.attributes[0x0005] = DataElement.sequence([DataElement.uuid16(0x1002)])
    record.attributes[0x0002] = DataElement.uint32(0x00001000)
    record.attributes[0x0100] = DataElement.text("PyBlueHost PTS SDP")
    handle = stack.sdp.register(record)
    record.attributes[0x0000] = DataElement.uint32(handle)
    setattr(stack, _PTS_SDP_HANDLE_ATTR, handle)
    return handle


async def handle_command(
    payload: Mapping[str, Any],
    *,
    actions: IutActions,
    stack: Any,
    transport: str,
) -> dict[str, Any]:
    """Handle one decoded JSON command and return a JSON-serializable dict."""
    cmd = payload.get("cmd")
    if cmd == "status":
        return _ok(
            bd_addr=str(stack.local_address) if stack.local_address is not None else None,
            transport=transport,
            last_handle=_last_handle(actions),
        )

    if cmd == "advertise":
        await actions.advertise()
        return _ok()

    if cmd in {"stop-advertise", "stop_advertise"}:
        await actions.stop_advertising()
        return _ok()

    if cmd == "connectable":
        await actions.set_connectable(_parse_bool(payload.get("enabled"), default=True))
        return _ok()

    if cmd == "discoverable":
        await actions.set_discoverable(_parse_bool(payload.get("enabled"), default=True))
        return _ok()

    if cmd == "connect":
        addr_raw = payload.get("addr")
        if not isinstance(addr_raw, str):
            raise ValueError("addr is required")
        addr = BDAddress.from_string(addr_raw)
        handle = await actions.connect(addr, le=_parse_bool(payload.get("le"), default=True))
        return _ok(handle=handle)

    if cmd == "pair":
        handle = None
        if payload.get("handle") is not None:
            handle = _parse_int(payload.get("handle"), name="handle")
        io_cap = payload.get("io_cap") or payload.get("io-cap")
        if io_cap is not None and not isinstance(io_cap, str):
            raise ValueError("io_cap must be a string")
        await actions.pair(
            handle=handle,
            io_cap=io_cap,
            mitm=_parse_bool(payload.get("mitm"), default=False),
        )
        return _ok()

    if cmd in {"l2cap-connect", "l2cap_connect"}:
        addr_raw = payload.get("addr")
        if not isinstance(addr_raw, str):
            raise ValueError("addr is required")
        addr = BDAddress.from_string(addr_raw)
        psm = _parse_int(payload.get("psm"), name="psm")
        handle = _find_classic_handle(actions, addr)
        if handle is None:
            # PTS-initiated incoming ACL links don't match by address (recorded
            # with peer=None). Reuse the single active link rather than opening a
            # fresh outgoing ACL connection to PTS, which PTS never accepts mid-test.
            handle = _any_active_handle(actions)
        if handle is None:
            handle = await actions.connect(addr, le=False)
        channel = await stack.l2cap.connect_classic_channel(handle, psm)
        return _ok(handle=handle, cid=channel.cid)

    if cmd in {"l2cap-le-listen", "l2cap_le_listen"}:
        psm = _parse_int(payload.get("psm"), name="psm")

        def _on_channel(channel: Any) -> None:
            logger.info("Accepted LE CoC channel cid=0x%04X", getattr(channel, "cid", 0))

        stack.l2cap.listen_le_coc_channel(psm, _on_channel)
        return _ok(psm=psm)
    if cmd in {"l2cap-le-connect", "l2cap_le_connect"}:
        psm = _parse_int(payload.get("psm"), name="psm")
        if payload.get("handle") is not None:
            handle = _parse_int(payload.get("handle"), name="handle")
        else:
            addr_raw = payload.get("addr")
            if isinstance(addr_raw, str):
                addr = BDAddress.from_string(addr_raw)
                handle = _find_le_handle(actions, addr)
                if handle is None:
                    handle = await actions.connect(addr, le=True)
            else:
                handle = _last_handle(actions)
                if handle is None:
                    raise ValueError("addr or active handle is required")
        channel = await stack.l2cap.connect_le_coc_channel(
            handle=handle,
            psm=psm,
            mtu=_parse_int(payload.get("mtu", 512), name="mtu"),
            mps=_parse_int(payload.get("mps", 247), name="mps"),
            initial_credits=_parse_int(payload.get("credits", 10), name="credits"),
            timeout=_parse_float(payload.get("timeout"), default=5.0),
        )
        return _ok(handle=handle, cid=channel.cid)

    if cmd in {"help", "commands"}:
        return _ok(commands=list(COMMANDS))

    raise ValueError(f"unknown command: {cmd!r}")


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    actions: IutActions,
    stack: Any,
    transport: str,
) -> None:
    peer = writer.get_extra_info("peername")
    logger.info("PTS IUT control client connected: %s", peer)
    try:
        while not reader.at_eof():
            line = await reader.readline()
            if not line:
                break
            try:
                payload = json.loads(line.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("JSON command must be an object")
                result = await handle_command(
                    payload,
                    actions=actions,
                    stack=stack,
                    transport=transport,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("PTS IUT command failed")
                result = {
                    "ok": False,
                    "error": str(exc),
                    "type": type(exc).__name__,
                }
            writer.write((json.dumps(result, separators=(",", ":")) + "\n").encode("utf-8"))
            await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()
        logger.info("PTS IUT control client disconnected: %s", peer)


async def run_json_controller(
    stack: Any,
    stop_event: asyncio.Event,
    *,
    transport: str,
    host: str = "127.0.0.1",
    port: int = 18766,
) -> None:
    """Run a JSON-line TCP server until ``stop_event`` is set."""
    ensure_pts_sdp_records(stack)
    actions = IutActions(stack)
    server = await asyncio.start_server(
        lambda reader, writer: _handle_client(
            reader,
            writer,
            actions=actions,
            stack=stack,
            transport=transport,
        ),
        host,
        port,
    )
    sockets = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    logger.warning(
        "PyBlueHost PTS IUT JSON controller listening on %s; local=%s transport=%s",
        sockets,
        stack.local_address,
        transport,
    )
    async with server:
        await stop_event.wait()