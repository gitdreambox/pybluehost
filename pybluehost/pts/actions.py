"""IUT action layer — primitives shared by Phase 1 REPL and Phase 2 BTP tester.

See design spec §4. Each primitive maps 1:1 to a Stack/GAP/SMP/SDP call;
`IutSession` tracks state (active connections + last_handle for handle-elision)
so MMI prompts like "do X on the current connection" work without re-specifying.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pybluehost.ble.gatt import GATTClient
    from pybluehost.core.address import BDAddress
    from pybluehost.stack import Stack


@dataclass
class ConnInfo:
    """One connection in the IUT's session table (out-going + incoming)."""

    handle: int
    peer: "BDAddress | None"
    transport: str  # "le" | "classic"
    gatt_client: "GATTClient | None" = None  # central side only


@dataclass
class IutSession:
    """Cross-command state of the REPL (or BTP tester) session."""

    connections: dict[int, ConnInfo] = field(default_factory=dict)
    last_handle: int | None = None
    # Retained after disconnect: BCST/BV-05 enables RPA advertising only after
    # its bonded preamble link has closed, and still needs that peer's IRK to
    # resolve the Lower Tester's SCAN_REQ address against the accept list.
    last_peer: "BDAddress | None" = None
    le_io_capability: int = 0x03  # NoInputNoOutput default
    classic_io_capability: int = 0x01  # DisplayYesNo default


# TGAP(private_addr_int) cadence the BTP path advertises to PTS as
# TSPX_iut_private_address_interval (see auto_pts_project/pybluehost_iut/gap.py).
PRIVATE_ADDRESS_ROTATION_S = 5.0

# Device Identity the PTS IUT uses for resolvable private addresses. The same
# value is published as TSPX_iut_device_IRK_for_resolvable_privacy_address_
# generation_procedure by auto_pts_project/pybluehost_iut/gap.py — PTS resolves
# our RPAs (and mints its directed TargetA) with it, so the two must not drift.
# All-sixteen-bytes-equal keeps PTS's hex byte-order parse irrelevant (any order
# yields the same key) while being NON-zero: the Intel controller treats an
# all-zero resolving-list Local_IRK as "no key" and silently skips both
# controller-generated RPAs (Own_Address_Type 0x02 fell back to identity) and
# directed-advertisement TargetA resolution (GAP/CONN/ACEP/BV-03 never matched).
# All-zero (the zephyr reference value) worked only while no controller-side
# resolution was needed.
PTS_IUT_IRK = b"\xAB" * 16


def _peer_from_wire(address_type: int, address: bytes) -> "BDAddress":
    """Build a BDAddress from a BTP (addr_type, 6 little-endian bytes) pair."""
    from pybluehost.core.address import AddressType, BDAddress

    return BDAddress.from_hci(bytes(address)[:6], type=AddressType(address_type))


class IutActions:
    """Drive PyBlueHost as a PTS IUT. Primitive set per design spec §4."""

    def __init__(self, stack: "Stack") -> None:
        self._stack = stack
        self._session = IutSession()
        # Legacy Passkey-Entry plumbing (BTP GAP PASSKEY_ENTRY_REPLY op 0x13):
        # the SMP "input" role awaits a user-supplied 6-digit passkey; PTS delivers
        # it via submit_passkey. _pending_passkey covers the case where PTS replies
        # before the state machine reaches the input-await step.
        self._passkey_entry_future: "asyncio.Future[int] | None" = None
        self._pending_passkey: int | None = None
        # GATT-client ATT bearers bound to EATT channels, per connection
        # handle (GATT/CL/GAR/BV-10 sends its second Read Multiple Variable
        # request over the EATT bearer).
        self._eatt_client_bearers: dict[int, list] = {}
        # Register handler for incoming connections
        self._stack.on_connection_event(self._on_connection_event)
        # Pin the local IRK AT STARTUP, before any pairing: the IRK we distribute
        # must match the RPA we later advertise (GAP/PRIV/CONN/BV-10).
        _smp = getattr(self._stack, "_smp", None)
        if _smp is not None and hasattr(_smp, "set_local_irk"):
            _smp.set_local_irk(PTS_IUT_IRK)

    @property
    def stack(self) -> "Stack":
        """The stack this IUT drives (bond storage / managers access)."""
        return self._stack

    @property
    def local_address(self) -> "BDAddress | None":
        """The IUT controller's own BD_ADDR (read at stack bring-up)."""
        return self._stack.local_address

    # ---- LE advertising / scanning ---------------------------------------

    async def advertise(
        self,
        *,
        adv_type: int | None = None,
        data: bytes | None = None,
        scan_rsp: bytes | None = None,
        peer: "BDAddress | None" = None,
        own_addr_type: int | None = None,
        filter_policy: int = 0x00,
    ) -> None:
        """Start BLE advertising.

        ``data``/``scan_rsp`` are raw serialized AD TLV bytes (accepted verbatim
        by ``BLEAdvertiser``); empty byte strings are treated as "not provided".
        ``peer`` targets directed advertising (ADV_DIRECT_IND); leave None for
        undirected.

        ``own_addr_type`` is auto-pts's OwnAddrType: 0 = identity (public),
        1 = resolvable private, 2 = non-resolvable private. The private
        variants mean "generate and advertise from a private address", which the
        controller does via a programmed random address (own addr type 0x01).
        """
        from pybluehost.ble.gap import AdvertisingConfig

        config = AdvertisingConfig()
        if adv_type is not None:
            config.adv_type = adv_type
        config.filter_policy = filter_policy & 0xFF
        if peer is not None:
            config.peer_address = peer
        if own_addr_type:
            # OwnAddrType: 1 = resolvable private, 2 = non-resolvable private.
            address = await self.program_private_address(
                resolvable=(own_addr_type == 1)
            )
            config.own_address_type = 0x01
            # program_private_address writes the global LE_Set_Random_Address,
            # but extended advertising sets source their "random" own address
            # from LE_Set_Advertising_Set_Random_Address — without this the set
            # keeps advertising with the controller default (public) address
            # and every private-address case (GAP/BROB/BCST/BV-03/04/05,
            # GAP/PRIV/*) times out because the Lower Tester can never
            # resolve/match the RPA.
            advertiser = self._stack.gap.ble_advertiser
            if hasattr(advertiser, "set_random_address"):
                await advertiser.set_random_address(address)
        else:
            privacy = getattr(self._stack.gap, "ble_privacy", None)
            current = getattr(privacy, "_current_address", None) if privacy else None
            if current:
                # A private address was programmed earlier (e.g. by SET_PRIVACY)
                # — keep advertising with it instead of the public address.
                config.own_address_type = 0x01
                advertiser = self._stack.gap.ble_advertiser
                if hasattr(advertiser, "set_random_address"):
                    await advertiser.set_random_address(current)
        await self._stack.gap.ble_advertiser.start(
            config,
            ad_data=data if data else None,
            scan_rsp_data=scan_rsp if scan_rsp else None,
        )

    async def program_private_address(self, *, resolvable: bool = True) -> bytes:
        """Generate + program a privacy address and turn on the controller bits.

        ``resolvable`` selects a resolvable private address (RPA, built from the
        stack's IRK so the peer can resolve it) versus a non-resolvable one
        (NRPA, used by the plain "private address" broadcast cases). Address
        resolution is enabled either way. Returns the programmed address.
        """
        privacy = getattr(self._stack.gap, "ble_privacy", None)
        if privacy is None:
            raise RuntimeError("privacy manager is not available on this stack")
        irk = None
        if resolvable:
            # The stack's own IRK — the one distributed to the peer during
            # pairing — so the peer can resolve the RPA we advertise. Pinned to
            # the value published as the TSPX_iut_device_IRK PIXIT.
            smp = getattr(self._stack, "_smp", None)
            if smp is not None and hasattr(smp, "set_local_irk"):
                smp.set_local_irk(PTS_IUT_IRK)
            irk = getattr(smp, "local_irk", None)
        await privacy.enable(irk)
        if resolvable and self._session.last_peer is not None:
            # BCST/BV-05 bonds over a public-identity preamble connection and
            # enables RPA advertising only after that link has disconnected.
            # pair()/connect() therefore ran while privacy was inactive and
            # skipped the resolving list. Now that RPA mode is really active,
            # program the retained peer before enabling resolution: in phase 2
            # the accept-listed LT identity only matches its SCAN_REQ RPA via
            # this entry, and without it no scan response ever goes on air.
            await self._prepare_rpa_resolution(self._session.last_peer)
        address = (
            privacy.generate_rpa(irk) if irk else privacy.generate_nrpa()
        )
        await privacy.set_random_address(address)
        # set_random_address already restores resolution when it was enabled
        # around the write; enabling it again here runs *after* advertising has
        # resumed, and the BE200 answers 0x0C to that redundant toggle
        # (GAP/BROB/BCST/BV-05, GAP/PRIV/*). Only switch it on when it is off.
        if not getattr(privacy, "_resolution_enabled", False):
            await privacy.set_address_resolution(True)
        # TGAP(private_addr_int): keep changing the address on the cadence we
        # advertise to PTS via TSPX_iut_private_address_interval.
        await privacy.start_rotation(PRIVATE_ADDRESS_ROTATION_S)
        return address

    async def prepare_auto_connection(self, peer_address: str) -> None:
        """GAP/CONN/ACEP BV-03/04 preamble: program the controller resolving
        list with the LT identity and initiate from a resolvable private
        address of our own.

        The LT advertises with an RPA, so the filter accept list (which holds
        the LT identity) can only match through the resolving list. The peer
        IRK comes from the preamble bond when one exists (the current PTS
        distributes a fresh random value); the legacy all-zero workspace value
        is only a no-bond fallback. The local RPA is built from the IRK
        published as TSPX_iut_device_IRK so the LT can resolve our initiator
        address, and is written BEFORE resolution is enabled — the controller
        answers LE_Set_Random_Address with Command Disallowed once resolution
        is on (GAP/BROB/BCST/BV-04 lesson).

        WID 400 normally runs after SET_PRIVACY has already programmed an RPA
        from that same IRK. Re-programming it would first require disabling
        address resolution, and the 2026-11 BE200 firmware answers 0x0C to
        both resolution toggles while that privacy state is live — every
        connect retry then fails and the initiator never comes up
        (GAP/CONN/ACEP/BV-03/04, GAP/PRIV/CONN/BV-11). Reuse an already
        programmed RPA and skip a redundant resolution-enable.
        """
        from pybluehost.core.address import BDAddress

        privacy = getattr(self._stack.gap, "ble_privacy", None)
        if privacy is None:
            raise RuntimeError("privacy manager is not available on this stack")
        # SET_PRIVACY starts host RPA rotation for advertising cases. An
        # outgoing connection must not race that timer: on the BE200 a rotation
        # during resolving-list setup / initiating makes the whole sequence
        # fail with 0x0C (ACEP BV-03/04 failed at 5 s intervals).
        await privacy.stop_rotation()
        local_irk = PTS_IUT_IRK
        smp = getattr(self._stack, "_smp", None)
        if smp is not None and hasattr(smp, "set_local_irk"):
            smp.set_local_irk(local_irk)
        current = getattr(privacy, "_current_address", None)
        current_irk = getattr(privacy, "_irk", None)
        if current is None or current_irk != local_irk:
            # Only write a new address while resolution is off; set_random_address
            # handles the disable/enable window for the normal BCST/BV-04 path.
            await privacy.set_random_address(privacy.generate_rpa(local_irk))
        identity = BDAddress.from_string(peer_address)
        peer_irk = bytes(16)
        storage = getattr(getattr(self._stack, "config", None), "bond_storage", None)
        if storage is not None:
            try:
                bond = await storage.load_bond(identity)
            except Exception:  # noqa: BLE001
                logger.debug("auto-connection: bond IRK lookup failed", exc_info=True)
            else:
                if bond is not None and getattr(bond, "irk", None):
                    # The current LT mints its RPA from the IRK distributed in
                    # the preamble pairing, not the legacy all-zero workspace
                    # value. A zero-IRK entry added here is sticky: connect()'s
                    # later bond-aware add of the same identity is rejected as
                    # a duplicate, leaving the accept list unable to match.
                    peer_irk = bytes(bond.irk)
        await privacy.add_to_resolving_list(
            identity.to_hci(), peer_irk, local_irk)
        if not getattr(privacy, "_resolution_enabled", False):
            await privacy.set_address_resolution(True)

    async def stop_advertising(self) -> None:
        """Stop any active BLE advertising. Idempotent."""
        await self._stack.gap.ble_advertiser.stop()

    # ---- Periodic advertising (BTP GAP 0x22-0x29, PTS GAP/PADV) -------------

    def _periodic_advertising(self):
        padv = getattr(self._stack.gap, "periodic_advertising", None)
        if padv is None:
            raise RuntimeError("periodic advertising is not available on this stack")
        return padv

    async def padv_configure(
        self, *, include_tx_power: bool, interval_min: int, interval_max: int,
    ) -> None:
        await self._periodic_advertising().configure(
            include_tx_power=include_tx_power,
            interval_min=interval_min,
            interval_max=interval_max,
        )

    async def padv_start(self) -> None:
        await self._periodic_advertising().start()

    async def padv_stop(self) -> None:
        await self._periodic_advertising().stop()

    async def padv_set_data(self, data: bytes) -> None:
        await self._periodic_advertising().set_data(bytes(data))

    async def padv_create_sync(
        self, *, adv_sid: int, skip: int, sync_timeout: int, flags: int,
        address_type: int, address: bytes,
    ) -> None:
        await self._periodic_advertising().create_sync(
            adv_sid=adv_sid, skip=skip, sync_timeout=sync_timeout, flags=flags,
            address_type=address_type, address=bytes(address),
        )

    async def padv_sync_transfer_recv(
        self, *, skip: int, sync_timeout: int, flags: int,
        address_type: int, address: bytes,
    ) -> None:
        """Ask the controller to accept a sync transferred by ``address`` on
        the next connection, then remember the peer so a later
        SYNC_TRANSFER_START can target it."""
        padv = self._periodic_advertising()
        peer = _peer_from_wire(address_type, address)
        # The HCI command is per-connection: the controller applies the transfer
        # parameters to the link the Lower Tester will send LL_PERIODIC_SYNC_IND
        # on, so the handle has to come from the live session, not be assumed.
        handle = next(
            (h for h, c in self._session.connections.items() if c.peer == peer),
            None,
        )
        if handle is None:
            raise ValueError(f"PADV_SYNC_TRANSFER_RECV: no connection to {peer}")
        # BTP Flags bit 0 = "Reports Disabled" (doc/btp_gap.txt opcode 0x29).
        # The controller's Mode field selects the same thing directly
        # (§7.8.91): 0x01 = sync but HCI_LE_Periodic_Advertising_Report
        # disabled, 0x02 = sync with reports enabled. WID 307 sends flags=1 and
        # WID 308 sends flags=0, so hardcoding either one fails the other case.
        mode = 0x01 if flags & 0x01 else 0x02
        await padv.set_sync_transfer_parameters(
            conn_handle=handle, mode=mode, skip=skip, sync_timeout=sync_timeout,
        )
        self._padv_transfer_peer = peer

    async def padv_sync_transfer_set_info(
        self, *, address_type: int, address: bytes, service_data: int,
    ) -> None:
        """Send our periodic advertising to a connected peer (§7.8.90).

        GAP.TS §4.7.8.4.2 step 4 has the IUT *perform* the Periodic Advertising
        Synchronization Transfer, and the verdict is the Lower Tester receiving
        that synchronization information — so this WID is the whole point of
        PADV/PAST and cannot be a bookkeeping no-op. The three neighbouring HCI
        commands are all the sink or re-transfer direction and put nothing on
        air the first time; only LE_Periodic_Advertising_Set_Info_Transfer does.
        """
        padv = self._periodic_advertising()
        peer = _peer_from_wire(address_type, address)
        # Per-connection command: the transfer rides the LE link the Lower
        # Tester opened for the case, so the handle comes from the live session
        # (same lookup as padv_sync_transfer_recv).
        handle = next(
            (h for h, c in self._session.connections.items()
             if c.transport == "le" and c.peer == peer),
            None,
        )
        if handle is None:
            raise ValueError(f"PADV_SYNC_TRANSFER_SET_INFO: no LE connection to {peer}")
        await padv.set_info_transfer(
            conn_handle=handle, service_data=service_data,
        )
        # Keep the (service data, peer) pair: BTP 0x28 re-transfers an existing
        # Sync_Handle, which is a different command targeting the same peer.
        self._padv_transfer_info = (service_data, peer)

    async def padv_sync_transfer_start(self) -> None:
        """Transfer our current periodic sync to the remembered peer."""
        from pybluehost.core.address import BDAddress

        padv = self._periodic_advertising()
        info = getattr(self, "_padv_transfer_info", None)
        sync = padv.sync
        if info is None or sync is None:
            raise RuntimeError(
                "SYNC_TRANSFER_START without a remembered peer or an active sync"
            )
        service_data, peer = info
        handle = next(
            (h for h, c in self._session.connections.items()
             if c.transport == "le" and c.peer == peer),
            None,
        )
        if handle is None:
            raise ValueError(f"SYNC_TRANSFER_START: no LE connection to {peer}")
        await padv.sync_transfer(
            conn_handle=handle, service_data=service_data,
            sync_handle=sync.sync_handle,
        )

    # ---- Broadcast Isochronous Group (BTP GAP 0x2d/0x2e, PTS GAP/BIS) ------

    def _iso_broadcast(self):
        iso = getattr(self._stack.gap, "iso_broadcast", None)
        if iso is None:
            raise RuntimeError(
                "isochronous broadcast is not available on this stack"
            )
        return iso

    async def create_big(
        self,
        *,
        bis_id: int = 0,
        num_bis: int = 1,
        sdu_interval_us: int = 10000,
        max_transport_latency_ms: int = 20,
        rtn: int = 2,
        phy: int = 0x02,
        packing: int = 0,
        framing: int = 0,
        encryption: int = 0,
        broadcast_code: bytes | None = None,
    ) -> dict[int, int]:
        """Create a BIG hanging off the periodic advertising set.

        Defaults mirror the upstream ``hdl_wid_300`` call shape
        (``gap_create_big(0, 1, 10000, 20, ...)`` plus auto-pts's rtn=2 /
        PHY_2M defaults). ``phy`` is the HCI bitmask value verbatim —
        auto-pts's BTP_GAP_CMD_CREATE_BIG_PHY_* already are (0x01/0x02/0x04).
        """
        from pybluehost.ble.gap import PERIODIC_ADV_HANDLE

        return await self._iso_broadcast().create_big(
            big_handle=bis_id,
            adv_handle=PERIODIC_ADV_HANDLE,
            num_bis=num_bis,
            sdu_interval_us=sdu_interval_us,
            max_transport_latency_ms=max_transport_latency_ms,
            rtn=rtn,
            phy=phy,
            packing=packing,
            framing=framing,
            encryption=encryption,
            broadcast_code=broadcast_code,
        )

    async def bis_broadcast(self, bis_id: int, data: bytes) -> None:
        """Send one ISO SDU on a BIS of the BIG created earlier.

        One BTP command = one SDU: upstream's ``hdl_wid_356`` loops
        ``gap_bis_broadcast`` itself until "more than 3 packets" are on air,
        so the IUT must not multiply.
        """
        await self._iso_broadcast().bis_broadcast(bis_id, bytes(data))

    async def scan(self, *, active: bool = False, on_result: callable | None = None) -> None:
        """Start BLE scanning.

        ``active`` (BTP START_DISCOVERY bit 2) must reach the controller: an
        active scan sends SCAN_REQs so scan-response data is collected — the
        OBSV cases verify BOTH the advertising report and the scan response
        per device (auto-pts check_scan_report_and_response). A passive scan
        never sees the response half (GAP/BROB/OBSV INDCSV).
        """
        from pybluehost.ble.gap import ScanConfig
        if on_result is not None:
            self._stack.gap.ble_scanner.on_result(on_result)
        # GAP/BROB/OBSV/BV-05/06 have the IUT perform the observation procedure
        # with a private address: a host-programmed random address is only used
        # when Own_Address_Type says random, otherwise the controller scans from
        # the public address and PTS never sees the private one.
        privacy = getattr(self._stack.gap, "ble_privacy", None)
        own_addr_type = 0x01 if getattr(privacy, "enabled", False) else 0x00
        # Duplicate filtering must be OFF: it de-duplicates by address, so the
        # scan response that follows a device's advertising report is suppressed
        # as a repeat and the two halves can never be merged. On air that showed
        # as every report having rsp=0 (GAP/BROB/OBSV/BV-05/06, whose WID checks
        # the scan response payload).
        await self._stack.gap.ble_scanner.start(ScanConfig(
            active=active, own_address_type=own_addr_type, filter_duplicates=False,
        ))

    async def program_filter_accept_list(self, entries: "list[tuple[int, bytes]]") -> None:
        """Program the controller's LE filter accept list (GAP/CONN/ACEP).

        BTP SET_FILTER_ACCEPT_LIST only told us which peers PTS wanted in the
        list; the controller also needs them, because the Auto Connection
        Establishment procedure makes it the *controller* that matches
        advertisers against the list (Initiator_Filter_Policy 0x01).
        ``entries`` are ``(address_type, address_bytes)`` as auto-pts sends
        them — the six address bytes in HCI (little-endian) order.
        """
        from pybluehost.core.address import AddressType, BDAddress

        white_list = getattr(self._stack.gap, "whitelist", None)
        if white_list is None:
            return
        await white_list.clear()
        for addr_type, addr_bytes in entries:
            try:
                peer = BDAddress.from_hci(bytes(addr_bytes)[:6],
                                          type=AddressType(int(addr_type)))
            except Exception:
                logger.warning("filter accept list: bad entry %r", addr_bytes)
                continue
            try:
                await white_list.add(peer, address_type=int(addr_type))
            except Exception:
                logger.exception("filter accept list: add %s failed", peer)

    async def stop_scan(self) -> None:
        """Stop any active BLE scanning. Idempotent."""
        await self._stack.gap.ble_scanner.stop()

    # ---- Classic connectability / discoverability -----------------------

    async def set_connectable(self, enabled: bool = True) -> None:
        """Enable/disable Classic page scan (connectable mode).

        Required by PTS MMI prompts like "Place the IUT in connectable mode"
        (e.g. Classic L2CAP/SDP/RFCOMM test cases where the Lower Tester pages
        the IUT). Incoming ACL connection requests are auto-accepted by the
        stack once page scan is on.
        """
        disc = self._stack.gap.classic_discoverability
        if disc is None:
            raise RuntimeError("Classic GAP not available on this stack")
        await disc.set_connectable(enabled)

    async def set_discoverable(self, enabled: bool = True) -> None:
        """Enable/disable Classic inquiry scan (discoverable mode).

        Required by PTS MMI prompts like "Place the IUT in discoverable mode".
        """
        disc = self._stack.gap.classic_discoverability
        if disc is None:
            raise RuntimeError("Classic GAP not available on this stack")
        await disc.set_discoverable(enabled)

    # ---- Connection management ------------------------------------------

    async def connect(
        self, addr: "BDAddress", *, le: bool = True, filter_policy: int = 0x00,
        own_address_type: int | None = None,
    ) -> int:
        """Connect to a peer. Returns connection handle.

        ``filter_policy`` 0x01 is the Auto Connection Establishment procedure
        (GAP/CONN/ACEP): the controller ignores ``addr`` and connects to
        whatever advertises matching its filter accept list, which the caller
        must have programmed with ``program_filter_accept_list``.

        The CSR8510 IUT→PTS link is flaky: HCI reports LE Connection Complete
        (assigning a handle) then immediately drops with reason 0x3E (Connection
        Failed to be Established) roughly half the time. connect_gatt returns on
        the optimistic complete, so detect the drop via the ATT fixed channel
        disappearing and retry a few times.
        """
        privacy = getattr(self._stack.gap, "ble_privacy", None)
        stop_rotation = getattr(privacy, "stop_rotation", None)
        if stop_rotation is not None:
            # Host RPA rotation belongs to advertising. Stop it for the whole
            # outgoing-connect transaction, including retries and the failure
            # air-peek; otherwise its 5 s timer can rewrite the address while
            # the controller is initiating (BE200 -> 0x0C).
            await stop_rotation()
        await self._prepare_rpa_resolution(addr)
        if le:
            from pybluehost.l2cap.constants import CID_ATT

            client = None
            handle = None
            last_exc: Exception | None = None
            # Time-budgeted retry: auto-pts `send_wait_rsp` times out the GAP CONNECT
            # BTP response at 20s, so the whole retry loop must resolve (success or
            # failure) well under that. Fast 0x3E drops (~1-2s each) allow many
            # attempts; a hung attempt (no LE Connection Complete) eats up to 6s.
            # Cap the total at ~16s so auto-pts always gets a definitive response
            # (PASS on success, BTP_ERROR on exhaustion) instead of a BTP TIMEOUT.
            import time as _time

            deadline = _time.monotonic() + 16.0
            attempt = 0
            while True:
                # Clear any pending initiate before (re)trying — a prior 0x3E drop
                # or timed-out attempt can leave the controller mid-initiate, which
                # makes the next LE_Create_Connection Command Disallowed.
                if attempt:
                    await self._cancel_pending_le_connect()
                remaining = deadline - _time.monotonic()
                if remaining <= 2.0:
                    break
                try:
                    connect_kwargs: dict = {
                        "timeout": min(6.0, remaining - 1.0),
                        "filter_policy": filter_policy,
                    }
                    if own_address_type is not None:
                        connect_kwargs["own_address_type"] = own_address_type
                    client = await self._stack.connect_gatt(addr, **connect_kwargs)
                except Exception as exc:  # connect timed out / rejected
                    last_exc = exc
                    attempt += 1
                    continue
                handle = client.connection_handle
                # Settle window: let an immediate 0x3E drop manifest.
                await asyncio.sleep(0.4)
                if self._stack.l2cap.get_fixed_channel(handle, CID_ATT) is not None:
                    break  # link survived
                client = None
                handle = None
                attempt += 1
            if client is None or handle is None:
                # The last attempt timed out with the create still pending in
                # the controller (connect_gatt cancels only its waiter); a scan
                # started while initiating answers 0x0C.
                await self._cancel_pending_le_connect()
                await self._peek_air_after_connect_failure(addr)
                raise RuntimeError(
                    f"LE connection to {addr} failed to establish"
                    + (f": {last_exc}" if last_exc else " (link dropped 0x3E, retries exhausted)")
                )
            conn = ConnInfo(handle=handle, peer=addr, transport="le", gatt_client=client)
        else:
            handle = await self._stack.connect_classic(addr)
            conn = ConnInfo(handle=handle, peer=addr, transport="classic", gatt_client=None)
        self._session.connections[handle] = conn
        self._session.last_handle = handle
        self._session.last_peer = addr
        return handle

    async def _prepare_rpa_resolution(self, addr: "BDAddress") -> None:
        """Program the controller resolving list from a stored bond so
        that LE_Create_Connection to a peer identity address matches its on-air
        RPA (GAP/PRIV/CONN/BV-11: PTS re-advertises under a rotated RPA
        after bonding and expects the IUT to resolve + reconnect). """
        try:
            storage = getattr(self._stack.config, "bond_storage", None)
            privacy = getattr(self._stack.gap, "ble_privacy", None)
            if storage is None or privacy is None:
                logger.debug("RPA resolution: no storage/privacy (%s/%s)",
                             storage is not None, privacy is not None)
                return
            # Only program controller address resolution while privacy is
            # actually active. GAP/SEC/SEM/BV-56..67 reconnect to the Lower
            # Tester's *public* identity after bonding; leaving controller
            # resolution on there makes the 2026-10 BE200 initiator never
            # complete (the connection-side twin of the scan-side report drop
            # documented in GapService._maybe_disable_controller_resolution).
            # The privacy cases (GAP/PRIV/CONN, GAP/DISC/RPA) reach here only
            # after SET_PRIVACY has put privacy.enabled True.
            if not getattr(privacy, "enabled", False):
                logger.debug(
                    "RPA resolution: privacy inactive — leaving controller resolution off")
                return
            bond = await storage.load_bond(addr)
            if bond is None or not getattr(bond, "irk", None):
                logger.debug("RPA resolution: no bond/irk for %s", addr)
                return
            smp = getattr(self._stack, "_smp", None)
            local_irk = smp.local_irk if smp is not None else bytes(16)
            logger.debug("RPA resolution: adding peer %s irk=%s",
                         bond.peer_address, bond.irk.hex())
            await privacy.add_to_resolving_list(
                bond.peer_address.to_hci(), bond.irk, local_irk,
            )
            await privacy.set_address_resolution(True)
        except Exception:  # noqa: BLE001
            logger.exception("RPA resolution setup failed; plain connect continues")

    async def peer_identity(self, peer: "BDAddress | None") -> "BDAddress | None":
        """The identity address behind a peer that connected under its RPA.

        With privacy enabled the Lower Tester connects from its own resolvable
        private address, so the session table holds the RPA while auto-pts
        still addresses it by the identity it knows (TSPX_peer_addr). Matching
        an address-keyed BTP command (GAP/PRIV/CONN/BV-10's disconnect on the
        LT identity) needs the stored bond's IRK to resolve the RPA back.
        """
        if peer is None:
            return None
        loader = getattr(self._stack, "_load_bond_for_peer", None)
        if loader is None:
            return None
        try:
            bond = await loader(peer)
        except Exception:  # noqa: BLE001
            logger.debug("peer identity resolution failed for %s", peer, exc_info=True)
            return None
        return getattr(bond, "peer_address", None)

    async def _peek_air_after_connect_failure(self, addr) -> None:
        """Env-gated (PYBLUEHOST_DEBUG_CONNECT_SCAN) 2s passive scan after the
        connect retries exhaust, logging every advertising report.

        The initiator's internal matching is invisible in the HCI log — a
        create that never completes looks identical for "peer not advertising"
        and "peer advertising under an address the initiator failed to match"
        (GAP/SEC/SEM/BV-45's post-bond reconnect). The peek separates them:
        nothing on air vs reports with a different address type.
        """
        import os

        if not os.environ.get("PYBLUEHOST_DEBUG_CONNECT_SCAN"):
            return
        try:
            reports: list[str] = []

            def _on_report(r) -> None:
                peer = getattr(r, "address", None)
                reports.append(
                    f"addr={getattr(peer, 'address', '?')} type={getattr(peer, 'type', '?')} "
                    f"connectable={getattr(r, 'connectable', '?')} rssi={getattr(r, 'rssi', '?')}"
                )

            await self.scan(active=False, on_result=_on_report)
            await asyncio.sleep(2.0)
            await self.stop_scan()
            for line in reports:
                logger.warning("CONNECT-FAIL AIR PEEK: %s", line)
            if not reports:
                logger.warning(
                    "CONNECT-FAIL AIR PEEK: nothing on air in 2s while initiating to %s",
                    addr,
                )
        except Exception:  # noqa: BLE001
            logger.exception("connect-fail air peek failed")

    async def _cancel_pending_le_connect(self) -> None:
        """Best-effort LE Create Connection cancel between connect retries.

        A timed-out initiate can leave the controller in the initiating state,
        which would make the next LE_Create_Connection Command Disallowed. A
        0x3E drop also leaves the CSR8510 initiator needing recovery time before
        the next attempt — too short a gap and the retries drop 0x3E repeatedly.
        """
        try:
            mgr = getattr(self._stack.gap, "ble_connections", None)
            if mgr is not None and hasattr(mgr, "cancel_connect"):
                await mgr.cancel_connect()
        except Exception:
            pass
        await asyncio.sleep(0.6)

    async def disconnect(self, handle: int | None = None) -> None:
        """Disconnect a connection. If handle=None, use last_handle."""
        if handle is None:
            handle = self._session.last_handle
        if handle is None:
            raise ValueError("no active connection; specify <handle>")
        conn = self._session.connections.get(handle)
        if conn is None:
            raise ValueError(f"unknown handle 0x{handle:04X}")
        # Route via the per-transport connection manager: the GAP facade has no
        # disconnect of its own (it lives on BLE/ClassicConnectionManager).
        if conn.transport == "classic":
            await self._stack.gap.classic_connections.disconnect(handle)
        else:
            await self._stack.gap.ble_connections.disconnect(handle)
        # Cleanup happens via on_connection_event handler asynchronously

    # ---- Pairing / encryption -------------------------------------------

    async def pair(
        self, handle: int | None = None, *, io_cap: str | None = None, mitm: bool = False
    ) -> None:
        """Initiate pairing on a connection."""
        target = handle if handle is not None else self._session.last_handle
        if target is None:
            raise ValueError("no active connection; specify <handle>")
        if io_cap is not None:
            self.set_io_cap(io_cap)
        if mitm:
            self._stack.config.security.auth_requirements |= 0x04  # MITM bit
            self._stack.config.security.mitm_required = True
        await self._stack.pair(target)
        # After bonding, program the controller resolving list so a later scan /
        # reconnect resolves the peer's RPA to its identity (GAP/DISC/RPA/BV-01,
        # PRIV/CONN/BV-10). connect() runs before the bond exists, so this is the
        # first point the peer's IRK is available.
        conn = self._session.connections.get(target)
        peer = getattr(conn, "peer", None) if conn is not None else None
        if peer is not None:
            await self._prepare_rpa_resolution(peer)

    async def encrypt(self, handle: int | None = None) -> None:
        """Enable encryption on a connection."""
        target = handle if handle is not None else self._session.last_handle
        if target is None:
            raise ValueError("no active connection; specify <handle>")
        conn = self._session.connections.get(target)
        if conn is not None and conn.transport == "classic":
            await self._stack.enable_classic_encryption(target)
        else:
            await self._stack.encrypt(target)

    _IO_CAP_NAMES = {
        "DisplayOnly": 0x00,
        "DisplayYesNo": 0x01,
        "KeyboardOnly": 0x02,
        "NoInputNoOutput": 0x03,
        "KeyboardDisplay": 0x04,
    }

    def set_io_cap(self, cap: str) -> None:
        """Set IO capability for next pairing."""
        if cap not in self._IO_CAP_NAMES:
            raise ValueError(
                f"unknown io_cap '{cap}'; choose one of {list(self._IO_CAP_NAMES.keys())}"
            )
        value = self._IO_CAP_NAMES[cap]
        self._session.le_io_capability = value
        self._stack.config.security.io_capability = value
        # Propagate to the live SMP manager — _initiator_send_pairing_request reads
        # ctx.local_io_caps <- smp._local_io_caps (set at construction). Without this
        # the on-air Pairing Request keeps the construction-time io_cap (NoInputNoOutput)
        # and BTP SET_IO_CAP has no effect, so passkey-capable models never engage.
        smp = getattr(self._stack, "_smp", None)
        if smp is not None:
            from pybluehost.core.types import IOCapability

            smp._local_io_caps = IOCapability(value)

    def set_bondable(self, enabled: bool) -> None:
        """Set the SMP bonding flag for subsequent pairing (BTP GAP SET_BONDABLE).

        PTS SM tests toggle this per-case (e.g. SM/CEN/JW/BV-01-C requires the
        Pairing Request AuthReq Bonding Flags = 0x00). It must reach the SMP
        layer — the GAP settings bitmap alone does not change the Pairing
        Request we put on air.
        """
        smp = getattr(self._stack, "_smp", None)
        if smp is not None and hasattr(smp, "set_bondable"):
            smp.set_bondable(enabled)

    def set_mitm(self, enabled: bool) -> None:
        """Set the MITM requirement for subsequent pairing (BTP GAP SET_MITM)."""
        self._stack.config.security.mitm_required = enabled

    def set_oob_legacy_data(self, oob_tk: bytes) -> None:
        """Provision the 16-byte legacy OOB TK (BTP GAP OOB_LEGACY_SET_DATA 0x18).

        PTS SM/*/OOB tests generate the OOB data and push it here; it must reach
        the SMP layer so the pairing feature exchange advertises oob_data_flag=1
        and the legacy path uses it as the TK.
        """
        smp = getattr(self._stack, "_smp", None)
        if smp is not None and hasattr(smp, "set_oob_legacy_data"):
            smp.set_oob_legacy_data(oob_tk)

    def get_oob_sc_local_data(self) -> tuple[bytes, bytes]:
        """Return the local SC OOB ``(rand, conf)`` (BTP GAP OOB_SC_GET_LOCAL_DATA 0x19).

        PTS SM/*/SCOB tests read this (WID 147 returns conf, WID 148 returns
        rand) and hand it to the Lower Tester as the IUT's out-of-band block.
        """
        smp = getattr(self._stack, "_smp", None)
        if smp is None or not hasattr(smp, "get_oob_sc_local_data"):
            return bytes(16), bytes(16)
        return smp.get_oob_sc_local_data()

    def set_oob_sc_remote_data(self, rand: bytes, conf: bytes) -> None:
        """Store the peer's SC OOB ``(rand, conf)`` (BTP GAP OOB_SC_SET_REMOTE_DATA 0x1a).

        PTS SM/*/SCOB tests push the Lower Tester's OOB block here (WID 149) so
        the IUT can verify the peer's public key and use its OOB random in f6.
        """
        smp = getattr(self._stack, "_smp", None)
        if smp is not None and hasattr(smp, "set_oob_sc_remote_data"):
            smp.set_oob_sc_remote_data(rand, conf)

    async def unpair(self, addr: "BDAddress") -> None:
        """BTP GAP UNPAIR (op 0x12): remove the bond with the given peer.

        PTS GAP/BOND tests drive WID 135 ("remove the bond") here. Delete the
        peer's bond from the stack's bond storage so the next connection to it
        is treated as unbonded. Idempotent — unpairing an unknown peer is a
        no-op (``delete_bond`` pops with a default).
        """
        seen: set[int] = set()
        storages = [
            getattr(self._stack.config, "bond_storage", None),
            getattr(getattr(self._stack, "_smp", None), "_bond_storage", None),
        ]
        for storage in storages:
            if storage is None or id(storage) in seen:
                continue
            seen.add(id(storage))
            delete = getattr(storage, "delete_bond", None)
            if delete is not None:
                await delete(addr)

    async def conn_param_update(self, addr_bytes: bytes, params: bytes) -> None:
        """BTP GAP CONN_PARAM_UPDATE (op 0x16): change LE connection parameters.

        ``addr_bytes`` is the peer address in HCI little-endian order; ``params``
        is itvl_min+itvl_max+latency+supervision_timeout (4x u16 LE, raw HCI
        units — the same units we reported in DEVICE_CONNECTED, echoed back by
        auto-pts). Resolve the LE connection handle for the peer, then pick the
        procedure by our LE role:

        - **Central** — HCI LE_Connection_Update (the LL Connection Parameters
          Request Procedure). PTS GAP/CONN/CPUP/BV-06/10.
        - **Peripheral** — the LL procedure is central-only, so the update must
          travel on the L2CAP signalling channel as a Connection Parameter
          Update Request (0x12). PTS L2CAP/LE/CPU/BV-01-C asserts exactly that.

        No-op if the peer has no LE connection.
        """
        import struct

        from pybluehost.core.address import BDAddress

        if len(params) < 8:
            raise ValueError(f"CONN_PARAM_UPDATE: expected 8 param bytes, got {len(params)}")
        itvl_min, itvl_max, latency, timeout = struct.unpack_from("<HHHH", params, 0)
        peer = BDAddress.from_hci(bytes(addr_bytes))
        handle = next(
            (h for h, c in self._session.connections.items()
             if c.transport == "le" and c.peer == peer),
            None,
        )
        if handle is None:
            logger.warning(
                "CONN_PARAM_UPDATE: no LE connection to %s; connections=%s",
                peer,
                {h: (c.transport, str(c.peer)) for h, c in self._session.connections.items()},
            )
            raise ValueError(f"CONN_PARAM_UPDATE: no LE connection to {peer}")

        l2cap = self._stack.l2cap
        if l2cap.le_role(handle) == 0x01:
            result = await l2cap.request_le_conn_param_update(
                handle=handle,
                itvl_min=itvl_min,
                itvl_max=itvl_max,
                latency=latency,
                timeout=timeout,
            )
            logger.debug("CONN_PARAM_UPDATE: periph L2CAP 0x12 -> result=0x%04X", result)
            return

        await self._stack.gap.ble_connections.connection_update(
            handle, itvl_min, itvl_max, latency, timeout
        )

    async def subrate_request(self, addr_bytes: bytes, params: bytes) -> None:
        """BTP GAP SUBRATE_REQUEST (op 0x2b): start the Connection Subrating procedure.

        ``addr_bytes`` is the peer address in HCI little-endian order; ``params``
        is Subrate_Min+Subrate_Max+Max_Latency+Continuation_Number+
        Supervision_Timeout (5x u16 LE, raw HCI units). The single HCI command
        LE_Subrate_Request serves both GAP/CSUB cases — the Controller picks the
        direction from our link-layer role. The outcome is asynchronous: the
        Controller answers with Command Status now and an LE Subrate Change
        event when the peer has answered, which the Stack forwards to
        ``on_subrate_change`` listeners (BTP event 0x92).

        No-op if the peer has no LE connection.
        """
        import struct

        from pybluehost.core.address import BDAddress

        if len(params) < 10:
            raise ValueError(f"SUBRATE_REQUEST: expected 10 param bytes, got {len(params)}")
        subrate_min, subrate_max, latency, cont, timeout = struct.unpack_from("<HHHHH", params, 0)
        peer = BDAddress.from_hci(bytes(addr_bytes))
        handle = next(
            (h for h, c in self._session.connections.items()
             if c.transport == "le" and c.peer == peer),
            None,
        )
        if handle is None:
            logger.warning(
                "SUBRATE_REQUEST: no LE connection to %s; connections=%s",
                peer,
                {h: (c.transport, str(c.peer)) for h, c in self._session.connections.items()},
            )
            raise ValueError(f"SUBRATE_REQUEST: no LE connection to {peer}")

        await self._stack.gap.ble_connections.subrate_request(
            handle,
            subrate_min=subrate_min,
            subrate_max=subrate_max,
            max_latency=latency,
            continuation_number=cont,
            supervision_timeout=timeout,
        )

    async def submit_passkey(self, passkey: int) -> None:
        """BTP GAP PASSKEY_ENTRY_REPLY (op 0x13): deliver the passkey PTS asked us to enter.

        Completes the future the SMP "input" role is awaiting (see
        ``_await_passkey_entry``); if the state machine has not reached that step
        yet, the value is stashed and returned on the next call.
        """
        passkey = int(passkey)
        fut = self._passkey_entry_future
        if fut is not None and not fut.done():
            fut.set_result(passkey)
        else:
            self._pending_passkey = passkey

    async def confirm_passkey(self, match: bool) -> None:
        """BTP GAP PASSKEY_CONFIRM_REPLY (op 0x14).

        Legacy pairing has no passkey-confirm step (that reply exists for SC
        Numeric Comparison, which CSR8510/BT4.0 cannot run). The Display-role
        passkey we surface is validated by PTS itself, so this is a no-op ack.
        """

    async def _await_passkey_entry(self, timeout: float = 30.0) -> int:
        """SMP delegate hook (input role): block until PTS supplies the passkey.

        Returns a value pre-supplied via :meth:`submit_passkey` if one arrived
        before the state machine asked; otherwise waits on a fresh future.
        """
        if self._pending_passkey is not None:
            value, self._pending_passkey = self._pending_passkey, None
            return value
        loop = asyncio.get_running_loop()
        self._passkey_entry_future = loop.create_future()
        try:
            return await asyncio.wait_for(self._passkey_entry_future, timeout)
        finally:
            self._passkey_entry_future = None

    # ---- GATT server (peripheral role) ----------------------------------

    async def notify(self, char_handle: int, value: bytes, handle: int | None = None) -> None:
        """Send GATT notification."""
        target = handle if handle is not None else self._session.last_handle
        if target is None:
            raise ValueError("no active connection; specify <handle>")
        await self._stack.gatt_server.notify(char_handle, value, connections=[target])

    async def indicate(self, char_handle: int, value: bytes, handle: int | None = None) -> None:
        """Send GATT indication."""
        target = handle if handle is not None else self._session.last_handle
        if target is None:
            raise ValueError("no active connection; specify <handle>")
        await self._stack.gatt_server.indicate(char_handle, value, connection=target)

    # ---- GATT client (central role) ------------------------------------

    async def read(self, char_handle: int, handle: int | None = None) -> bytes:
        """Read a GATT characteristic (central role only)."""
        target = handle if handle is not None else self._session.last_handle
        if target is None:
            raise ValueError("no active connection; specify <handle>")
        conn = self._session.connections.get(target)
        if conn is None or conn.gatt_client is None:
            raise ValueError(f"handle 0x{target:04X} is not a central connection (no GATTClient)")
        return await conn.gatt_client.read_characteristic(char_handle)

    async def write(self, char_handle: int, value: bytes, handle: int | None = None) -> None:
        """Write a GATT characteristic (central role only)."""
        target = handle if handle is not None else self._session.last_handle
        if target is None:
            raise ValueError("no active connection; specify <handle>")
        conn = self._session.connections.get(target)
        if conn is None or conn.gatt_client is None:
            raise ValueError(f"handle 0x{target:04X} is not a central connection (no GATTClient)")
        await conn.gatt_client.write_characteristic(char_handle, value)

    # ---- Classic SDP / RFCOMM / L2CAP ----------------------------------

    async def sdp_browse(self, addr: "BDAddress", *, uuid: int | None = None) -> list:
        """Browse SDP on a peer."""
        if uuid is not None:
            return await self._stack.sdp.search(addr, uuid)
        return await self._stack.sdp.search_attributes(addr)

    async def rfcomm_open(self, addr: "BDAddress", channel: int) -> None:
        """Open RFCOMM channel to a peer."""
        # Ensure ACL exists
        existing_handle = None
        for h, c in self._session.connections.items():
            if c.peer == addr and c.transport == "classic":
                existing_handle = h
                break

        if existing_handle is None:
            handle = await self._stack.connect_classic(addr)
            self._session.connections[handle] = ConnInfo(
                handle=handle, peer=addr, transport="classic", gatt_client=None
            )
            self._session.last_handle = handle
        else:
            handle = existing_handle

        await self._stack.rfcomm.connect(handle, channel)

    async def l2cap_connect(self, addr: "BDAddress", psm: int) -> None:
        """Open L2CAP channel to a peer."""
        # Ensure ACL exists
        existing_handle = None
        for h, c in self._session.connections.items():
            if c.peer == addr:
                existing_handle = h
                break

        if existing_handle is None:
            handle = await self._stack.connect_classic(addr)
            self._session.connections[handle] = ConnInfo(
                handle=handle, peer=addr, transport="classic", gatt_client=None
            )
            self._session.last_handle = handle
        else:
            handle = existing_handle

        await self._stack.l2cap.connect(handle, psm)

    # ---- Session inspection ---------------------------------------------

    def status(self) -> IutSession:
        """Return current session snapshot."""
        return self._session

    # ---- Internal event handlers ----------------------------------------

    def gatt_client_for_handle(self, handle: int):
        """Return the GATT client for a connection, creating one lazily.

        Outgoing (central) connections get a GATTClient at ``connect_gatt``
        time; incoming (peripheral) connections are registered with
        ``gatt_client=None``. PTS security cases (GAP/SEC, GAP/BOND) have the
        IUT act as a GATT *client* toward PTS even when PTS initiated the
        connection (e.g. WID 227 "Write Request to handle 0x0007" to trigger
        authentication). Without this, ``_resolve_gatt_client`` returns None
        and every such BTP GATT op fails with BTP_STATUS_FAILED.
        """
        conn = self._session.connections.get(handle)
        if conn is None:
            return None
        if conn.gatt_client is not None:
            return conn.gatt_client
        from pybluehost.ble.att import ATTBearer
        from pybluehost.ble.gatt import GATTClient
        from pybluehost.l2cap.channel import install_att_channel_mux
        from pybluehost.l2cap.constants import CID_ATT

        channel = self._stack.l2cap.get_fixed_channel(handle, CID_ATT)
        if channel is None:
            return None
        bearer = ATTBearer(channel, mtu=getattr(channel, "mtu", 23))
        # Register into the ATT mux rather than set_events() so the GATT server
        # bound to the same channel (GAP/SEC cases act as both) keeps answering.
        install_att_channel_mux(channel)
        channel._att_client_handler = bearer._on_pdu
        setattr(channel, "_gatt_client_bound", True)
        hook = getattr(self._stack, "on_att_client_bearer", None)
        if callable(hook):
            try:
                hook(bearer, handle)
            except Exception:
                pass
        client = GATTClient(
            bearer,
            connection_handle=handle,
            on_insufficient_encryption=getattr(
                self._stack, "_on_gatt_insufficient_encryption", None),
        )
        conn.gatt_client = client
        return client

    def attach_eatt_client_bearer(self, handle: int, channel) -> None:
        """Bind a GATT-client ATT bearer to an EATT channel.

        Idempotent per channel. The channel's ATT mux routes responses (0x21)
        to the client bearer and requests to the server — the same split the
        ATT fixed channel uses (GAP/SEC). Idempotent because the server attach
        may already have installed the mux.
        """
        from pybluehost.ble.att import ATTBearer
        from pybluehost.l2cap.channel import install_att_channel_mux

        install_att_channel_mux(channel)
        bearer = ATTBearer(channel, mtu=getattr(channel, "mtu", 23))
        channel._att_client_handler = bearer._on_pdu
        self._eatt_client_bearers.setdefault(handle, []).append(bearer)

    def eatt_client_bearers_for_handle(self, handle: int) -> list:
        """Client bearers previously attached to this connection's EATT channels."""
        return list(self._eatt_client_bearers.get(handle, []))

    def _on_connection_event(self, event) -> None:
        """Handle incoming connections and disconnections."""
        # StackConnectionEvent shape: state, handle, reason, peer_address
        if event.state == "connected" and event.handle is not None:
            peer = getattr(event, "peer_address", None)
            if peer is not None:
                self._session.last_peer = peer
            if event.handle not in self._session.connections:
                # Incoming connection (peripheral side). LE Connection Complete
                # carries the peer address for both roles — record it so GATT
                # client resolution / SMP can find the peer (was hardcoded None).
                # Classic ACLs set transport="classic" at the source; LE sets
                # "le". A None here means the source didn't tag it — treat as LE
                # (never guess from the handle: LE handles can be >= 0x0100).
                transport = getattr(event, "transport", None) or "le"
                self._session.connections[event.handle] = ConnInfo(
                    handle=event.handle,
                    peer=peer,
                    transport=transport,
                    gatt_client=None,
                )
                self._session.last_handle = event.handle
        elif event.state == "disconnected" and event.handle is not None:
            self._session.connections.pop(event.handle, None)
            if self._session.last_handle == event.handle:
                self._session.last_handle = None

    # ---- BR/EDR SDP (BTP SDP service, PTS SDP/CL cases) ----------------------

    async def sdp_client_for(self, addr: bytes) -> object:
        """Return an SDPClient connected to the peer's PSM_SDP.

        Reuses an established Classic ACL (the case's WID 102 has already
        connected); otherwise connects first. The client is cached per peer so
        search/attribute transactions ride the same L2CAP channel.
        """
        from pybluehost.core.address import AddressType, BDAddress
        from pybluehost.l2cap.constants import PSM_SDP
        from pybluehost.classic.sdp import SDPClient

        target = BDAddress.from_hci(bytes(addr)[:6], type=AddressType.PUBLIC)
        cached = getattr(self, "_sdp_clients", None)
        if cached is None:
            cached = self._sdp_clients = {}
        key = bytes(addr)[:6]
        client = cached.get(key)
        if client is not None:
            return client

        stack = self._stack
        session = self.status()
        handle = None
        for h, info in session.connections.items():
            if getattr(info, "transport", "le") != "classic":
                continue
            peer = getattr(info, "peer", None)
            raw = getattr(peer, "to_hci", lambda: None)()
            if raw is not None and bytes(raw)[:6] == key:
                handle = h
                break
        if handle is None:
            handle = await stack.connect_classic(target)
        channel = await stack.l2cap.connect_classic_channel(handle=handle, psm=PSM_SDP)
        client = SDPClient(channel)
        cached[key] = client
        return client

    async def connect_classic(self, addr: "BDAddress") -> int:
        """Page a BR/EDR peer and return the ACL handle (BTP GAP CONNECT with
        the BR address type — SDP/RFCOMM cases, WID 102).

        PAGE_TIMEOUT is not fatal: in the RFCOMM "accept SLC" cases the Lower
        Tester pages the IUT at the same moment the WID handler pages it — our
        page loses the race but the incoming ACL still lands. Wait briefly for
        any classic connection and use it instead of surfacing the error."""
        try:
            return await self._stack.connect_classic(addr)
        except Exception:
            import asyncio
            for _ in range(80):  # ~8s for the peer's page to complete
                for h, info in self._session.connections.items():
                    if getattr(info, "transport", "le") == "classic":
                        return h
                await asyncio.sleep(0.1)
            raise

    async def inquire(self, *, on_result: callable | None = None) -> None:
        """Start Classic inquiry (BTP START_DISCOVERY with the BR/EDR bit).

        The ClassicDiscovery result carries an ExtendedInquiryResponse blob;
        on_result receives it as-is (the GAP service adapts it to BTP
        DEVICE_FOUND with the BR address type).
        """
        disc = self._stack.gap.classic_discovery
        if disc is None:
            raise RuntimeError("Classic inquiry not available on this stack")
        if on_result is not None:
            disc.on_result(on_result)
        await disc.start()

    # ---- BR/EDR RFCOMM (BTP RFCOMM service, PTS RFCOMM cases) ---------------

    def _classic_handle_for(self, addr: bytes) -> int | None:
        key = bytes(addr)[:6]
        session = self.status()
        for h, info in session.connections.items():
            if getattr(info, "transport", "le") != "classic":
                continue
            peer = getattr(info, "peer", None)
            raw = getattr(peer, "to_hci", lambda: None)()
            if raw is not None and bytes(raw)[:6] == key:
                return h
        return None

    def _rfcomm(self):
        rf = getattr(self._stack, "_rfcomm", None)
        if rf is None:
            raise RuntimeError("RFCOMM not available on this stack")
        return rf

    async def rfcomm_connect(self, addr: bytes, channel: int) -> tuple[object, int]:
        """Open a DLC to the peer's server channel; returns (channel, MTU).

        Reuses the established Classic ACL (paging a second one fails)."""
        from pybluehost.core.address import AddressType, BDAddress
        target = BDAddress.from_hci(bytes(addr)[:6], type=AddressType.PUBLIC)
        handle = self._classic_handle_for(addr)
        if handle is None:
            handle = await self._stack.connect_classic(target)
        rf = self._rfcomm()
        ch = await rf.connect(acl_handle=handle, server_channel=channel)
        cached = getattr(self, "_rfcomm_channels", None)
        if cached is None:
            cached = self._rfcomm_channels = {}
        cached[(bytes(addr)[:6], channel)] = ch
        return ch, ch.max_frame_size

    def _rfcomm_channel(self, addr: bytes, channel: int):
        cached = getattr(self, "_rfcomm_channels", None) or {}
        ch = cached.get((bytes(addr)[:6], channel))
        if ch is None:
            # Incoming DLCs may have been cached under a peer key that
            # didn't resolve at handler time (session-table miss) — fall
            # back to the single DLC on the requested channel; the BTP
            # peer address is authoritative in these single-link cases.
            for (peer, chn), candidate in cached.items():
                if chn == channel:
                    return candidate
            raise RuntimeError(f"no RFCOMM DLC on channel {channel}")
        return ch

    async def rfcomm_disconnect(self, addr: bytes, channel: int) -> None:
        ch = self._rfcomm_channel(addr, channel)
        await ch.close()
        cached = getattr(self, "_rfcomm_channels", None) or {}
        cached.pop((bytes(addr)[:6], channel), None)

    async def rfcomm_send(self, addr: bytes, channel: int, value: bytes) -> None:
        ch = self._rfcomm_channel(addr, channel)
        logger.debug("rfcomm_send: channel=%d len=%d tx_credits=%s",
                     channel, len(value), getattr(ch, "_tx_credits", "?"))
        await ch.send(value)

    async def rfcomm_send_rls(self, addr: bytes, channel: int,
                              line_status: int) -> None:
        """Send an RLS MCC command on the DLC's session (BV-14 WID 23)."""
        ch = self._rfcomm_channel(addr, channel)
        session = getattr(ch, "_session", None)
        if session is None or not hasattr(session, "send_rls"):
            raise RuntimeError("RFCOMM session has no RLS support")
        await session.send_rls(getattr(ch, "dlci", channel * 2), line_status)

    async def rfcomm_send_rpn(self, addr: bytes, channel: int, baud_rate: int,
                              line_settings: int, flow_control: int,
                              xon_char: int, xoff_char: int,
                              param_mask: int) -> None:
        """Send an RPN MCC command on the DLC's session (BV-17/19)."""
        ch = self._rfcomm_channel(addr, channel)
        session = getattr(ch, "_session", None)
        if session is None or not hasattr(session, "send_rpn"):
            raise RuntimeError("RFCOMM session has no RPN support")
        await session.send_rpn(getattr(ch, "dlci", channel * 2), baud_rate,
                               line_settings, flow_control, xon_char,
                               xoff_char, param_mask)

    async def rfcomm_listen(self, channel: int) -> None:
        """Accept incoming DLCs on a server channel; wire their data/close
        callbacks so the BTP service can emit Connected/Data events."""
        rf = self._rfcomm()
        service = getattr(self, "_rfcomm_btp", None)

        def on_incoming(dlc) -> None:
            cached = getattr(self, "_rfcomm_channels", None)
            if cached is None:
                cached = self._rfcomm_channels = {}
            peer_le = b"\x00" * 6
            l2 = getattr(getattr(dlc, "_session", None), "_l2cap_channel", None)
            peer = getattr(l2, "peer", None) or getattr(l2, "peer_address", None)
            to_hci = getattr(peer, "to_hci", None)
            if callable(to_hci):
                peer_le = to_hci()
            cached[(bytes(peer_le)[:6], channel)] = dlc
            if service is not None:
                service.on_incoming_connected(bytes(peer_le)[:6], 0xE0,
                                              channel, dlc.max_frame_size)
                dlc.on_data(lambda data, _a=bytes(peer_le)[:6], _c=channel:
                            service.on_data_received(_a, 0xE0, _c, data))

        await rf.listen(channel, on_incoming)

    async def rfcomm_dlc_info(self, addr: bytes, channel: int) -> tuple[int, int]:
        """Return (MTU, state) — state: 0=disconnected, 1=connected, 2=connecting."""
        cached = getattr(self, "_rfcomm_channels", None) or {}
        ch = cached.get((bytes(addr)[:6], channel))
        if ch is None:
            return 0, 0
        return ch.max_frame_size, 1

    async def rfcomm_close_session(self, addr: bytes) -> None:
        """Send DISC(DLCI 0) to shut the multiplexer down (BV-04 WID 14).

        Covers both session origins: our initiator sessions (cached per peer
        from rfcomm_session_only) and responder sessions the manager created
        on inbound L2CAP connections (kept on the manager by ACL handle)."""
        cached = getattr(self, "_rfcomm_sessions", None) or {}
        session = cached.get(bytes(addr)[:6])
        if session is None:
            rf = self._rfcomm()
            for sess in getattr(rf, "_sessions", {}).values():
                session = sess
                break
        if session is None:
            raise RuntimeError("no RFCOMM session to close")
        await session.close()

    async def rfcomm_session_only(self, addr: bytes) -> None:
        """Open only the RFCOMM multiplexer session (SABM 0 ↔ UA), no DLC —
        RFCOMM/DEVA/RFC/BV-01 initialises the session and PTS registers no
        server channel, so a following PN/DLC makes it drop the ACL."""
        from pybluehost.core.address import AddressType, BDAddress
        from pybluehost.classic.rfcomm import RFCOMMSession
        from pybluehost.l2cap.constants import PSM_RFCOMM
        target = BDAddress.from_hci(bytes(addr)[:6], type=AddressType.PUBLIC)
        handle = self._classic_handle_for(addr)
        if handle is None:
            handle = await self._stack.connect_classic(target)
        channel = await self._stack.l2cap.connect_classic_channel(
            handle=handle, psm=PSM_RFCOMM)
        session = RFCOMMSession(channel)
        await session.open()
        cached = getattr(self, "_rfcomm_sessions", None)
        if cached is None:
            cached = self._rfcomm_sessions = {}
        cached[bytes(addr)[:6]] = session
