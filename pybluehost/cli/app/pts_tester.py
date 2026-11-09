"""`pybluehost app pts-tester` — run a BTP tester for autoptsclient (Phase 2 P.5)."""
import argparse
import asyncio
import logging
import os

from pybluehost.cli._lifecycle import (
    add_common_arguments, run_app_command, trace_kwargs_from_args,
)

#: Point this at a file path to make the IUT's bonds outlive the pts-tester
#: process (see ``_make_bond_storage``).
BOND_STORE_ENV = "PYBLUEHOST_PTS_BOND_STORE"


def register_pts_tester_command(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "pts-tester",
        help="Run a BTP tester listening for autoptsclient (Phase 2)",
    )
    add_common_arguments(p)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--listen", default="127.0.0.1:65103",
        help="host:port to listen on for autoptsclient (default 127.0.0.1:65103)",
    )
    mode.add_argument(
        "--connect", default=None, metavar="HOST:PORT",
        help="connect OUT to an auto-pts BTPSocketSrv at host:port "
             "(auto-pts is the BTP server; the IUT is the client)",
    )
    p.set_defaults(func=lambda args: asyncio.run(
        run_app_command(
            args.transport,
            lambda stack, stop: _pts_tester_main(
                stack, stop, listen=args.listen, connect=args.connect,
            ),
            **trace_kwargs_from_args(args),
        )
    ))


def _parse_host_port(spec: str, *, flag: str) -> tuple[str, int]:
    if ":" not in spec:
        raise ValueError(f"{flag} must be host:port, got {spec!r}")
    host, port_str = spec.rsplit(":", 1)
    return host, int(port_str)


def _make_bond_storage():
    """Bond storage for this pts-tester process.

    Default is in-memory: a fresh pts-tester is spawned per test case, so every
    case starts with a clean bond slate.

    ``PYBLUEHOST_PTS_BOND_STORE`` switches to a file-backed store that survives
    the case boundary, for cases where the IUT is required to already hold a
    bond when the case starts.
    """
    from pybluehost.ble.smp import InMemoryBondStorage, JsonBondStorage

    path = os.environ.get(BOND_STORE_ENV)
    if path:
        return JsonBondStorage(path)
    return InMemoryBondStorage()


def _forward_sec_level(gap, ev, *, peer_bytes: bytes, addr_type: int) -> None:
    """Turn the stack's "encrypted" connection event into BTP SEC_LEVEL_CHANGED.

    Bond-resume encryption (LL_ENC_REQUEST answered with a stored LTK) involves
    no pairing, so the pairing-driven emit in GapService never fires — but
    auto-pts advances its `conn.sec_level` model only via this event. Without
    it, WIDs that wait for a minimum security level (e.g. the EATT listen in
    GATT/SR/GAR/BV-11/12) time out and the case aborts even though the link is
    encrypted.
    """
    gap.on_sec_level_changed(
        addr=peer_bytes, addr_type=addr_type,
        sec_level=getattr(ev, "sec_level", None) or 2,
    )


class _PtsSmpDelegate:
    """Bridge SMP pairing user-interaction to the auto-pts BTP event/command stream.

    The default ``AutoAcceptDelegate`` returns passkey 000000 and never surfaces a
    displayed passkey, so PTS Legacy Passkey-Entry cases (SM/*/PKE) cannot run.
    This delegate:

    * ``display_passkey`` — emits BTP GAP PASSKEY_DISPLAY (ev 0x84) so auto-pts
      stores ``stack.gap.passkey.data`` and its WID handler can read it back to PTS.
      This is the path taken with io_cap=DisplayOnly (the bluez default we match).
    * ``get_passkey`` — input role: blocks until PTS supplies the passkey via
      BTP PASSKEY_ENTRY_REPLY (op 0x13) → ``IutActions.submit_passkey``.
    * ``confirm_pairing``/``confirm_passkey``/``confirm_numeric`` — auto-accept
      (no local UI to ask). ``display_passkey`` doubles as the Numeric
      Comparison display: with io_cap=KeyboardDisplay on both sides, SC selects
      Numeric Comparison and that is the only way the 6-digit value reaches
      auto-pts.
    """

    def __init__(self, gap_service, actions) -> None:
        self._gap = gap_service
        self._actions = actions

    async def display_passkey(self, peer_addr, passkey: int) -> None:
        to_hci = getattr(peer_addr, "to_hci", None)
        if callable(to_hci):
            raw = to_hci()                      # little-endian, matches auto-pts le_bytes_to_hex_str
        else:
            raw = getattr(peer_addr, "address", None) or getattr(peer_addr, "bytes", None) or b"\x00" * 6
        addr_type = getattr(peer_addr, "type", 0)
        addr_type = int(getattr(addr_type, "value", addr_type) or 0)
        self._gap.on_passkey_display(
            addr=bytes(raw)[:6].ljust(6, b"\x00"),
            addr_type=addr_type,
            passkey=int(passkey),
        )

    async def get_passkey(self, peer_addr) -> int:
        return await self._actions._await_passkey_entry()

    async def confirm_pairing(self, handle: int, io_cap: int) -> bool:
        return True

    async def confirm_passkey(self, peer_addr, passkey: int) -> bool:
        return True

    async def confirm_numeric(self, peer_addr, value: int) -> bool:
        return True


async def _pts_tester_main(stack, stop_event, *, listen: str, connect: str | None):
    logger = logging.getLogger(__name__)
    from pybluehost.pts.actions import IutActions
    from pybluehost.pts.btp import (
        BtpServiceRegistry, BtpTester, CoreService,
    )
    from pybluehost.pts.btp.services.gap import GapService
    from pybluehost.pts.btp.services.gatt import GattService
    from pybluehost.pts.btp.services.l2cap import LeCoCService
    from pybluehost.pts.btp.services.sdp import SdpService
    from pybluehost.pts.btp.services.rfcomm import RfcommService

    actions = IutActions(stack)
    # Offer LE Secure Connections to the peer. The IUT hardware (AX201, BT5.2)
    # is SC-capable; many GAP/SEC + SM cases have PTS require SC=1 and fail the
    # pairing with 0x0A (Invalid Parameters) if the IUT's AuthReq omits the SC
    # bit. Setting the flag makes the SMP responder advertise SC; pairing still
    # falls back to Legacy when the peer doesn't request SC (SC bit is ANDed),
    # so legacy PKE/JW cases are unaffected. (MITM is NOT forced here — the
    # responder mirrors the peer's requested MITM/SC bits, see
    # _smp_state._responder_recv_pairing_request.)
    stack.config.security.enable_secure_connections = True
    # Give the IUT bond storage so a bonding case that pairs → disconnects →
    # reconnects can re-establish encryption from the LTK stored during pairing
    # (PTS SM/GAP-BOND cases and SC cases like SM/*/SCJW verify this). Without
    # storage the LTK is dropped at pairing time ("no bond storage configured")
    # and the reconnect has nothing to encrypt with → re-pairing fails.
    # In-memory by default (not file): a fresh pts-tester is spawned per test
    # case, so each case starts with a clean bond slate and no cross-case
    # leakage. Cases that need the bond to outlive the case opt in via
    # PYBLUEHOST_PTS_BOND_STORE — see _make_bond_storage. The SMP manager reads
    # _bond_storage at pairing time and stack.encrypt reads config.bond_storage,
    # so set both to the same instance.
    _bond_storage = _make_bond_storage()
    stack.config.bond_storage = _bond_storage
    _smp_now = getattr(stack, "_smp", None)
    if _smp_now is not None:
        _smp_now._bond_storage = _bond_storage
    registry = BtpServiceRegistry()
    registry.register(CoreService(registry=registry))
    if connect is not None:
        tester = BtpTester(registry=registry, connect_to=_parse_host_port(connect, flag="--connect"))
    else:
        host, port = _parse_host_port(listen, flag="--listen")
        tester = BtpTester(registry=registry, host=host, port=port)
    gap = GapService(actions=actions, tester=tester)
    registry.register(gap)
    gatt = GattService(actions=actions, tester=tester)
    registry.register(gatt)
    l2cap = LeCoCService(actions=actions, tester=tester)
    registry.register(l2cap)
    registry.register(SdpService(actions=actions, tester=tester))
    rfcomm_svc = RfcommService(actions=actions, tester=tester)
    registry.register(rfcomm_svc)
    # Give the actions layer a back-reference so incoming RFCOMM DLCs can emit
    # Connected/Data events through this service.
    actions._rfcomm_btp = rfcomm_svc
    # Route SMP passkey display/entry through the BTP stream so PTS Legacy
    # Passkey-Entry cases work (default AutoAcceptDelegate would silently use 000000).
    smp = getattr(stack, "_smp", None)
    if smp is not None and hasattr(smp, "set_delegate"):
        smp.set_delegate(_PtsSmpDelegate(gap, actions))
    await tester.start()

    # Attach BTP notification/indication forwarding to each GATT-client ATT
    # bearer the moment it is created (stack hook fired by connect_gatt /
    # gatt_client_for_handle), so a secured indication PTS sends on a passive
    # reconnect — with no preceding BTP GATT command — is still caught
    # (PTS GAP/SEC/SEM BV-56..67).
    _conn_peers: dict[int, tuple[bytes, int]] = {}

    def _on_att_bearer(bearer, handle):
        peer_info = _conn_peers.get(handle)
        if peer_info is None:
            return
        peer_bytes, addr_type = peer_info
        gatt.attach_to_att_bearer(
            bearer, peer=peer_bytes, addr_type=addr_type, conn_handle=handle,
            is_encrypted=getattr(stack, "is_le_encrypted", None),
            encrypt_pending=getattr(stack, "is_le_encrypt_pending", None),
        )
    stack.on_att_client_bearer = _on_att_bearer

    # Hook stack connection events into GapService for DEVICE_CONNECTED/DISCONNECTED
    # and attach GATT notification listeners to new central connections.
    def _on_conn(ev):
        # "encrypted" = the link came up (pairing or bond-resume). Bond-resume
        # pairs nothing, so SEC_LEVEL_CHANGED would never reach auto-pts without
        # forwarding it here (GATT/SR/GAR/BV-11/12 EATT-listen WID depends on
        # the sec_level model). A pre-encryption indication is still dropped at
        # the GATT gate, not queued (GAP.TS step 9A.4/9B.4).
        if ev.state not in ("connected", "disconnected", "encrypted"):
            return
        peer = getattr(ev, "peer_address", None)
        if peer is None:
            return
        addr_type_attr = getattr(peer, "address_type", 0)
        addr_type = getattr(addr_type_attr, "value", addr_type_attr)
        # auto-pts parses DEVICE_CONNECTED addr with le_bytes_to_hex_str
        # (reverses bytes), so send HCI little-endian via to_hci() when available.
        to_hci = getattr(peer, "to_hci", None)
        if callable(to_hci):
            raw = to_hci()
        else:
            raw = getattr(peer, "address", None) or getattr(peer, "bytes", None)
        if raw is None:
            return
        peer_bytes = bytes(raw)[:6].ljust(6, b"\x00")
        if ev.state == "encrypted":
            _forward_sec_level(gap, ev, peer_bytes=peer_bytes, addr_type=int(addr_type))
            return
        if ev.state == "connected":
            _conn_peers[ev.handle] = (peer_bytes, int(addr_type))
            # Ensure a GATT-client bearer exists so a notification/indication PTS
            # sends without any BTP GATT command is caught (peripheral SEC/SEM,
            # central passive reconnect). Retries until the ATT channel is up;
            # for central links connect_gatt's bearer ultimately wins the mux.
            async def _ensure_bearer(handle):
                factory = getattr(actions, "gatt_client_for_handle", None)
                if not callable(factory):
                    return
                for _ in range(200):
                    if factory(handle) is not None:
                        return
                    await asyncio.sleep(0.01)
            asyncio.get_running_loop().create_task(_ensure_bearer(ev.handle))
        else:  # disconnected
            _conn_peers.pop(ev.handle, None)
        gap.on_connection_state_change(
            handle=ev.handle or 0,
            addr=peer_bytes,
            addr_type=int(addr_type),
            connected=(ev.state == "connected"),
            conn_params=getattr(stack, "_le_conn_params", {}).get(ev.handle),
        )
    stack.on_connection_event(_on_conn)

    # Bond lost (GAP/SEC/AUT/BV-21/22): the peer answered our encryption request
    # with "PIN or Key Missing", so the LTK it distributed is gone on its side.
    # auto-pts waits on stack.gap.bond_lost_ev_data, filled by BTP ev 0x8B.
    def _on_bond_lost(handle, peer):
        peer_info = _conn_peers.get(handle)
        if peer_info is not None:
            peer_bytes, addr_type = peer_info
        else:
            to_hci = getattr(peer, "to_hci", None)
            peer_bytes = bytes(to_hci())[:6] if callable(to_hci) else None
            addr_type = 0
        if peer_bytes is None:
            return
        gap.on_bond_lost(addr=peer_bytes, addr_type=int(addr_type))
    stack.on_bond_lost(_on_bond_lost)

    # Connection Subrating (GAP/CSUB): the Controller completes the procedure
    # asynchronously, so the LE Subrate Change event is what tells PTS the case
    # is done. auto-pts matches the address against its own LT address.
    def _on_subrate_change(handle, status, factor, latency, cont, timeout):
        peer_info = _conn_peers.get(handle)
        if peer_info is None:
            logger.warning(
                "Subrate Change for unknown handle 0x%04X; no addr to report", handle)
            return
        peer_bytes, addr_type = peer_info
        gap.on_subrate_change(
            addr=peer_bytes, addr_type=int(addr_type), status=status, handle=handle,
            subrate_factor=factor, peripheral_latency=latency,
            continuation_number=cont, supervision_timeout=timeout,
        )
    stack.on_subrate_change(_on_subrate_change)

    # Periodic advertising (GAP/PADV): route the LE Meta subevents the stack
    # fans into PeriodicAdvertising out as BTP events 0x8D-0x90.
    gap.wire_periodic_advertising()

    # Surface a peer-initiated Pairing Failed as a BTP PAIRING_FAILED event. A
    # responder (PTS-driven pairing) has no pair() waiter, so without this the
    # Upper Tester / auto-pts never learns the peer rejected the pairing — WID
    # 173 waits on stack.gap.pairing_failed_rcvd (SM/*/KDU/BI-02/03).
    def _on_pairing_failed(handle, peer, reason):
        peer_bytes, addr_type = _conn_peers.get(handle, (None, 0))
        if peer_bytes is None:
            to_hci = getattr(peer, "to_hci", None)
            raw = to_hci() if callable(to_hci) else getattr(peer, "address", None)
            if raw is None:
                return
            peer_bytes = bytes(raw)[:6].ljust(6, b"\x00")
            at = getattr(peer, "address_type", 0)
            addr_type = int(getattr(at, "value", at))
        gap.on_pairing_failed(addr=peer_bytes, addr_type=addr_type, reason=int(reason))

    _smp = getattr(stack, "_smp", None)
    if _smp is not None and hasattr(_smp, "on_pairing_failed"):
        _smp.on_pairing_failed(_on_pairing_failed)

    where = f"connecting out to auto-pts at {connect}" if connect is not None else f"listening on {listen}"
    logger.info("PyBlueHost BTP tester %s (Core + GAP + GATT + L2CAP)", where)
    try:
        await stop_event.wait()
    finally:
        await tester.stop()
