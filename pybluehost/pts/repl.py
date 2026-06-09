"""REPL front-end for the IUT action layer (Phase 1 manual driving).

`parse_repl_command(line) -> (cmd, args)` is a pure function: it splits
the line with shlex, separates `--key=value` / `--flag` options from
positional arguments, and returns a normalized form for dispatch.
"""
from __future__ import annotations

import asyncio
import logging
import shlex

logger = logging.getLogger(__name__)


_KNOWN_COMMANDS = {
    "advertise",
    "scan",
    "connect",
    "disconnect",
    "pair",
    "encrypt",
    "notify",
    "indicate",
    "read",
    "write",
    "sdp-browse",
    "rfcomm-open",
    "l2cap-connect",
    "set-io-cap",
    "status",
    "help",
    "quit",
}
_ALIASES = {"exit": "quit"}


def parse_repl_command(line: str) -> tuple[str | None, dict]:
    """Parse one REPL line.

    Returns `(None, {})` for empty lines, `("unknown", {...})` for unknown
    commands, otherwise `(cmd, args)` where `args` always has `_positional`
    plus zero or more `--name=value` / `--flag` entries.
    """
    line = line.strip()
    if not line:
        return None, {}
    try:
        parts = shlex.split(line)
    except ValueError as e:
        return "unknown", {"_error": str(e)}
    cmd_raw = parts[0]
    cmd = _ALIASES.get(cmd_raw, cmd_raw)
    if cmd not in _KNOWN_COMMANDS:
        return "unknown", {"_positional": parts[1:]}

    args: dict = {"_positional": []}
    for token in parts[1:]:
        if token.startswith("--"):
            body = token[2:]
            if "=" in body:
                k, _, v = body.partition("=")
                args[k] = v
            else:
                args[body] = True
        else:
            args["_positional"].append(token)
    return cmd, args


async def run_repl(actions, *, prompt: str = "pts> ") -> None:
    """Run the interactive REPL until EOF or `quit`. Uses run_in_executor for stdin
    so the event loop stays responsive to stack events (incoming connections, ATT,
    SMP PDUs) between input lines.
    """
    from pybluehost.pts.actions import IutActions

    loop = asyncio.get_running_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, input, prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            return
        cmd, args = parse_repl_command(line)
        if cmd is None:
            continue
        if cmd == "quit":
            return
        if cmd == "help":
            _print_help()
            continue
        try:
            await _dispatch(actions, cmd, args)
        except Exception as e:  # noqa: BLE001
            print(f"error: {e}")


def _print_help() -> None:
    """Print REPL command help."""
    print("commands: advertise / scan / connect / disconnect / pair / encrypt /")
    print("          notify / indicate / read / write / sdp-browse / rfcomm-open /")
    print("          l2cap-connect / set-io-cap / status / help / quit")


async def _dispatch(actions, cmd: str, args: dict) -> None:
    """Dispatch a parsed command to the IutActions layer."""
    pos = args.get("_positional", [])
    if cmd == "advertise":
        data = bytes.fromhex(args["data"]) if "data" in args else None
        await actions.advertise(data=data)
    elif cmd == "scan":
        await actions.scan(active=args.get("active", False))
    elif cmd == "connect":
        if not pos:
            raise ValueError("connect requires <addr>")
        addr = pos[0]
        await actions.connect(addr, le=not args.get("classic", False))
    elif cmd == "disconnect":
        handle = int(pos[0], 0) if pos else None
        await actions.disconnect(handle=handle)
    elif cmd == "pair":
        await actions.pair(io_cap=args.get("io-cap"), mitm=bool(args.get("mitm", False)))
    elif cmd == "encrypt":
        handle = int(pos[0], 0) if pos else None
        await actions.encrypt(handle=handle)
    elif cmd == "notify":
        if len(pos) < 2:
            raise ValueError("notify requires <char_handle> <hex_value> [conn_handle]")
        char = int(pos[0], 0)
        value = bytes.fromhex(pos[1])
        handle = int(pos[2], 0) if len(pos) > 2 else None
        await actions.notify(char, value, handle=handle)
    elif cmd == "indicate":
        if len(pos) < 2:
            raise ValueError("indicate requires <char_handle> <hex_value> [conn_handle]")
        char = int(pos[0], 0)
        value = bytes.fromhex(pos[1])
        handle = int(pos[2], 0) if len(pos) > 2 else None
        await actions.indicate(char, value, handle=handle)
    elif cmd == "read":
        if not pos:
            raise ValueError("read requires <char_handle>")
        char = int(pos[0], 0)
        handle = int(pos[1], 0) if len(pos) > 1 else None
        result = await actions.read(char, handle=handle)
        print(result.hex())
    elif cmd == "write":
        if len(pos) < 2:
            raise ValueError("write requires <char_handle> <hex_value> [conn_handle]")
        char = int(pos[0], 0)
        value = bytes.fromhex(pos[1])
        handle = int(pos[2], 0) if len(pos) > 2 else None
        await actions.write(char, value, handle=handle)
    elif cmd == "sdp-browse":
        if not pos:
            raise ValueError("sdp-browse requires <addr>")
        uuid = int(args["uuid"], 0) if "uuid" in args else None
        result = await actions.sdp_browse(pos[0], uuid=uuid)
        print(result)
    elif cmd == "rfcomm-open":
        if len(pos) < 2:
            raise ValueError("rfcomm-open requires <addr> <channel>")
        await actions.rfcomm_open(pos[0], int(pos[1], 0))
    elif cmd == "l2cap-connect":
        if len(pos) < 2:
            raise ValueError("l2cap-connect requires <addr> <psm>")
        await actions.l2cap_connect(pos[0], int(pos[1], 0))
    elif cmd == "set-io-cap":
        if not pos:
            raise ValueError("set-io-cap requires <cap_name>")
        actions.set_io_cap(pos[0])
    elif cmd == "status":
        print(actions.status())
    else:
        print(f"unknown command: {cmd}")
