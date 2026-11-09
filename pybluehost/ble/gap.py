"""BLE GAP — advertising, scanning, connections, privacy, and white list."""
from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Iterator

from pybluehost.core.address import AddressType, BDAddress
from pybluehost.core.gap_common import AdvertisingData
from pybluehost.hci.constants import (
    LEMetaSubEvent,
    HCI_LE_ADD_DEVICE_TO_WHITE_LIST,
    HCI_LE_ADD_DEVICE_TO_RESOLVING_LIST,
    HCI_LE_CLEAR_WHITE_LIST,
    HCI_LE_CREATE_BIG,
    HCI_LE_CREATE_CONNECTION,
    HCI_LE_CREATE_CONNECTION_CANCEL,
    HCI_LE_EXTENDED_CREATE_CONNECTION,
    HCI_LE_SETUP_ISO_DATA_PATH,
    HCI_LE_TERMINATE_BIG,
    HCI_LE_PERIODIC_ADVERTISING_CREATE_SYNC,
    HCI_LE_PERIODIC_ADVERTISING_SET_INFO_TRANSFER,
    HCI_LE_PERIODIC_ADVERTISING_SYNC_TRANSFER,
    HCI_LE_PERIODIC_ADVERTISING_TERMINATE_SYNC,
    HCI_LE_REMOVE_DEVICE_FROM_WHITE_LIST,
    HCI_LE_SET_ADDRESS_RESOLUTION_ENABLE,
    HCI_LE_SET_ADVERTISING_SET_RANDOM_ADDRESS,
    HCI_LE_SET_RANDOM_ADDRESS,
    HCI_LE_SET_PERIODIC_ADVERTISING_DATA,
    HCI_LE_SET_PERIODIC_ADVERTISING_ENABLE,
    HCI_LE_SET_PERIODIC_ADVERTISING_PARAMS,
    HCI_LE_SET_PERIODIC_ADVERTISING_RECEIVE_ENABLE,
    HCI_LE_SET_PERIODIC_ADVERTISING_SYNC_TRANSFER_PARAMS,
    HCI_LE_SET_EXTENDED_ADVERTISING_DATA,
    HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE,
    HCI_LE_SET_EXTENDED_ADVERTISING_PARAMS,
    HCI_LE_SET_EXTENDED_SCAN_ENABLE,
    HCI_LE_SET_EXTENDED_SCAN_PARAMS,
    HCI_LE_SET_EXTENDED_SCAN_RSP_DATA,
)
from pybluehost.hci.controller import command_status
from pybluehost.hci.packets import HCI_LE_Meta_Event, HCICommand, HCIEvent


# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AdvertisingConfig:
    min_interval_ms: float = 100.0
    max_interval_ms: float = 100.0
    adv_type: int = 0x00       # ADV_IND
    channel_map: int = 0x07    # all channels
    filter_policy: int = 0x00
    # 0x00 = public; 0x01 = random (needed for NRPA/RPA advertising).
    own_address_type: int = 0x00
    # Directed advertising (ADV_DIRECT_IND 0x01 / 0x04) target. None = undirected.
    peer_address: "BDAddress | None" = None


@dataclass
class ScanConfig:
    active: bool = False
    interval_ms: float = 100.0
    window_ms: float = 50.0
    filter_duplicates: bool = True
    # LE_Set_Scan_Parameters Own_Address_Type: 0x00 = public, 0x01 = random.
    # GAP/BROB/OBSV/BV-05/06 have the IUT observe with a *private* address, so
    # the scanner has to honour this rather than always using the public one.
    own_address_type: int = 0x00


@dataclass
class ScanResult:
    address: BDAddress
    rssi: int
    advertising_data: AdvertisingData
    connectable: bool = True
    # The report's EIR exactly as it came off the air. AdvertisingData models a
    # handful of AD types and re-serialising drops the rest (URI, service data,
    # manufacturer data…), which is fatal for anything comparing the received
    # bytes. Consumers that need fidelity use this; the parsed view is for the
    # convenience accessors.
    raw_advertising_data: bytes = b""

    @property
    def local_name(self) -> str | None:
        return (
            self.advertising_data.get_complete_local_name()
            or self.advertising_data.get_short_local_name()
        )


@dataclass
class BLEConnectionConfig:
    scan_interval_ms: float = 60.0
    scan_window_ms: float = 30.0
    min_interval_ms: float = 30.0
    max_interval_ms: float = 50.0
    latency: int = 0
    supervision_timeout_ms: float = 5000.0
    # LE_Create_Connection Initiator_Filter_Policy: 0x00 = use the peer address
    # below, 0x01 = ignore it and connect to whatever advertises matching the
    # controller's filter accept list (GAP/CONN/ACEP's Auto Connection
    # Establishment procedure). With 0x01 the target address is not used.
    filter_policy: int = 0x00
    own_address_type: int = 0x00


class ConnectionRole(IntEnum):
    CENTRAL = 0
    PERIPHERAL = 1


@dataclass
class BLEConnection:
    handle: int
    peer_address: BDAddress
    role: ConnectionRole
    att: object | None = None
    gatt_client: object | None = None
    gatt_server: object | None = None
    smp: object | None = None


@dataclass
class ExtAdvertisingConfig:
    adv_handle: int = 0
    primary_phy: int = 1       # 1=1M, 3=coded
    secondary_phy: int = 1
    adv_type: int = 0x05       # non-connectable, non-scannable, undirected
    max_skip: int = 0
    # LE_Set_Extended_Advertising_Parameters tail (Core §7.8.53).
    properties: int = 0x0010   # 0x0010 = use LEGACY PDUs (bit 4)
    interval_min: int = 0x000020
    interval_max: int = 0x000020
    channel_map: int = 0x07
    own_address_type: int = 0x00
    peer_address_type: int = 0x00
    peer_address: bytes = bytes(6)
    filter_policy: int = 0x00
    tx_power: int = 0x7F       # host has no preference
    sid: int = 0


# ---------------------------------------------------------------------------
# Helper: build a raw HCI command with given opcode and parameters
# ---------------------------------------------------------------------------

def _make_cmd(opcode: int, params: bytes = b"") -> HCICommand:
    """Create an HCICommand with the given opcode and parameters."""
    return HCICommand(opcode=opcode, parameters=params)


def _extended_scan_params_body(
    own_address_type: int, scan_type: int, interval: int, window: int
) -> bytes:
    """LE_Set_Extended_Scan_Parameters body (Core Vol 4 Part E §7.8.64).

    Scanning_PHYs selects LE 1M only, but the command still carries one
    Scan_Type/Interval/Window triple per PHY, so the second triple is present
    and ignored. (The BE200 tolerates a truncated 8-byte body, but that is
    lenient parsing, not the command.)
    """
    per_phy = bytes([scan_type]) + struct.pack("<HH", interval, window)
    return bytes([own_address_type & 0xFF, 0x00, 0x01]) + per_phy + per_phy


# ---------------------------------------------------------------------------
# BLEAdvertiser
# ---------------------------------------------------------------------------

def _ad_to_raw(ad_data: AdvertisingData | bytes) -> bytes:
    """Coerce advertising/scan-rsp data to serialized AD TLV bytes.

    Accepts an ``AdvertisingData`` structure (serialize it) or raw bytes
    (already-serialized TLVs, returned unchanged so controller receives the
    exact bytes the caller — e.g. the PTS BTP path — supplied).
    """
    return ad_data if isinstance(ad_data, (bytes, bytearray)) else ad_data.to_bytes()


# BLEAdvertiser owns advertising set 0; PeriodicAdvertising owns set 1 (see
# PERIODIC_ADV_HANDLE). They must be distinct: periodic advertising is only
# defined on an extended-PDU set, and one set cannot be both legacy-PDU/
# connectable and periodic (Core §7.8.61 answers Invalid HCI Command
# Parameters, 0x12).
ADVERTISING_HANDLE = 0x00

# LE_Set_Extended_Advertising_Parameters Advertising_Event_Properties for each
# legacy adv_type (Core Table 7.3). Bit 4 keeps the on-air PDUs byte-identical
# to what the legacy LE_Set_Advertising_Parameters command produced.
_LEGACY_PDU_PROPERTIES = {
    0x00: 0x0013,   # ADV_IND          connectable + scannable
    0x01: 0x001D,   # ADV_DIRECT_IND   connectable + directed + high duty cycle
    0x02: 0x0012,   # ADV_SCAN_IND     scannable
    0x03: 0x0010,   # ADV_NONCONN_IND  neither
    0x04: 0x0015,   # ADV_DIRECT_IND   connectable + directed + low duty cycle
}
# Table 7.3: the remaining legacy PDU types carry no advertising data, and
# §7.8.53 rejects writing data to such a set with 0x12 once it holds some.
_LEGACY_PDU_DATA_TYPES = frozenset({0x00, 0x02, 0x03})


class BLEAdvertiser:
    """BLE advertising controller — advertising set 0.

    This drives the *extended* advertising command family with properties bit 4
    ("Use legacy advertising PDUs") set, so the on-air PDUs are byte-identical
    to what LE_Set_Advertising_Parameters used to produce.

    Core Vol 4 Part E §3.1.1: "If, since the last power-on or reset, the Host
    has ever issued a legacy advertising command and then issues an extended
    advertising command, or has ever issued an extended advertising command and
    then issues a legacy advertising command, the Controller shall return the
    error code Command Disallowed (0x0C)." Table 3.2's extended family includes
    LE_Set_Periodic_Advertising_* and LE_Set_Periodic_Advertising_Sync_
    Transfer_Parameters, so a single legacy command anywhere in the power cycle
    poisons every periodic advertising command. Using the extended family
    everywhere is what unblocks GAP/PADV.
    """

    def __init__(self, hci: object) -> None:
        self._hci = hci
        self._active = False
        # Remembered so the address-rotation path can restart advertising with
        # the same parameters/data after swapping the random address.
        self._last_start: tuple[AdvertisingConfig, object, object] | None = None
        # The address to program into set 0 whenever Own_Address_Type is 0x01.
        # LE_Set_Advertising_Set_Random_Address is the only command that reaches
        # an advertising set (Core §7.8.5 note); LE_Set_Random_Address is limited
        # to scanning and initiating once the extended commands are in use.
        self._random_address: bytes | None = None

    async def pause_for_address_change(self) -> bool:
        """Stop advertising so the random address can be changed.

        Returns True when advertising was actually running (and therefore needs
        ``resume_after_address_change``).
        """
        if not self._active:
            return False
        await self.stop()
        return True

    async def resume_after_address_change(self) -> None:
        """Re-issue the last ``start()`` with the newly programmed address."""
        if self._last_start is None:
            return
        config, ad_data, scan_rsp_data = self._last_start
        await self.start(config, ad_data=ad_data, scan_rsp_data=scan_rsp_data)

    @property
    def advertising_address(self) -> bytes | None:
        """The random address set 0 advertises with, or None for the identity.

        A connection established from this advertising set carries this address
        on air, and SMP's Secure Connections f5/f6 must hash the address the
        peer saw — the controller's Connection Complete does not report a
        host-programmed random address back, so this is the only record of it.
        """
        if self._random_address is None or self._last_start is None:
            return None
        if getattr(self._last_start[0], "own_address_type", 0x00) != 0x01:
            return None
        return bytes(self._random_address)

    async def set_random_address(self, address: bytes) -> bool:
        """Program the address set 0 advertises with when it uses a random one.

        The address is remembered even when the write is rejected (a set that
        has not been created yet answers Unknown Advertising Identifier, 0x42),
        so the next ``start()`` re-applies it after creating the set.
        """
        self._random_address = bytes(address[:6])
        return await self._program_random_address()

    async def _program_random_address(self) -> bool:
        if self._random_address is None:
            return False
        params = bytes([ADVERTISING_HANDLE]) + self._random_address
        event = await self._hci.send_command(
            _make_cmd(HCI_LE_SET_ADVERTISING_SET_RANDOM_ADDRESS, params)
        )
        status = getattr(event, "return_parameters", b"\x00")[:1]
        ok = not status or status[0] == 0x00
        if not ok:
            logger.warning(
                "BLEAdvertiser: LE_Set_Advertising_Set_Random_Address rejected, status=0x%02X",
                status[0],
            )
        else:
            logger.debug(
                "BLEAdvertiser: advertising set address set to %s",
                self._random_address.hex(),
            )
        return ok

    async def start(
        self,
        config: AdvertisingConfig = AdvertisingConfig(),
        ad_data: AdvertisingData | bytes | None = None,
        scan_rsp_data: AdvertisingData | bytes | None = None,
    ) -> None:
        """Start advertising with the given config and data.

        ``ad_data``/``scan_rsp_data`` accept either an ``AdvertisingData``
        structure or raw bytes. Raw bytes are already serialized AD TLVs
        ([length][type][data...]) and are pushed to the controller verbatim —
        the PTS BTP path supplies exactly the bytes the Lower Tester expects,
        so they must not be parsed/re-serialized (which would reorder or
        collapse duplicate AD structures).
        """
        # Reprogramming a set is only legal while it is disabled: the Intel
        # controller answers 0x0C otherwise, and a privacy RPA swap can resume advertising before this call.
        if self._active:
            await self.stop()
        properties = _LEGACY_PDU_PROPERTIES.get(config.adv_type, 0x0010)
        # Legacy PDUs only exist on the LE 1M PHY (Table 7.3) and intervals are
        # in units of 0.625 ms, floored at the 20 ms extended-advertising minimum.
        min_interval = max(int(config.min_interval_ms / 0.625), 0x000020)
        max_interval = max(int(config.max_interval_ms / 0.625), min_interval)
        peer = config.peer_address
        if peer is not None:
            peer_addr_type = int(getattr(peer, "type", 0)) & 0xFF
            peer_addr = bytes(peer.to_hci()) if hasattr(peer, "to_hci") else bytes(6)
        else:
            peer_addr_type = 0x00
            peer_addr = bytes(6)
        params = (
            bytes([ADVERTISING_HANDLE])
            + struct.pack("<H", properties)
            + min_interval.to_bytes(3, "little")
            + max_interval.to_bytes(3, "little")
            + bytes([config.channel_map, config.own_address_type, peer_addr_type])
            + peer_addr
            + bytes([config.filter_policy, 0x7F, 0x01, 0x00, 0x01, 0x00, 0x00])
        )
        params_event = await self._hci.send_command(
            _make_cmd(HCI_LE_SET_EXTENDED_ADVERTISING_PARAMS, params)
        )
        status = getattr(params_event, "return_parameters", b"\x00")[:1]
        if status and status[0] != 0x00:
            logger.warning(
                "BLEAdvertiser: LE_Set_Extended_Advertising_Parameters rejected, status=0x%02X",
                status[0],
            )
        logger.debug(
            "BLEAdvertiser: start adv_type=0x%02X properties=0x%04X own_addr_type=0x%02X "
            "interval=%.2fms",
            config.adv_type, properties, config.own_address_type, config.min_interval_ms,
        )

        # A set has to exist before it can carry an address, so this has to
        # follow LE_Set_Extended_Advertising_Parameters on every (re)start.
        if config.own_address_type == 0x01:
            await self._program_random_address()

        # Directed advertising carries no AD payload (Table 7.3) and is not
        # scannable; writing data to such a set is rejected with 0x12 when the
        # set already holds some.
        if config.adv_type in _LEGACY_PDU_DATA_TYPES:
            # Order matters on the Intel BE200: an empty scan-response write
            # (which is what a start without scan_rsp_data sends) clears the
            # set's advertising data, so the advertising data has to go in
            # last to survive it. §7.8.55 governs a separate buffer and does
            # not sanction this, but the controllers we test against behave
            # this way and the ordering costs nothing.
            await self._write_data(HCI_LE_SET_EXTENDED_SCAN_RSP_DATA, scan_rsp_data)
            await self._write_data(HCI_LE_SET_EXTENDED_ADVERTISING_DATA, ad_data)

        enable = bytes([0x01, 0x01, ADVERTISING_HANDLE, 0x00, 0x00, 0x00])
        enable_event = await self._hci.send_command(
            _make_cmd(HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE, enable)
        )
        status = getattr(enable_event, "return_parameters", b"\x00")[:1]
        if status and status[0] != 0x00:
            logger.warning(
                "BLEAdvertiser: LE_Set_Extended_Advertising_Enable rejected, status=0x%02X",
                status[0],
            )
        self._active = True
        self._last_start = (config, ad_data, scan_rsp_data)

    async def _write_data(self, opcode: int, data: AdvertisingData | bytes | None) -> None:
        raw = _ad_to_raw(data) if data is not None else b""
        # Operation 0x03 = complete data; the length is explicit, so unlike the
        # legacy command there is nothing to zero-pad. Fragment_Preference is
        # 0x00 ("the Controller may fragment") and must be sent — dropping it
        # shifts the length into its slot and the first AD byte into the
        # length's, which the controller accepts with 0x00 while putting a
        # two-byte AD on air (Core §7.8.54).
        params = bytes([ADVERTISING_HANDLE, 0x03, 0x00, len(raw)]) + raw
        await self._hci.send_command(_make_cmd(opcode, params))

    async def stop(self) -> None:
        """Stop advertising.

        Scoped to set 0 rather than "disable all": periodic advertising runs on
        its own set and the GAP stop must not tear it down.
        """
        if not self._active:
            return
        disable = bytes([0x00, 0x01, ADVERTISING_HANDLE, 0x00, 0x00, 0x00])
        await self._hci.send_command(
            _make_cmd(HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE, disable)
        )
        self._active = False

    async def update_data(self, ad_data: AdvertisingData | bytes) -> None:
        """Update advertising data while advertising."""
        await self._write_data(HCI_LE_SET_EXTENDED_ADVERTISING_DATA, ad_data)


# ---------------------------------------------------------------------------
# PeriodicAdvertising
# ---------------------------------------------------------------------------

# LE_Set_Periodic_Advertising_* use advertising set handles; PTS exercises a
# single periodic set, so one handle is all we need (the BTP commands carry no
# handle). It must differ from ADVERTISING_HANDLE: periodic advertising is only
# defined on an extended-PDU set, and BLEAdvertiser's set carries legacy PDUs.
PERIODIC_ADV_HANDLE = 0x01
# The bit that says "include TxPower in the periodic advertising PDU" (the
# LE_Set_Periodic_Advertising_Parameters Properties field, Core §7.8.61).
PERIODIC_ADV_PROP_INCLUDE_TX_POWER = 0x0040

_PERIODIC_SUBEVENTS = frozenset({
    LEMetaSubEvent.LE_PERIODIC_ADVERTISING_REPORT,
    LEMetaSubEvent.LE_PERIODIC_ADVERTISING_SYNC_ESTABLISHED,
    LEMetaSubEvent.LE_PERIODIC_ADVERTISING_SYNC_LOST,
    LEMetaSubEvent.LE_PERIODIC_ADVERTISING_SYNC_TRANSFER_RECEIVED,
})

logger = logging.getLogger(__name__)


@dataclass
class PeriodicAdvertisingConfig:
    """Parameters for LE_Set_Periodic_Advertising_Parameters."""

    interval_min: int = 0x0006   # in 1.25 ms units
    interval_max: int = 0x0006
    properties: int = 0x0000


@dataclass
class PeriodicSync:
    """A periodic-advertising sync the controller reported as established."""

    sync_handle: int
    adv_sid: int = 0
    advertiser_address: bytes = bytes(6)
    advertiser_address_type: int = 0x00
    adv_phy: int = 0x01
    interval: int = 0
    clock_accuracy: int = 0


class PeriodicAdvertising:
    """Periodic advertising (advertiser side) + periodic sync (scanner side).

    Drives the LE_Set_Periodic_Advertising_* / LE_Periodic_Advertising_* HCI
    commands. The BTP GAP service (opcodes 0x22-0x29) is the caller — see
    ``pts/btp/services/gap.py``.
    """

    def __init__(self, hci: object) -> None:
        self._hci = hci
        self._enabled = False
        self._syncing = False
        self._sync: PeriodicSync | None = None
        self._transfer_info: tuple[int, int] | None = None
        # The advertising set periodic advertising hangs off — periodic
        # advertising is only valid on a set created with extended PDUs.
        self._ext_advertiser: ExtendedAdvertiser | None = None
        self._broadcast_ready = False
        # Scan engine, used only to satisfy the sync-establishment prerequisite
        # below — see _ensure_scanning.
        self._scanner: BLEScanner | None = None
        self._scan_started_for_sync = False
        # Callables invoked on the matching LE Meta subevent.
        self._on_sync_established: Callable[[PeriodicSync], object] | None = None
        self._on_sync_lost: Callable[[int], object] | None = None
        self._on_report: Callable[[bytes], object] | None = None
        self._on_transfer_received: Callable[[], object] | None = None

    def bind_extended_advertiser(self, ext_advertiser: "ExtendedAdvertiser") -> None:
        self._ext_advertiser = ext_advertiser

    def bind_scanner(self, scanner: "BLEScanner") -> None:
        """Hand over the scan engine so sync establishment can tell whether the
        application already owns it.

        ``LE_Periodic_Advertising_Create_Sync`` only *attempts* to synchronize
        while scanning is enabled (Vol 4 Part E §7.8.67), so the sync side has
        to be able to turn scanning on — and to know when the application has
        it on already, rather than fight over the single scan engine.
        """
        self._scanner = scanner

    async def _ensure_scanning(self) -> None:
        """Enable scanning so the controller will attempt the sync at all.

        §7.8.67: "synchronization can only occur when scanning is enabled.
        While scanning is disabled, no attempt to synchronize will take
        place." The command is accepted either way, so a controller whose scan
        is off answers Command Complete/Status 0x00 and then emits nothing —
        no Sync Established, no error, nothing to time out on. The GAP.TS
        initial condition for the PADV/PASE cases is Link Layer *Standby*, so
        enabling the scan is the Host's job as part of the procedure.

        The scan has to be the **extended** one: §7.8.11 says
        HCI_LE_Set_Scan_Enable "is used to start and stop scanning for legacy
        PDUs (but not extended PDUs, even if the device supports extended
        advertising)", and a periodic advertising train is carried by
        AUX_SYNC_IND — an extended PDU. Scanning legacy leaves the controller
        blind to it, which looks exactly like "the command was accepted and
        then nothing ever happened".
        """
        if self._scan_started_for_sync:
            logger.debug("PeriodicAdvertising: extended scan already on for sync")
            return
        scanner = self._scanner
        if scanner is not None and scanner.active:
            # The application already owns the scan engine. Reprogramming its
            # scan parameters would break whatever it is doing, and a second
            # scan-enable is a no-op anyway (the extended scan enable is one
            # controller-wide setting, first-come-first-served). The app
            # scanner's default 50% duty plus duplicate filtering is what the
            # train has to survive, so say so — from PTS this looks like
            # "accepted the command, then nothing happened".
            logger.warning(
                "PeriodicAdvertising: sync requested while the bound scanner is "
                "active — its scan parameters and duplicate filter are in force, "
                "so the ADV_EXT_IND carrying the periodic train may never be seen"
            )
            return
        config = ScanConfig()
        interval = int(config.interval_ms / 0.625)
        # 100% duty: a periodic advertising train is only on its channel for a
        # sliver of each interval, and this scan exists solely to catch the
        # ADV_EXT_IND that carries its SyncInfo.
        window = interval
        params = _extended_scan_params_body(
            config.own_address_type, 0x01 if config.active else 0x00, interval, window
        )
        await self._send(
            HCI_LE_SET_EXTENDED_SCAN_PARAMS, params, "Set_Extended_Scan_Params"
        )
        await self._send(
            HCI_LE_SET_EXTENDED_SCAN_ENABLE,
            bytes([0x01, 0x01 if config.filter_duplicates else 0x00]) + bytes(4),
            "Set_Extended_Scan_Enable(enable)",
        )
        self._scan_started_for_sync = True

    async def _release_scanning(self) -> None:
        """Undo ``_ensure_scanning``, but only if we were the one who enabled."""
        if not self._scan_started_for_sync:
            return
        self._scan_started_for_sync = False
        await self._send(
            HCI_LE_SET_EXTENDED_SCAN_ENABLE,
            bytes([0x00, 0x00]) + bytes(4),
            "Set_Extended_Scan_Enable(disable)",
        )

    @staticmethod
    def _check_status(command: str, event) -> None:
        """Log a warning when the controller rejects a periodic-advertising
        command. Silently ignoring these turns into a PTS time-out far from the
        actual cause (e.g. Unknown Advertising Identifier when the extended
        advertising set was never created)."""
        status = command_status(event)
        if status:
            logger.warning(
                "PeriodicAdvertising: %s rejected, status=0x%02X", command, status,
            )

    async def _send(self, opcode: int, params: bytes, command: str) -> None:
        """Issue an HCI command and surface a non-zero status."""
        event = await self._hci.send_command(_make_cmd(opcode, params))
        status = command_status(event)
        logger.debug(
            "PeriodicAdvertising: %s opcode=0x%04X params=%s -> status=%s",
            command, opcode, params.hex(),
            "?" if status is None else f"{status:02X}",
        )
        self._check_status(command, event)

    async def _send_enable(self, enable: bool) -> None:
        await self._send(
            HCI_LE_SET_PERIODIC_ADVERTISING_ENABLE,
            bytes([0x01 if enable else 0x00, PERIODIC_ADV_HANDLE]),
            "Set_Periodic_Adv_Enable",
        )

    # -- notification hooks --------------------------------------------

    def set_handlers(
        self,
        *,
        on_sync_established: Callable[[PeriodicSync], object] | None = None,
        on_sync_lost: Callable[[int], object] | None = None,
        on_report: Callable[[bytes], object] | None = None,
        on_transfer_received: Callable[[], object] | None = None,
    ) -> None:
        self._on_sync_established = on_sync_established
        self._on_sync_lost = on_sync_lost
        self._on_report = on_report
        self._on_transfer_received = on_transfer_received

    @property
    def sync(self) -> PeriodicSync | None:
        return self._sync

    # -- advertiser side -------------------------------------------------

    async def configure(
        self,
        *,
        include_tx_power: bool = False,
        interval_min: int = 0x0006,
        interval_max: int = 0x0006,
        properties: int | None = None,
    ) -> None:
        """Bring up the advertising set, then LE_Set_Periodic_Advertising_Parameters.

        Periodic advertising is only defined on an advertising set created with
        EXTENDED PDUs, so the set has to exist (and be enabled) first — the
        controller answers Unknown Advertising Identifier otherwise.
        """
        await self._prepare_broadcast()
        if properties is None:
            properties = PERIODIC_ADV_PROP_INCLUDE_TX_POWER if include_tx_power else 0
        params = struct.pack(
            "<BHHH",
            PERIODIC_ADV_HANDLE,
            # auto-pts passes the interval in 1.25 ms units already
            max(interval_min, 0x0006), max(interval_max, 0x0006),
            properties,
        )
        await self._send(
            HCI_LE_SET_PERIODIC_ADVERTISING_PARAMS, params,
            "Set_Periodic_Adv_Parameters",
        )

    async def _prepare_broadcast(self) -> None:
        """Create + enable the extended advertising set periodic advertising
        rides on. Idempotent: only the first call issues commands."""
        if self._broadcast_ready or self._ext_advertiser is None:
            return
        config = ExtAdvertisingConfig(
            adv_handle=PERIODIC_ADV_HANDLE,
            # Non-connectable, non-scannable, EXTENDED PDUs (bit 4 clear).
            properties=0x0000,
            interval_min=0x000020,
            interval_max=0x000020,
        )
        await self._ext_advertiser.create_set(config)
        # Advertising data: empty is legal and keeps the PDU minimal; the
        # controller appends the SyncInfo itself.
        await self._ext_advertiser.set_data(PERIODIC_ADV_HANDLE, AdvertisingData())
        await self._ext_advertiser.start([PERIODIC_ADV_HANDLE])
        self._broadcast_ready = True

    async def set_data(self, data: bytes) -> None:
        """LE_Set_Periodic_Advertising_Data (252-byte field, zero-padded).

        The same payload also goes into the extended advertising data: the
        Lower Tester discovers the periodic advertiser by scanning the extended
        PDUs, and the PADV test cases verify the advertising data it sees.
        """
        if len(data) > 252:
            raise ValueError(f"periodic advertising data too long: {len(data)}")
        # Advertising_Handle, Operation, Advertising_Data_Length, Advertising_Data
        # (§7.8.63). The Operation byte is easy to drop and its absence is
        # invisible: the controller then reads Advertising_Data_Length as the
        # operation, and 0x03 is both "complete data" and a legal length, so a
        # three-octet payload passes by coincidence while any other length
        # answers 0x12.
        params = (
            bytes([PERIODIC_ADV_HANDLE, 0x03, len(data)])
            + data
            + bytes(252 - len(data))
        )
        await self._send(
            HCI_LE_SET_PERIODIC_ADVERTISING_DATA, params, "Set_Periodic_Adv_Data"
        )
        if self._ext_advertiser is not None and data:
            await self._ext_advertiser.set_data(PERIODIC_ADV_HANDLE, bytes(data))

    async def start(self) -> None:
        """LE_Set_Periodic_Advertising_Enable (enable)."""
        await self._send_enable(True)
        self._enabled = True

    async def stop(self) -> None:
        """LE_Set_Periodic_Advertising_Enable (disable)."""
        await self._send_enable(False)
        self._enabled = False

    # -- scanner side ----------------------------------------------------

    async def create_sync(
        self,
        *,
        adv_sid: int,
        skip: int,
        sync_timeout: int,
        flags: int,
        address_type: int,
        address: bytes,
    ) -> None:
        """LE_Periodic_Advertising_Create_Sync.

        ``flags`` is the BTP/auto-pts flag byte for this command (doc/btp_gap.txt
        opcode 0x26): bit 0 = Reports Disabled, bit 1 = Duplicate filtering
        enabled. The HCI ``Options`` byte it maps onto has a different layout
        (§7.8.67), so the bits have to be moved, not copied:

        * bit 0 stays clear — we always sync to the explicit
          Advertising_SID/Advertiser_Address parameters below. Setting it would
          mean "listen to the Periodic Advertiser List" instead, which we never
          populate, so the sync would silently never establish.
        * bit 0 (Reports Disabled) -> bit 1 (Reporting initially disabled)
        * bit 1 (Duplicate filtering enabled) -> bit 2
        """
        options = ((flags & 0x01) << 1) | ((flags & 0x02) << 1)
        params = (
            struct.pack("<BB", options, adv_sid)
            + bytes([address_type])
            + bytes(address[:6]).ljust(6, b"\x00")
            + struct.pack("<HHB", skip, sync_timeout, 0x00)  # Sync_CTE_Type
        )
        await self._ensure_scanning()
        await self._send(
            HCI_LE_PERIODIC_ADVERTISING_CREATE_SYNC, params,
            "Periodic_Adv_Create_Sync",
        )
        self._syncing = True

    async def terminate_sync(self, sync_handle: int) -> None:
        """LE_Periodic_Advertising_Terminate_Sync."""
        await self._hci.send_command(
            _make_cmd(
                HCI_LE_PERIODIC_ADVERTISING_TERMINATE_SYNC,
                struct.pack("<H", sync_handle),
            )
        )
        await self._release_scanning()
        self._syncing = False
        self._sync = None

    async def set_receive_enable(self, sync_handle: int, enable: bool) -> None:
        """LE_Set_Periodic_Advertising_Receive_Enable."""
        await self._hci.send_command(
            _make_cmd(
                HCI_LE_SET_PERIODIC_ADVERTISING_RECEIVE_ENABLE,
                struct.pack("<HB", sync_handle, 0x01 if enable else 0x00),
            )
        )

    async def set_sync_transfer_parameters(
        self, *, conn_handle: int, mode: int, skip: int, sync_timeout: int,
    ) -> None:
        """LE_Set_Periodic_Advertising_Sync_Transfer_Parameters.

        The HCI parameter list starts with the Connection_Handle
        (``Connection_Handle(2) + Mode(1) + Skip(2) + Sync_Timeout(2) +
        CTE_Type(1)`` = 8 octets, Vol 4 Part E §7.8.91). Omitting it sent a
        6-octet command, which the controller rejects — so a Lower Tester's
        Periodic Advertising Sync Transfer never reaches us and every PAST case
        (GAP/PADV/PASE/BV-03…, PADV/PAST/*) dies waiting for it.
        """
        await self._send(
            HCI_LE_SET_PERIODIC_ADVERTISING_SYNC_TRANSFER_PARAMS,
            struct.pack("<HBHHB", conn_handle, mode, skip, sync_timeout, 0x00),
            "LE_Set_Periodic_Advertising_Sync_Transfer_Parameters",
        )

    async def set_info_transfer(
        self, *, conn_handle: int, service_data: int,
        adv_handle: int = PERIODIC_ADV_HANDLE,
    ) -> None:
        """LE_Periodic_Advertising_Set_Info_Transfer — hand our periodic
        advertising on air to a connected peer.

        Vol 4 Part E §7.8.90: the *source* direction of the procedure
        (``Connection_Handle(2) + Service_Data(2) + Advertising_Handle(1)``).
        This is the command GAP.TS step 4 asks the IUT for in PADV/PAST, and
        the only one of the PAST family that sends anything without the Host
        already holding a Sync_Handle — the peer's controller reports the
        result to its own Host as LE_Periodic_Advertising_Sync_Transfer_Received.
        """
        await self._send(
            HCI_LE_PERIODIC_ADVERTISING_SET_INFO_TRANSFER,
            struct.pack("<HHB", conn_handle, service_data, adv_handle),
            "LE_Periodic_Advertising_Set_Info_Transfer",
        )

    async def sync_transfer(
        self, *, conn_handle: int, service_data: int, sync_handle: int,
    ) -> None:
        """LE_Periodic_Advertising_Sync_Transfer (send our sync to a peer)."""
        await self._hci.send_command(
            _make_cmd(
                HCI_LE_PERIODIC_ADVERTISING_SYNC_TRANSFER,
                struct.pack("<HHH", conn_handle, service_data, sync_handle),
            )
        )

    def remember_transfer_info(self, service_data: int, sync_handle: int) -> None:
        """Record what to pass to ``sync_transfer`` for a later BTP command."""
        self._transfer_info = (service_data, sync_handle)

    # -- HCI event fan-in -------------------------------------------------

    async def on_hci_event(self, event: HCIEvent) -> None:
        """Consume periodic-advertising LE Meta subevents we registered for."""
        if not isinstance(event, HCI_LE_Meta_Event):
            return
        params = event.subevent_parameters
        if event.subevent_code in _PERIODIC_SUBEVENTS:
            logger.debug(
                "PeriodicAdvertising: subevent 0x%02X params=%s",
                event.subevent_code, bytes(params[:20]).hex(),
            )
        if event.subevent_code == LEMetaSubEvent.LE_PERIODIC_ADVERTISING_SYNC_ESTABLISHED:
            sync = _parse_sync_established(params)
            if sync is not None:
                self._sync = sync
                self._syncing = False
                if self._on_sync_established is not None:
                    self._on_sync_established(sync)
            elif params:
                logger.warning(
                    "PeriodicAdvertising: sync establishment failed, status=0x%02X",
                    params[0],
                )
        elif event.subevent_code == LEMetaSubEvent.LE_PERIODIC_ADVERTISING_SYNC_LOST:
            if len(params) >= 2:
                handle = struct.unpack_from("<H", params, 0)[0]
                self._sync = None
                self._syncing = False
                if self._on_sync_lost is not None:
                    self._on_sync_lost(handle)
        elif event.subevent_code == LEMetaSubEvent.LE_PERIODIC_ADVERTISING_REPORT:
            # Sync_Handle(2) TxPower(1) RSSI(1) CTE_Type(1) Data_Status(1)
            # Data_Length(1) then the data itself.
            if len(params) >= 7:
                data_len = params[6]
                payload = bytes(params[7:7 + data_len])
                if self._on_report is not None:
                    self._on_report(payload)
        elif event.subevent_code == LEMetaSubEvent.LE_PERIODIC_ADVERTISING_SYNC_TRANSFER_RECEIVED:
            if self._on_transfer_received is not None:
                self._on_transfer_received()


def _parse_sync_established(params: bytes) -> PeriodicSync | None:
    """Parse LE_Periodic_Advertising_Sync_Established.

    Status(1) Sync_Handle(2) SID(1) AddrType(1) Addr(6) PHY(1) Interval(2)
    ClockAccuracy(1). A non-zero status means the sync failed — report nothing.
    """
    if len(params) < 15 or params[0] != 0x00:
        return None
    sync_handle, adv_sid, addr_type = struct.unpack_from("<HBB", params, 1)
    address = bytes(params[5:11])
    adv_phy = params[11]
    interval = struct.unpack_from("<H", params, 12)[0]
    return PeriodicSync(
        sync_handle=sync_handle, adv_sid=adv_sid,
        advertiser_address=address, advertiser_address_type=addr_type,
        adv_phy=adv_phy, interval=interval, clock_accuracy=params[14],
    )


# ---------------------------------------------------------------------------
# IsoBroadcastManager (Broadcast Isochronous Group — the BIG broadcaster)
# ---------------------------------------------------------------------------

class IsoBroadcastManager:
    """Broadcast Isochronous Group: LE_Create_BIG → ISO data paths → ISO SDUs.

    The broadcaster half of isochronous channels, driven by the BTP GAP
    CREATE_BIG (0x2d) / BIS_BROADCAST (0x2e) commands for PTS GAP/BIS/BBM/BV-01-C.
    ``create_big`` resolves only after the controller reports LE BIG Complete —
    the BIS connection handles in that event are the handles the host feeds
    ISO SDUs to, so nothing can be sent before it arrives.
    """

    # LE_Create_BIG answers Command Status immediately; the BIS handles come
    # later in LE BIG Complete. BBM/BV-01's BIG (NSE 2, 10 ms SDU interval)
    # establishes in well under a second on air — 10 s covers a cold controller
    # without hanging a BTP command anywhere near auto-pts's 20 s read timeout.
    BIG_COMPLETE_TIMEOUT_S = 10.0

    def __init__(self, hci: object) -> None:
        self._hci = hci
        # bis_id (0..num_bis-1, in LE BIG Complete handle order) -> conn handle.
        self.bis_handles: dict[int, int] = {}
        # Per-BIS Packet_Sequence_Number, incremented per SDU sent (§5.4.5).
        self._sequence_numbers: dict[int, int] = {}
        # LE BIG Complete resolves this while a create_big is in flight.
        self._big_waiter: "asyncio.Future | None" = None

    # -- LE_Create_BIG (Vol 4 Part E §7.8.99) ------------------------------

    async def create_big(
        self,
        *,
        big_handle: int = 0x00,
        adv_handle: int = PERIODIC_ADV_HANDLE,
        num_bis: int = 1,
        sdu_interval_us: int = 10000,
        max_sdu: int = 251,
        max_transport_latency_ms: int = 20,
        rtn: int = 0,
        phy: int = 0x01,
        packing: int = 0,
        framing: int = 0,
        encryption: int = 0,
        broadcast_code: bytes | None = None,
        timeout_s: float | None = None,
    ) -> dict[int, int]:
        """Create a BIG off ``adv_handle`` and wire each BIS's HCI data path.

        Returns {bis_id: connection_handle} once LE BIG Complete arrives.
        Raises ``RuntimeError`` if the controller reports a failure status and
        ``asyncio.TimeoutError`` if no event comes back.
        """
        code = bytes(16)
        if encryption and broadcast_code is not None:
            code = bytes(broadcast_code[:16]).ljust(16, b"\x00")
        params = (
            struct.pack(
                "<BBB", big_handle, adv_handle, num_bis,
            )
            + int(sdu_interval_us).to_bytes(3, "little")
            + struct.pack(
                "<HHBBBBB",
                max_sdu, max_transport_latency_ms,
                rtn, phy, packing, framing, encryption,
            )
            + code
        )
        loop = asyncio.get_running_loop()
        self._big_waiter = loop.create_future()
        try:
            await self._send(HCI_LE_CREATE_BIG, params, "LE_Create_BIG")
            status, handles = await asyncio.wait_for(
                self._big_waiter, timeout_s or self.BIG_COMPLETE_TIMEOUT_S,
            )
        finally:
            self._big_waiter = None
        if status != 0x00:
            raise RuntimeError(
                f"LE_Create_BIG failed: status 0x{status:02X} "
                f"(big_handle=0x{big_handle:02X} num_bis={num_bis})"
            )
        self.bis_handles = dict(enumerate(handles))
        self._sequence_numbers = {}
        # The controller starts delivering ISO data the moment the BIG is up,
        # but only through a data path the host has configured — one per BIS.
        for handle in handles:
            await self._setup_iso_data_path(handle)
        return dict(self.bis_handles)

    async def _setup_iso_data_path(self, conn_handle: int) -> None:
        """LE_Setup_ISO_Data_Path (§7.8.107): HCI input path, transparent codec.

        A broadcaster feeds SDUs from the host, so the direction is Input
        (0x00) and the path is HCI (0x00). Coding_Format 0x03 (transparent)
        passes our bytes through untouched — GAP/BIS is not a codec test.
        """
        params = struct.pack(
            "<HBBBHH3sB",
            conn_handle,
            0x00,       # Data_Path_Direction: Input
            0x00,       # Data_Path_ID: HCI
            0x03,       # Coding_Format: transparent
            0x0000,     # Company_ID
            0x0000,     # VS_Codec_ID
            b"\x00\x00\x00",  # Controller_Delay
            0x00,       # Codec_Config_Length
        )
        await self._send(
            HCI_LE_SETUP_ISO_DATA_PATH, params, "LE_Setup_ISO_Data_Path"
        )

    # -- ISO SDUs (§5.4.5) ---------------------------------------------------

    async def bis_broadcast(
        self, bis_id: int, data: bytes, *, copies: int = 1,
    ) -> None:
        """Send ``copies`` complete-SDU ISO packets on one BIS.

        Each packet carries the SDU header (Packet_Sequence_Number +
        ISO_SDU_Length with packet status 0b00) followed by the payload, with
        PB_Flag 0b10 (BT_ISO_SINGLE: complete SDU in one HCI packet). TS_Flag
        stays clear — it is permitted with complete SDUs, but PTS matches SDUs
        by content, not by timestamp.
        """
        handle = self.bis_handles[bis_id]
        seq = self._sequence_numbers.get(bis_id, 0)
        for _ in range(copies):
            sdu = struct.pack("<HH", seq & 0xFFFF, len(data) & 0x3FFF) + bytes(data)
            await self._hci.send_iso_data(handle, sdu, pb_flag=0x02, ts_flag=0)
            seq = (seq + 1) & 0xFFFF
        self._sequence_numbers[bis_id] = seq

    # -- teardown ------------------------------------------------------------

    async def terminate_big(
        self, *, big_handle: int = 0x00, reason: int = 0x13,
    ) -> None:
        """LE_Terminate_BIG (§7.8.101). The controller answers with LE BIG
        Terminate, which clears the handle map in ``on_hci_event``."""
        await self._send(
            HCI_LE_TERMINATE_BIG,
            struct.pack("<BB", big_handle, reason),
            "LE_Terminate_BIG",
        )

    # -- HCI event fan-in ------------------------------------------------------

    async def on_hci_event(self, event: HCIEvent) -> None:
        """Consume LE BIG Complete / LE BIG Terminate."""
        if not isinstance(event, HCI_LE_Meta_Event):
            return
        params = bytes(event.subevent_parameters)
        if event.subevent_code == LEMetaSubEvent.LE_CREATE_BIG_COMPLETE:
            if len(params) < 18:
                logger.warning(
                    "IsoBroadcast: truncated LE BIG Complete (%d bytes)", len(params),
                )
                return
            status = params[0]
            num_bis = params[17]
            handles = [
                struct.unpack_from("<H", params, 18 + 2 * i)[0]
                for i in range(num_bis)
                if 18 + 2 * i + 2 <= len(params)
            ]
            logger.debug(
                "IsoBroadcast: LE BIG Complete status=0x%02X handles=%s",
                status, [hex(h) for h in handles],
            )
            waiter = self._big_waiter
            if waiter is not None and not waiter.done():
                waiter.set_result((status, handles))
        elif event.subevent_code == LEMetaSubEvent.LE_TERMINATE_BIG_COMPLETE:
            big_handle = params[0] if params else 0
            reason = params[1] if len(params) > 1 else 0
            logger.debug(
                "IsoBroadcast: LE BIG Terminate big_handle=0x%02X reason=0x%02X",
                big_handle, reason,
            )
            self.bis_handles = {}
            self._sequence_numbers = {}

    async def _send(self, opcode: int, params: bytes, command: str) -> None:
        """Issue an HCI command and surface a non-zero status."""
        event = await self._hci.send_command(_make_cmd(opcode, params))
        status = command_status(event)
        logger.debug(
            "IsoBroadcast: %s opcode=0x%04X params=%s -> status=%s",
            command, opcode, params.hex(),
            "?" if status is None else f"{status:02X}",
        )
        if status:
            logger.warning(
                "IsoBroadcast: %s rejected, status=0x%02X", command, status,
            )


# ---------------------------------------------------------------------------
# BLEScanner
# ---------------------------------------------------------------------------
@dataclass
class _AdvReport:
    """One advertising report, normalised across the two report layouts.

    ``event_type`` keeps the encoding of the layout it came from — the legacy
    subevent uses ordinals (0x00 ADV_IND … 0x04 SCAN_RSP) while the extended
    subevent uses a bitfield — so ``connectable`` and ``is_scan_response`` are
    derived by each parser rather than tested here. The bit positions differ:
    the extended scan-response bit is bit 3 (0x08, BlueZ ``LE_EXT_ADV_SCAN_RSP``)
    and bit 2 (0x04) is *directed* — testing 0x04 there would misread a legacy
    ADV_DIRECT_IND (0x15) as a scan response.
    """

    event_type: int
    address_type: int
    address: bytes
    ad_data: bytes
    rssi: int
    connectable: bool
    is_scan_response: bool


def _parse_legacy_advertising_reports(data: bytes) -> Iterator[_AdvReport]:
    """LE Advertising Report subevent (Vol 4 Part E §7.7.65.2)."""
    if not data:
        return
    count = data[0]
    offset = 1
    for _ in range(count):
        if offset + 10 > len(data):
            return
        event_type = data[offset]
        address_type = data[offset + 1]
        address = bytes(data[offset + 2 : offset + 8])
        data_len = data[offset + 8]
        offset += 9
        if offset + data_len + 1 > len(data):
            return
        ad_data = bytes(data[offset : offset + data_len])
        offset += data_len
        rssi = struct.unpack("b", data[offset : offset + 1])[0]
        offset += 1
        yield _AdvReport(
            event_type=event_type,
            address_type=address_type,
            address=address,
            ad_data=ad_data,
            rssi=rssi,
            connectable=event_type in (0x00, 0x01),
            is_scan_response=event_type == 0x04,
        )


def _parse_extended_advertising_reports(data: bytes) -> Iterator[_AdvReport]:
    """LE Extended Advertising Report subevent (Vol 4 Part E §7.7.65.13).

    Emitted instead of the legacy report once the controller is scanning with
    the extended family — including for ordinary legacy advertisers, whose
    reports then carry Event_Type bit 4 (0x13 ADV_IND, 0x1A SCAN_RSP, …).

    Per report: Event_Type (**2 octets**, LE) + Addr_Type + Address + Primary_PHY
    + Secondary_PHY + SID + TX_Power + RSSI + Periodic_Advertising_Interval(2)
    + Direct_Address_Type + Direct_Address — 24 fixed bytes — then Data_Length +
    Data. Event_Type read as one octet shifts every later field by one and
    garbled every address; verified against on-air BE200 captures.
    """
    if not data:
        return
    count = data[0]
    offset = 1
    for _ in range(count):
        # 24 bytes of per-report fields precede Advertising_Data.
        if offset + 24 > len(data):
            return
        event_type = int.from_bytes(data[offset : offset + 2], "little")
        address_type = data[offset + 2]
        address = bytes(data[offset + 3 : offset + 9])
        rssi = struct.unpack("b", data[offset + 13 : offset + 14])[0]
        data_len = data[offset + 23]
        offset += 24
        if offset + data_len > len(data):
            return
        ad_data = bytes(data[offset : offset + data_len])
        offset += data_len
        logger.debug("ext adv report event=0x%04X addr_type=0x%02X addr=%s",
                     event_type, address_type, address.hex())
        yield _AdvReport(
            event_type=event_type,
            address_type=address_type,
            address=address,
            ad_data=ad_data,
            rssi=rssi,
            connectable=bool(event_type & 0x01),
            is_scan_response=bool(event_type & 0x08),
        )


class BLEScanner:
    """BLE scanning controller, driven by the extended scan family."""

    def __init__(self, hci: object) -> None:
        self._hci = hci
        self._handlers: list[Callable[[ScanResult], object]] = []
        self._active = False
        # Advertising data waiting for its scan-response half, keyed by
        # (address_type, address_bytes) — see _merge_report.
        self._pending_reports: dict[tuple, dict] = {}
        self._pending_flushes: dict[tuple, "asyncio.Task"] = {}
        self._MERGE_WINDOW_S = 0.4

    def on_result(self, handler: Callable[[ScanResult], object]) -> None:
        self._handlers.append(handler)

    @property
    def active(self) -> bool:
        return self._active

    async def on_hci_event(self, event: HCIEvent) -> None:
        if not isinstance(event, HCI_LE_Meta_Event):
            return
        if event.subevent_code == LEMetaSubEvent.LE_ADVERTISING_REPORT:
            reports = _parse_legacy_advertising_reports(event.subevent_parameters)
        elif event.subevent_code == LEMetaSubEvent.LE_EXTENDED_ADVERTISING_REPORT:
            reports = _parse_extended_advertising_reports(event.subevent_parameters)
        else:
            return
        for report in reports:
            self._merge_report(report)

    async def start(self, config: ScanConfig = ScanConfig()) -> None:
        """Start scanning.

        Scan parameters and scan enable both come from the *extended* family.
        A legacy LE_Set_Scan_Parameters (0x200B) is a one-way door: once the
        controller accepts it, every later extended advertising/scanning
        command answers Command Disallowed (0x0C) until the next HCI_Reset, and
        issuing an extended one first blocks the legacy family the same way.
        This stack needs the extended family for the extended advertiser, the
        extended initiator and periodic advertising, so scanning joins it
        rather than fighting it.
        """
        interval = int(config.interval_ms / 0.625)
        window = int(config.window_ms / 0.625)
        scan_type = 0x01 if config.active else 0x00
        params = _extended_scan_params_body(
            config.own_address_type, scan_type, interval, window
        )
        await self._hci.send_command(
            _make_cmd(HCI_LE_SET_EXTENDED_SCAN_PARAMS, params)
        )
        enable = bytes([0x01, 0x01 if config.filter_duplicates else 0x00]) + bytes(4)
        await self._hci.send_command(
            _make_cmd(HCI_LE_SET_EXTENDED_SCAN_ENABLE, enable)
        )
        self._active = True

    async def stop(self) -> None:
        """Stop scanning."""
        await self._hci.send_command(
            _make_cmd(HCI_LE_SET_EXTENDED_SCAN_ENABLE, bytes([0x00, 0x00]) + bytes(4))
        )
        self._active = False
        # Flush anything still inside the merge window: a bounded scan that ends
        # before the window elapses would otherwise drop the devices it just
        # found, which looks exactly like "the IUT never saw them" to PTS.
        for task in list(self._pending_flushes.values()):
            task.cancel()
        self._pending_flushes.clear()
        for key in list(self._pending_reports):
            self._flush_report(key)

    async def _on_advertising_report(self, result: ScanResult) -> None:
        """Called by HCI event router when an advertising report arrives."""
        for handler in self._handlers:
            handler(result)

    def _merge_report(self, report: _AdvReport) -> None:
        """Buffer a report, merging a device's SCAN_RSP half into its EIR.

        Active scanning delivers a device's advertising data and its scan
        response as **two reports**. auto-pts appends one LeAdv per
        DEVICE_FOUND event, so forwarding them separately gives it two partial
        EIRs and its scan-report-and-response check can never match
        (GAP/BROB/OBSV/BV-05/06). Hold the advertising data briefly and emit a
        single merged EIR once the scan response has had a chance to arrive.
        """
        key = (report.address_type, report.address)
        pending = self._pending_reports.get(key)
        if pending is None:
            pending = self._pending_reports[key] = {
                "ad": b"", "rsp": b"", "rssi": report.rssi,
                "event_type": report.event_type,
                "connectable": report.connectable,
            }
        if report.is_scan_response:
            pending["rsp"] += report.ad_data
        else:
            pending["ad"] += report.ad_data
            pending["rssi"] = report.rssi
            pending["event_type"] = report.event_type
            pending["connectable"] = report.connectable
        self._schedule_flush(key, immediate=report.is_scan_response)

    def _schedule_flush(self, key: tuple, *, immediate: bool) -> None:
        """Emit the merged report, right away or after the merge window."""
        task = self._pending_flushes.pop(key, None)
        if task is not None:
            task.cancel()
        if immediate:
            self._flush_report(key)
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._flush_report(key)
            return
        self._pending_flushes[key] = loop.create_task(self._flush_after(key))

    async def _flush_after(self, key: tuple) -> None:
        await asyncio.sleep(self._MERGE_WINDOW_S)
        self._pending_flushes.pop(key, None)
        self._flush_report(key)

    def _flush_report(self, key: tuple) -> None:
        pending = self._pending_reports.pop(key, None)
        if pending is None:
            return
        address_type, address = key
        merged = pending["ad"] + pending["rsp"]
        logger.debug(
            "BLEScanner: report %s ad=%d rsp=%d type=0x%02X",
            BDAddress.from_hci(address, AddressType(address_type)),
            len(pending["ad"]), len(pending["rsp"]), pending["event_type"],
        )
        result = ScanResult(
            address=BDAddress.from_hci(address, AddressType(address_type)),
            rssi=pending["rssi"],
            advertising_data=AdvertisingData.from_bytes(merged),
            connectable=pending["connectable"],
            raw_advertising_data=merged,
        )
        for handler in self._handlers:
            handler(result)

    async def scan_for(
        self, duration: float, config: ScanConfig = ScanConfig(),
    ) -> list[ScanResult]:
        """Scan for a given duration and return collected results."""
        import asyncio
        collected: list[ScanResult] = []
        self.on_result(lambda r: collected.append(r))
        await self.start(config)
        await asyncio.sleep(duration)
        await self.stop()
        return collected


# ---------------------------------------------------------------------------
# BLEConnectionManager
# ---------------------------------------------------------------------------

class BLEConnectionManager:
    """Manages BLE connections (create, cancel, disconnect)."""

    def __init__(self, hci: object) -> None:
        self._hci = hci
        self._connections: dict[int, BLEConnection] = {}
        self._on_connection_handler: Callable[[BLEConnection], object] | None = None
        # Set by the Stack: called with the handle on every IUT-initiated
        # disconnect, so Disconnection_Complete can tell "we hung up" from
        # "the peer dropped the link".
        self.on_local_disconnect: Callable[[int], object] | None = None
        # Own_Address_Type of the most recent initiator request. The Stack reads
        # it on LE Connection Complete to tell whether the link was initiated
        # from a random address (SMP f5/f6 must hash the on-air address).
        self.initiator_own_address_type: int = 0x00

    def on_connection(self, handler: Callable[[BLEConnection], object]) -> None:
        self._on_connection_handler = handler

    async def connect(
        self,
        target: BDAddress,
        config: BLEConnectionConfig = BLEConnectionConfig(),
    ) -> None:
        """Initiate a connection to a target device.

        Prefers the extended initiator when the controller advertises it: an
        extended advertising set makes LE_Create_Connection (0x200D) answer
        Command Disallowed for as long as the set exists, so a device that must
        advertise and initiate at the same time (GAP/PADV/PAST) can only get a
        connection through 0x2043. Controllers without it (BT 4.0/4.1) fall
        back to the legacy command, which is all they have.
        """
        scan_interval = int(config.scan_interval_ms / 0.625)
        scan_window = int(config.scan_window_ms / 0.625)
        min_interval = int(config.min_interval_ms / 1.25)
        max_interval = int(config.max_interval_ms / 1.25)
        supervision = int(config.supervision_timeout_ms / 10)
        self.initiator_own_address_type = int(config.own_address_type) & 0xFF
        capabilities = getattr(self._hci, "supported_commands", None)
        if capabilities is not None and capabilities.has(HCI_LE_EXTENDED_CREATE_CONNECTION):
            params = struct.pack(
                "<BBB6sBHHHHHHHH",
                config.filter_policy & 0xFF,
                config.own_address_type & 0xFF,
                target.type,  # peer address type
                target.to_hci(),
                0x01,  # Initiating_PHYs: LE 1M
                scan_interval, scan_window,
                min_interval, max_interval,
                config.latency,
                supervision,
                0x0000, 0x0000,  # min/max CE length
            )
            await self._hci.send_command(
                _make_cmd(HCI_LE_EXTENDED_CREATE_CONNECTION, params))
            return
        params = struct.pack(
            "<HHBB6sBHHHHHH",
            scan_interval, scan_window,
            config.filter_policy & 0xFF,
            target.type,  # peer address type
            target.to_hci(),
            config.own_address_type & 0xFF,
            min_interval, max_interval,
            config.latency,
            supervision,
            0x0000, 0x0000,  # min/max CE length
        )
        await self._hci.send_command(_make_cmd(HCI_LE_CREATE_CONNECTION, params))

    async def cancel_connect(self) -> None:
        await self._hci.send_command(_make_cmd(HCI_LE_CREATE_CONNECTION_CANCEL))

    async def disconnect(self, handle: int, reason: int = 0x13) -> None:
        # Log the caller: a locally-initiated HCI_Disconnect also reports the
        # configured reason (0x13 by default), so the Disconnection Complete
        # reason alone cannot tell "who disconnected" (PTS vs us).
        import inspect

        caller = ""
        try:
            frame = inspect.stack()[1]
            caller = f"{frame.filename.rsplit('/', 1)[-1]}:{frame.lineno}"
        except Exception:
            pass
        logger.debug(
            "BLEConnectionManager.disconnect handle=0x%04X reason=0x%02X caller=%s",
            handle, reason, caller,
        )
        # Mark this hang-up as ours so the stack's Disconnection_Complete
        # handler can tell it apart from the peer dropping the link (the
        # autonomous peer-drop reconnect must not fire on our own calls).
        on_local_disconnect = getattr(self, "on_local_disconnect", None)
        if on_local_disconnect is not None:
            on_local_disconnect(handle)
        from pybluehost.hci.constants import HCI_DISCONNECT
        params = struct.pack("<HB", handle, reason)
        await self._hci.send_command(_make_cmd(HCI_DISCONNECT, params))
        self._connections.pop(handle, None)

    async def connection_update(
        self,
        handle: int,
        itvl_min: int,
        itvl_max: int,
        latency: int,
        supervision_timeout: int,
    ) -> None:
        """Request new connection parameters via HCI LE_Connection_Update.

        All values are in raw HCI units (interval N*1.25ms, timeout N*10ms).
        On a peripheral the controller translates this into an LL Connection
        Parameters Request; on a central it performs the update directly.
        """
        from pybluehost.hci.constants import HCI_LE_CONNECTION_UPDATE
        params = struct.pack(
            "<HHHHHHH",
            handle, itvl_min, itvl_max, latency, supervision_timeout,
            0x0000, 0x0000,  # min/max CE length
        )
        await self._hci.send_command(_make_cmd(HCI_LE_CONNECTION_UPDATE, params))

    async def subrate_request(
        self,
        handle: int,
        *,
        subrate_min: int,
        subrate_max: int,
        max_latency: int,
        continuation_number: int,
        supervision_timeout: int,
    ) -> None:
        """Start the Connection Subrating procedure: HCI LE_Subrate_Request.

        Only meaningful on a connection that already has subrating enabled (the
        controller announces that through the LE Connection Complete
        event's Subrate_Factor). The outcome comes back asynchronously as an
        **LE Subrate Change** LE Meta event (GAP/CSUB/CSU/BV-01).
        """
        from pybluehost.hci.constants import HCI_LE_SUBRATE_REQUEST
        params = struct.pack(
            "<HHHHHH",
            handle, subrate_min, subrate_max, max_latency,
            continuation_number, supervision_timeout,
        )
        event = await self._hci.send_command(_make_cmd(HCI_LE_SUBRATE_REQUEST, params))
        # The controller answers with Command Status only; a rejection here
        # (0x0C disallowed / 0x11 unsupported) otherwise shows up as PTS
        # failing later on a missing LE Subrate Change event, far from the cause.
        status = (getattr(event, "return_parameters", None) or b"\x00")[0]
        logger.debug(
            "LE_Subrate_Request handle=0x%04X min=%d max=%d latency=%d cont=%d "
            "timeout=%d -> status=0x%02X",
            handle, subrate_min, subrate_max, max_latency, continuation_number,
            supervision_timeout, status,
        )
        if status:
            logger.warning(
                "LE_Subrate_Request rejected by controller, status=0x%02X", status,
            )

    async def set_phy(
        self,
        connection_handle: int,
        tx_phys: int,
        rx_phys: int,
        *,
        phy_options: int = 0,
        timeout_s: float = 5.0,
    ) -> "LEPhyUpdateComplete":
        """Request a PHY update on an LE connection.

        ``tx_phys`` and ``rx_phys`` are bitmasks (``LEPhyMask.LE_1M`` /
        ``LE_2M`` / ``LE_CODED``, OR'd together). Returns the parsed
        ``LE_PHY_Update_Complete`` subevent the controller emits after the
        peer accepts (or rejects) the request. Raises ``asyncio.TimeoutError``
        if the event doesn't arrive within ``timeout_s``.

        Note: passing a tx/rx of 0 + setting bit 0/1 of all_phys lets the
        controller choose. This helper always sets ``all_phys=0`` (explicit
        preference) because that's the common operator intent — set both
        sides to 2M, for example.
        """
        import asyncio
        from pybluehost.hci.packets import HCI_LE_Set_PHY

        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()

        def _on_update(parsed):  # parsed: LEPhyUpdateComplete
            if parsed.connection_handle != connection_handle:
                return
            if not fut.done():
                fut.set_result(parsed)

        self._hci.on_le_phy_update(_on_update)
        try:
            await self._hci.send_command(HCI_LE_Set_PHY(
                connection_handle=connection_handle,
                all_phys=0,
                tx_phys=tx_phys,
                rx_phys=rx_phys,
                phy_options=phy_options,
            ))
            return await asyncio.wait_for(fut, timeout=timeout_s)
        finally:
            try:
                self._hci._le_phy_update_listeners.remove(_on_update)
            except (ValueError, AttributeError):
                pass


# ---------------------------------------------------------------------------
# PrivacyManager
# ---------------------------------------------------------------------------

class PrivacyManager:
    """BLE privacy — resolvable (RPA) and non-resolvable (NRPA) address support.

    RPA = hash(3) || prand(3) with prand[2] top two bits = 01 and
    hash = ah(IRK, prand)   (Core Vol 3 Part C §10.8.2.2).
    NRPA = 46 random bits with the top two bits = 00 (§10.8.2.1).
    """

    def __init__(self, hci: object | None = None) -> None:
        self._hci = hci
        self._enabled = False
        self._irk: bytes | None = None
        self._current_address: bytes | None = None
        self._resolution_enabled = False
        self._rotation_task: "asyncio.Task | None" = None
        self._rotation_interval: float = 0.0
        self._pause_advertising = None
        self._resume_advertising = None
        self._set_advertising_address = None

    @property
    def enabled(self) -> bool:
        """True once a private address has been programmed and resolution on."""
        return self._enabled

    async def enable(self, irk: bytes | None = None) -> None:
        self._enabled = True
        if irk is not None:
            self._irk = bytes(irk)

    async def disable(self) -> None:
        self._enabled = False

    @staticmethod
    def resolve_rpa(rpa: bytes, irk: bytes) -> bool:
        """Check if an on-air RPA was generated with the given IRK.

        The wire form is hash(3) || prand(3), least-significant octet first,
        while ``ah`` (Core Vol 3 Part H §2.2.2) takes r most-significant octet
        first and returns its result the same way — so both halves are reversed
        on the way in.
        """
        from pybluehost.ble.smp import SMPCrypto
        rpa_hash = bytes(rpa[0:3])[::-1]
        prand_value = bytes(rpa[3:6])[::-1]
        return SMPCrypto.ah(irk, prand_value) == rpa_hash

    @staticmethod
    def generate_nrpa(random_bytes: bytes | None = None) -> bytes:
        """A non-resolvable private address: 46 random bits, top two = 00."""
        import os

        raw = bytearray(random_bytes or os.urandom(6))
        raw = bytearray(raw[:6].ljust(6, b"\x00"))
        raw[5] &= 0x3F          # clear the two most significant bits
        if all(b == 0 for b in raw):
            raw[0] = 0x01       # never the all-zero (invalid) address
        return bytes(raw)

    @classmethod
    def generate_rpa(cls, irk: bytes, random_bytes: bytes | None = None) -> bytes:
        """A resolvable private address built from ``irk``.

        ``ah`` (Core Vol 3 Part H §2.2.2) takes r as a 24-bit value with its
        most significant octet first and returns the low 24 bits of the AES
        output in the same order. Addresses go on air least-significant octet
        first, so both the prand handed to ``ah`` and its result are reversed
        relative to the wire form.
        """
        import os

        from pybluehost.ble.smp import SMPCrypto

        # p is wire order: p[0] lands at air octet 3, p[2] at air octet 5.
        prand = bytearray(random_bytes or os.urandom(3))
        prand = bytearray(bytes(prand[:3]).ljust(3, b"\x00"))
        # The two most significant bits of the 24-bit prand live in its most
        # significant octet — wire byte 5 (prand[2]); 01 = resolvable.
        prand[2] = (prand[2] & 0x3F) | 0x40
        value = bytes(prand)[::-1]                          # MSB-first for ah()
        rpa_hash = SMPCrypto.ah(bytes(irk), value)[::-1]    # back to wire order
        return bytes(rpa_hash) + bytes(prand)

    async def set_random_address(self, address: bytes) -> bool:
        """LE_Set_Random_Address. Returns False when the controller refuses.

        The controller answers Command Disallowed (0x0C) when address resolution
        is enabled, so resolution is turned off around the write and restored
        afterwards — without this every re-program (a second test case, or the
        TGAP rotation loop) silently keeps the old address.

        Both resolution toggles happen inside the advertising-paused window:
        the Intel controller answers Command Disallowed (0x0C) to
        LE_Set_Address_Resolution_Enable in *either* direction while an
        advertising set is enabled. Disabling before the pause therefore left
        resolution enabled through the write, and restoring after the resume
        left it disabled for the rest of the session — either way the peer's
        RPA was reported instead of its identity and address-keyed commands
        (GAP/PRIV/CONN/BV-10's disconnect on the LT identity) stopped matching.
        """
        if self._hci is None:
            return False
        restore_resolution = self._resolution_enabled
        # Pause advertising first: it is the only way to make the resolution
        # toggle legal (see above), and the swap itself needs the set disabled.
        paused = False
        if self._pause_advertising is not None:
            paused = bool(await self._pause_advertising())
        if restore_resolution:
            await self.set_address_resolution(False)
        try:
            event = await self._hci.send_command(
                _make_cmd(HCI_LE_SET_RANDOM_ADDRESS, bytes(address[:6]))  # type: ignore[union-attr]
            )
            # With the extended advertising commands in use, LE_Set_Random_Address
            # only reaches scanning and initiating; the address an advertising set
            # advertises with comes from LE_Set_Advertising_Set_Random_Address
            # (Core §7.8.5 note). Set it inside the pause window: §7.8.52 rejects
            # the command while the set is enabled and connectable.
            if self._set_advertising_address is not None:
                await self._set_advertising_address(bytes(address[:6]))
            # Restore resolution *before* advertising comes back: the Intel
            # controller answers Command Disallowed (0x0C) to
            # LE_Set_Address_Resolution_Enable while an advertising set is
            # enabled. A rotation that resumed advertising first left
            # resolution off for the rest of the session, so an incoming
            # connection from the peer's RPA was reported as the RPA instead of
            # its identity — and every address-keyed command afterwards
            # (GAP/PRIV/CONN/BV-10's disconnect on the LT identity) missed.
            if restore_resolution:
                await self.set_address_resolution(True)
        finally:
            if paused and self._resume_advertising is not None:
                await self._resume_advertising()
        status = getattr(event, "return_parameters", b"\x00")[:1]
        ok = not status or status[0] == 0x00
        if not ok:
            logger.warning(
                "PrivacyManager: LE_Set_Random_Address rejected, status=0x%02X",
                status[0],
            )
        else:
            self._current_address = bytes(address[:6])
            logger.debug(
                "PrivacyManager: programmed private address %s",
                bytes(address[:6]).hex(),
            )
        return ok

    async def set_address_resolution(self, enable: bool) -> bool:
        """LE_Set_Address_Resolution_Enable; True on success. """
        if self._hci is None:
            return False
        event = await self._hci.send_command(  # type: ignore[union-attr]
            _make_cmd(HCI_LE_SET_ADDRESS_RESOLUTION_ENABLE,
                      bytes([0x01 if enable else 0x00])))
        status = getattr(event, "return_parameters", b"\x00")[:1]
        ok = not status or status[0] == 0x00
        if ok:
            self._resolution_enabled = bool(enable)
        else:
            # Worth a warning: a resolution state that silently stays off is
            # what strands address-keyed commands after a privacy rotation.
            logger.warning(
                "PrivacyManager: LE_Set_Address_Resolution_Enable(%s) rejected, status=0x%02X",
                enable, status[0] if status else -1,
        )
        return ok

    async def add_to_resolving_list(
        self, peer_identity_address: bytes, peer_irk: bytes,
        local_irk: bytes = bytes(16),
    ) -> None:
        """LE_Add_Device_To_Resolving_List (peer id address + both IRKs)."""
        if self._hci is None:
            return
        params = (
            bytes([0x00])                                   # peer address type
            + bytes(peer_identity_address[:6]).ljust(6, b"\x00")
            + bytes(peer_irk[:16]).ljust(16, b"\x00")
            + bytes(local_irk[:16]).ljust(16, b"\x00")
        )
        await self._hci.send_command(  # type: ignore[union-attr]
            _make_cmd(HCI_LE_ADD_DEVICE_TO_RESOLVING_LIST, params)
        )

    # -- address rotation --------------------------------------------------

    async def start_rotation(self, interval_s: float) -> None:
        """Re-generate the private address every ``interval_s`` seconds.

        TGAP(private_addr_int) requires the IUT to change a private address on
        a schedule; PTS observes the advertising events and fails the case if
        the address never changes (GAP/BROB/BCST/BV-04). Idempotent.
        """
        await self.stop_rotation()
        self._rotation_interval = float(interval_s)
        self._rotation_task = asyncio.ensure_future(self._rotate_loop())

    async def stop_rotation(self) -> None:
        task = getattr(self, "_rotation_task", None)
        self._rotation_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def _rotate_loop(self) -> None:
        interval = getattr(self, "_rotation_interval", 5.0)
        while True:
            await asyncio.sleep(interval)
            try:
                address = (
                    self.generate_rpa(self._irk) if self._irk
                    else self.generate_nrpa()
                )
                # set_random_address pauses/resumes advertising around the swap.
                await self.set_random_address(address)
                logger.debug(
                    "PrivacyManager: rotated private address to %s", address.hex(),
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("PrivacyManager: address rotation failed")

    def set_rotation_hooks(self, pause, resume, set_advertising_address=None) -> None:
        """Register the (async) pause/resume pair used around an address swap.

        ``set_advertising_address`` (optional) programs the *advertising set's*
        address. With the extended advertising commands in use,
        LE_Set_Random_Address only reaches scanning and initiating — an
        advertising set with Own_Address_Type 0x01 stays un-addressable without
        this, and LE_Set_Extended_Advertising_Enable answers Invalid HCI Command
        Parameters (0x12).
        """
        self._pause_advertising = pause
        self._resume_advertising = resume
        self._set_advertising_address = set_advertising_address


# ---------------------------------------------------------------------------
# WhiteList
# ---------------------------------------------------------------------------

class WhiteList:
    """BLE White List management via HCI commands."""

    def __init__(self, hci: object) -> None:
        self._hci = hci
        self._entries: list[tuple[BDAddress, int]] = []

    async def add(self, address: BDAddress, address_type: int = 0x00) -> None:
        params = bytes([address_type]) + address.to_hci()
        await self._hci.send_command(_make_cmd(HCI_LE_ADD_DEVICE_TO_WHITE_LIST, params))
        self._entries.append((address, address_type))

    async def remove(self, address: BDAddress, address_type: int = 0x00) -> None:
        params = bytes([address_type]) + address.to_hci()
        await self._hci.send_command(_make_cmd(HCI_LE_REMOVE_DEVICE_FROM_WHITE_LIST, params))
        self._entries = [(a, t) for a, t in self._entries if a != address]

    async def clear(self) -> None:
        await self._hci.send_command(_make_cmd(HCI_LE_CLEAR_WHITE_LIST))
        self._entries.clear()

    @property
    def entries(self) -> list[tuple[BDAddress, int]]:
        return list(self._entries)


# ---------------------------------------------------------------------------
# ExtendedAdvertiser (BT 5.0+)
# ---------------------------------------------------------------------------

class ExtendedAdvertiser:
    """BT 5.0 Extended Advertising — multiple advertising sets, coded PHY."""

    def __init__(self, hci: object) -> None:
        self._hci = hci
        self._sets: dict[int, ExtAdvertisingConfig] = {}

    async def create_set(self, config: ExtAdvertisingConfig) -> None:
        """LE_Set_Extended_Advertising_Parameters (Core §7.8.53, 25 bytes).

        Field order: handle(1) properties(2) interval_min(3) interval_max(3)
        channel_map(1) own_addr_type(1) peer_addr_type(1) peer_addr(6)
        filter_policy(1) tx_power(1) primary_phy(1) secondary_max_skip(1)
        secondary_phy(1) sid(1) scan_req_notification(1).

        Periodic advertising requires a set created here that advertises with
        EXTENDED PDUs — the controller rejects
        LE_Set_Periodic_Advertising_Parameters on a legacy-PDU set.
        """
        params = (
            bytes([config.adv_handle])
            + struct.pack("<H", config.properties)
            + int(config.interval_min).to_bytes(3, "little")
            + int(config.interval_max).to_bytes(3, "little")
            + bytes([
                config.channel_map,
                config.own_address_type,
                config.peer_address_type,
            ])
            + bytes(config.peer_address[:6]).ljust(6, b"\x00")
            + bytes([
                config.filter_policy,
                config.tx_power & 0xFF,
                config.primary_phy,
                config.max_skip,
                config.secondary_phy,
                config.sid,
                0x00,  # Scan_Request_Notification_Enable
            ])
        )
        await self._hci.send_command(
            _make_cmd(HCI_LE_SET_EXTENDED_ADVERTISING_PARAMS, params)
        )
        self._sets[config.adv_handle] = config

    async def set_data(self, handle: int, ad_data) -> None:
        raw = _ad_to_raw(ad_data)
        # Handle, Operation (0x03 = complete), Fragment_Preference, Length — the
        # extended commands carry one more header byte than the legacy ones.
        params = struct.pack("<BBBB", handle, 0x03, 0x00, len(raw)) + raw
        await self._hci.send_command(
            _make_cmd(HCI_LE_SET_EXTENDED_ADVERTISING_DATA, params)
        )

    async def start(
        self,
        handles: list[int],
        durations: list[float] | None = None,
    ) -> None:
        """Start extended advertising on the given handles."""
        num_sets = len(handles)
        params = bytearray([0x01, num_sets])  # enable=1, num_sets
        for i, h in enumerate(handles):
            duration = int((durations[i] if durations else 0) * 100)  # in 10ms units
            params.extend(struct.pack("<BHB", h, duration, 0))
        await self._hci.send_command(
            _make_cmd(HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE, bytes(params))
        )

    async def stop(self, handles: list[int] | None = None) -> None:
        """Stop extended advertising."""
        if handles is None:
            handles = list(self._sets.keys())
        num_sets = len(handles)
        params = bytearray([0x00, num_sets])  # enable=0
        for h in handles:
            params.extend(struct.pack("<BHB", h, 0, 0))
        await self._hci.send_command(
            _make_cmd(HCI_LE_SET_EXTENDED_ADVERTISING_ENABLE, bytes(params))
        )

    async def remove_set(self, handle: int) -> None:
        self._sets.pop(handle, None)
