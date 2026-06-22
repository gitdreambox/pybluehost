"""`pybluehost app pts-tester` — run a BTP tester for autoptsclient (Phase 2 P.5)."""
import argparse
import asyncio
import logging

from pybluehost.cli._lifecycle import (
    add_common_arguments, run_app_command, trace_kwargs_from_args,
)


def register_pts_tester_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "pts-tester",
        help="Run a BTP tester listening for autoptsclient (Phase 2)",
    )
    add_common_arguments(p)
    p.add_argument(
        "--listen", default="127.0.0.1:65103",
        help="host:port to listen on for autoptsclient (default 127.0.0.1:65103)",
    )
    p.set_defaults(func=lambda args: asyncio.run(
        run_app_command(
            args.transport,
            lambda stack, stop: _pts_tester_main(stack, stop, listen=args.listen),
            **trace_kwargs_from_args(args),
        )
    ))


async def _pts_tester_main(stack, stop_event, *, listen: str):
    logger = logging.getLogger(__name__)
    from pybluehost.pts.actions import IutActions
    from pybluehost.pts.btp import (
        BtpServiceRegistry, BtpTester, CoreService,
    )
    from pybluehost.pts.btp.services.gap import GapService
    from pybluehost.pts.btp.services.gatt import GattService

    if ":" not in listen:
        raise ValueError(f"--listen must be host:port, got {listen!r}")
    host, port_str = listen.rsplit(":", 1)
    port = int(port_str)

    actions = IutActions(stack)
    registry = BtpServiceRegistry()
    registry.register(CoreService(registry=registry))
    tester = BtpTester(registry=registry, host=host, port=port)
    gap = GapService(actions=actions, tester=tester)
    registry.register(gap)
    gatt = GattService(actions=actions, tester=tester)
    registry.register(gatt)
    await tester.start()

    # Hook stack connection events into GapService for DEVICE_CONNECTED/DISCONNECTED
    # and attach GATT notification listeners to new central connections.
    def _on_conn(ev):
        if ev.state not in ("connected", "disconnected"):
            return
        peer = getattr(ev, "peer_address", None)
        if peer is None:
            return
        addr_type_attr = getattr(peer, "address_type", 0)
        addr_type = getattr(addr_type_attr, "value", addr_type_attr)
        raw = getattr(peer, "address", None) or getattr(peer, "bytes", None)
        if raw is None:
            return
        peer_bytes = bytes(raw)[:6].ljust(6, b"\x00")
        gap.on_connection_state_change(
            handle=ev.handle or 0,
            addr=peer_bytes,
            addr_type=int(addr_type),
            connected=(ev.state == "connected"),
        )
        # When a central connection comes up, wire GATT notifications through
        # GattService → BTP 0x80 event stream.
        if ev.state == "connected":
            try:
                session = actions.status()
                conn_info = session.connections.get(ev.handle)
            except Exception:
                conn_info = None
            client = getattr(conn_info, "gatt_client", None) if conn_info else None
            if client is not None:
                gatt.attach_to_gatt_client(client, peer=peer_bytes, addr_type=int(addr_type))
    stack.on_connection_event(_on_conn)

    logger.info(
        "PyBlueHost BTP tester listening on %s:%d "
        "(Core + GAP + GATT; L2CAP/SMP land in P.8)",
        host, port,
    )
    try:
        await stop_event.wait()
    finally:
        await tester.stop()
