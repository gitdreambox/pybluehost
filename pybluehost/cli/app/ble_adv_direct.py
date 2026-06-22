"""'app ble-adv-direct' - bond over ordinary advertising, then directed advertise."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
from pathlib import Path

from pybluehost.cli._lifecycle import add_common_arguments, run_app_command, trace_kwargs_from_args
from pybluehost.cli.app._ble_peripheral import (
    _ensure_hci_success,
    start_connectable_advertising,
    start_directed_advertising,
    stop_advertising,
)
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability
from pybluehost.ble.security import SecurityConfig
from pybluehost.ble.smp import JsonBondStorage
from pybluehost.profiles.ble import BatteryServer, HeartRateServer
from pybluehost.stack import Stack, StackConfig, StackConnectionEvent

logger = logging.getLogger(__name__)


def register_ble_adv_direct_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "ble-adv-direct",
        help="Advertise connectable first, then directed advertise to the bonded phone",
    )
    p.add_argument("-n", "--name", default="PyBlueHost", help="Local name in scan response")
    p.add_argument(
        "--peer-address",
        help="Phone target address for directed advertising; omitted means use the first learned peer",
    )
    p.add_argument(
        "--peer-address-type",
        choices=["public", "random"],
        default="public",
        help="Phone target address type for directed advertising",
    )
    p.add_argument(
        "--own-address-type",
        choices=["public", "random"],
        default="public",
        help="Own legacy advertising address type",
    )
    p.add_argument(
        "--direct-duty",
        choices=["low", "high"],
        default="low",
        help="Directed advertising duty cycle; high stops quickly on many controllers",
    )
    p.add_argument(
        "--direct-timeout",
        type=float,
        default=60.0,
        help="Seconds to wait for the directed advertising reconnect",
    )
    p.add_argument(
        "--direct-interval-ms",
        type=float,
        default=100.0,
        help="Low-duty directed advertising interval in milliseconds",
    )
    p.add_argument(
        "--bond-store",
        type=Path,
        default=Path("ble_adv_direct_bonds.json"),
        help="JSON file used to persist BLE bond keys for reconnect",
    )
    add_common_arguments(p)
    p.set_defaults(
        func=lambda args: asyncio.run(
            run_app_command(
                args.transport,
                lambda s, e: _ble_adv_direct_main(
                    s,
                    e,
                    name=args.name,
                    peer_address=args.peer_address,
                    peer_address_type=args.peer_address_type,
                    own_address_type=args.own_address_type,
                    direct_duty=args.direct_duty,
                    direct_timeout=args.direct_timeout,
                    direct_interval_ms=args.direct_interval_ms,
                ),
                config=_build_ble_adv_direct_stack_config(args.bond_store),
                **trace_kwargs_from_args(args),
                trace_spec=getattr(args, "_trace_spec", None),
            )
        )
    )


def _build_ble_adv_direct_stack_config(bond_store: Path) -> StackConfig:
    return StackConfig(
        bond_storage=JsonBondStorage(bond_store),
        security=SecurityConfig(enable_secure_connections=True, mitm_required=True),
        le_io_capability=IOCapability.DISPLAY_YES_NO,
    )


def _format_address_type(address: BDAddress) -> str:
    return getattr(address.type, "name", str(int(address.type)))


def _public_random_address_type(address: BDAddress) -> int:
    return 0x01 if int(address.type) in (0x01, 0x03) else 0x00


class _ConnectionEventQueue:
    def __init__(self, stack: Stack) -> None:
        self._queue: asyncio.Queue[StackConnectionEvent] = asyncio.Queue()
        stack.on_connection_event(self._queue.put_nowait)

    async def wait_for(self, state: str, *, handle: int | None = None, timeout: float | None = None) -> StackConnectionEvent:
        while True:
            event = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            if event.state != state:
                continue
            if handle is not None and event.handle != handle:
                continue
            return event


async def _learn_peer_address(stack: Stack, handle: int | None) -> BDAddress | None:
    if handle is None:
        return None
    await asyncio.sleep(0)
    smp = getattr(stack, "smp", None)
    peers = getattr(smp, "_peer_addrs", None)
    if isinstance(peers, dict):
        peer = peers.get(handle)
        if isinstance(peer, BDAddress):
            return peer
    return None


async def _latest_bond(stack: Stack):
    config = getattr(stack, "_config", None)
    storage = getattr(config, "bond_storage", None)
    if storage is None:
        return None
    bonds = await storage.list_bonds()
    if not bonds:
        return None
    return bonds[-1]


async def _configure_resolving_list_for_bond(stack: Stack, bond) -> None:
    if bond is None or not getattr(bond, "irk", None):
        return
    from pybluehost.hci.packets import (
        HCI_LE_Add_Device_To_Resolving_List_Command,
        HCI_LE_Clear_Resolving_List_Command,
        HCI_LE_Set_Address_Resolution_Enable_Command,
        HCI_LE_Set_Privacy_Mode_Command,
    )

    peer = bond.peer_address
    if not isinstance(peer, BDAddress):
        return
    peer_type = _public_random_address_type(peer)
    peer_addr = peer.to_hci()
    cmd = HCI_LE_Set_Address_Resolution_Enable_Command(address_resolution_enable=0)
    _ensure_hci_success(await stack.hci.send_command(cmd), cmd.opcode)
    cmd = HCI_LE_Clear_Resolving_List_Command()
    _ensure_hci_success(await stack.hci.send_command(cmd), cmd.opcode)
    cmd = HCI_LE_Add_Device_To_Resolving_List_Command(
        peer_identity_address_type=peer_type,
        peer_identity_address=peer_addr,
        peer_irk=bond.irk,
        local_irk=bytes(16),
    )
    _ensure_hci_success(await stack.hci.send_command(cmd), cmd.opcode)
    try:
        cmd = HCI_LE_Set_Privacy_Mode_Command(
            peer_identity_address_type=peer_type,
            peer_identity_address=peer_addr,
            privacy_mode=1,
        )
        _ensure_hci_success(await stack.hci.send_command(cmd), cmd.opcode)
    except Exception as exc:  # noqa: BLE001
        logger.debug("LE Set Privacy Mode not applied: %s", exc)
    cmd = HCI_LE_Set_Address_Resolution_Enable_Command(address_resolution_enable=1)
    _ensure_hci_success(await stack.hci.send_command(cmd), cmd.opcode)
    logger.info("Resolving list configured for directed peer %s", peer)


async def _register_demo_services(stack: Stack) -> None:
    battery = BatteryServer(initial_level=85)
    hrs = HeartRateServer(sensor_location=0x02)
    await battery.register(stack.gatt_server)
    await hrs.register(stack.gatt_server)


async def _ble_adv_direct_main(
    stack: Stack,
    stop: asyncio.Event,
    *,
    name: str,
    peer_address: str | None,
    peer_address_type: str,
    own_address_type: str,
    direct_duty: str,
    direct_timeout: float,
    direct_interval_ms: float = 100.0,
) -> None:
    events = _ConnectionEventQueue(stack)
    await _register_demo_services(stack)
    await start_connectable_advertising(
        stack,
        service_uuids=[0x180F, 0x180D],
        local_name=name,
    )
    logger.info("Ordinary connectable advertising started as %r", name)
    logger.info("Pair/bond from the phone, then disconnect the phone to enter directed advertising")

    first_connection = await events.wait_for("connected")
    first_handle = first_connection.handle
    connected_peer = first_connection.peer_address
    logger.info("Phone connected on handle 0x%04X", first_handle if first_handle is not None else 0)
    if connected_peer is not None:
        logger.info(
            "Phone peer address from connection event: %s (%s)",
            connected_peer,
            _format_address_type(connected_peer),
        )
    smp = getattr(stack, "smp", None)
    request_security = getattr(smp, "request_security", None)
    if request_security is not None and first_handle is not None:
        await request_security(first_handle, auth_req=0x0D)
        logger.info("SMP Security Request sent on handle 0x%04X auth_req=0x0D", first_handle)

    disconnected = await events.wait_for("disconnected", handle=first_handle)
    logger.info("Phone disconnected from handle 0x%04X: %s", first_handle or 0, disconnected.reason)

    learned_peer = await _learn_peer_address(stack, first_handle)
    latest_bond = await _latest_bond(stack)
    bonded_peer = latest_bond.peer_address if latest_bond is not None else None
    target_address: str | BDAddress | None = peer_address or bonded_peer or connected_peer or learned_peer
    if target_address is None:
        raise RuntimeError(
            "No peer address learned from the first connection; pass --peer-address and --peer-address-type"
        )
    if isinstance(target_address, BDAddress):
        peer_address_type = "random" if _public_random_address_type(target_address) == 0x01 else "public"

    await stop_advertising(stack)
    await _configure_resolving_list_for_bond(stack, latest_bond)
    await start_directed_advertising(
        stack.hci,
        peer_address=target_address,
        peer_address_type=peer_address_type,
        own_address_type=own_address_type,
        duty=direct_duty,
        interval_ms=direct_interval_ms,
    )
    logger.info(
        "Directed advertising started: target=%s type=%s own_type=%s duty=%s",
        target_address,
        peer_address_type,
        own_address_type,
        direct_duty,
    )

    reconnect = await events.wait_for("connected", timeout=direct_timeout)
    logger.info("Directed advertising reconnect succeeded on handle 0x%04X", reconnect.handle or 0)
    try:
        await stop.wait()
    finally:
        with contextlib.suppress(Exception):
            await stop_advertising(stack)
