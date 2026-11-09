"""GAP BTP service — translates GAP opcodes into Phase 1 IutActions calls.

See design spec §11.5 + auto-pts doc/btp_gap.txt for the wire format.

Command handlers land in P.6 Tasks 2-7; this file is the skeleton.
"""
from __future__ import annotations

import asyncio
import logging
import os
import struct
from typing import TYPE_CHECKING

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import BtpFrame
from pybluehost.pts.btp.services.base import BtpService

if TYPE_CHECKING:
    from pybluehost.pts.actions import IutActions
    from pybluehost.pts.btp.tester import BtpTester

logger = logging.getLogger(__name__)

# GAP settings bitmap bits (auto-pts defs.py GAP_SETTINGS_*). NOTE: there is no
# "periodic advertising" bit — bit 13 is Privacy, so PADV_START must NOT touch
# the bitmap (setting it makes auto-pts believe privacy is enabled).
_GAP_SETTINGS_PRIVACY = 13
_GAP_SETTINGS_EXTENDED_ADVERTISING = 17
# TGAP(lim_adv_timeout): how long the IUT may keep advertising after entering
# Limited Discoverable mode. GAP.TS LIMM/* pass criteria: past this deadline
# the LT must not receive any advertising carrying the Limited flag — matches
# the workspace default of TSPX_lim_adv_timeout (30720 ms; zephyr/bluez
# reference IUTs set the same value).
_LIM_ADV_TIMEOUT_S = 30.72


def _decode_bd_addr(addr_bytes: bytes, addr_type: int = 0) -> "BDAddress":
    """6-byte BTP wire address (little-endian BD_ADDR) → BDAddress.

    ``BDAddress.address`` is the canonical big-endian (display) order, so build
    via ``from_hci`` which reverses the little-endian wire bytes. ``addr_type``
    follows the BTP byte: 0=PUBLIC, 1=RANDOM.
    """
    from pybluehost.core.address import AddressType, BDAddress
    atype = AddressType.RANDOM if addr_type == 1 else AddressType.PUBLIC
    return BDAddress.from_hci(bytes(addr_bytes), type=atype)


def _encode_bd_addr(addr) -> bytes:
    """BDAddress → 6-byte little-endian wire form (matches BTP addr field)."""
    if addr is None:
        return bytes(6)
    to_hci = getattr(addr, "to_hci", None)
    if callable(to_hci):
        return bytes(to_hci())[:6].ljust(6, b"\x00")
    # Test fakes may carry raw wire bytes directly.
    raw = getattr(addr, "address", None)
    if raw is None:
        raw = getattr(addr, "bytes", None)
    if raw is None:
        try:
            raw = bytes(addr)
        except Exception:
            raw = bytes(6)
    return bytes(raw)[:6].ljust(6, b"\x00")


# AD Type for the Flags structure.
_AD_TYPE_FLAGS = 0x01
# AD Flags bits.
_AD_FLAG_LIMITED_DISC = 0x01
_AD_FLAG_GENERAL_DISC = 0x02
_AD_FLAG_BREDR_NOT_SUPPORTED = 0x04

# BLE advertising PDU types (HCI LE Set Advertising Parameters).
_ADV_IND = 0x00          # connectable + scannable, undirected
_ADV_DIRECT_IND = 0x01   # connectable, directed (high duty cycle)
_ADV_SCAN_IND = 0x02     # non-connectable, scannable, undirected
_ADV_NONCONN_IND = 0x03  # non-connectable, non-scannable, undirected


def _parse_btp_ad(data: bytes) -> "list[tuple[int, bytes]]":
    """Parse BTP advertising data into a list of (ad_type, ad_data).

    BTP START_ADVERTISING carries AD structures as ``{AD_Type, AD_Len, AD_DATA}``
    (type FIRST, AD_Len = len(AD_DATA)) — NOT the on-air ``[len][type][data]``
    layout the controller expects. Split into typed fields here; re-serialise to
    the controller format with :func:`_ad_to_hci`.
    """
    out: list[tuple[int, bytes]] = []
    i = 0
    while i + 2 <= len(data):
        ad_type = data[i]
        ad_len = data[i + 1]
        i += 2
        if i + ad_len > len(data):
            break
        out.append((ad_type, bytes(data[i:i + ad_len])))
        i += ad_len
    return out


def _ad_flags_from_eir(eir: bytes) -> int:
    """Extract the AD Flags value from an on-air EIR (``[len][type][data]``).

    Returns 0 when no Flags AD type (0x01) is present — a device without a
    Flags structure is not in any discoverable mode, so a discovery procedure
    must not report it.
    """
    i = 0
    n = len(eir)
    while i + 2 <= n:
        ad_len = eir[i]
        if ad_len == 0:
            break
        if i + 1 + ad_len > n:
            break
        if eir[i + 1] == _AD_TYPE_FLAGS and ad_len >= 2:
            return eir[i + 2] & 0xFF
        i += 1 + ad_len
    return 0


def _ad_to_hci(structs: "list[tuple[int, bytes]]") -> bytes:
    """Serialise (ad_type, ad_data) structs to on-air ``[len][type][data]``."""
    out = bytearray()
    for ad_type, ad_data in structs:
        out.append(1 + len(ad_data))
        out.append(ad_type)
        out.extend(ad_data)
    return bytes(out)


def _apply_mode_to_adv(
    structs: "list[tuple[int, bytes]]", *, connectable: bool, discoverable: int,
    scannable: bool,
) -> tuple[int, "list[tuple[int, bytes]]"]:
    """Apply GAP connectable/discoverable mode to parsed AD structs.

    Injects (or overrides) the AD Flags field to carry the discoverable mode +
    BR/EDR-not-supported, and returns the advertising PDU type for connectability.
    PTS decides DISC verdicts from the on-air AD Flags + PDU type.
    """
    if discoverable == 1:
        flags = _AD_FLAG_GENERAL_DISC | _AD_FLAG_BREDR_NOT_SUPPORTED
    elif discoverable == 2:
        flags = _AD_FLAG_LIMITED_DISC | _AD_FLAG_BREDR_NOT_SUPPORTED
    else:
        flags = _AD_FLAG_BREDR_NOT_SUPPORTED

    for idx, (ad_type, _ad_data) in enumerate(structs):
        if ad_type == _AD_TYPE_FLAGS:
            structs[idx] = (_AD_TYPE_FLAGS, bytes([flags]))
            break
    else:
        structs = [(_AD_TYPE_FLAGS, bytes([flags]))] + structs

    if connectable:
        adv_type = _ADV_IND
    elif scannable:
        adv_type = _ADV_SCAN_IND
    else:
        adv_type = _ADV_NONCONN_IND
    return adv_type, structs


class GapService(BtpService):
    """LE GAP BTP service. Routes opcodes to IutActions calls; emits async
    GAP events to autoptsclient via BtpTester.emit_event."""

    SERVICE_ID = op.SERVICE_GAP

    def __init__(self, *, actions: "IutActions", tester: "BtpTester") -> None:
        self._actions = actions
        self._tester = tester
        self._current_settings: int = 0
        self._controller_index: int = 0
        # Connectable / discoverable mode for the NEXT start_advertising. The
        # auto-pts set_* commands only toggle settings bits; the real controller
        # advertising must reflect them in the adv PDU type + AD Flags byte, so
        # we track the intended mode here and apply it in _handle_op_0a.
        self._adv_connectable: bool = False
        self._discoverable_mode: int = 0  # 0=non, 1=general, 2=limited
        # Active GAP discovery mode for the running scan, set by START_DISCOVERY.
        # "general" reports General+Limited discoverable devices, "limited" only
        # Limited, "observe" reports everything (observation is a raw scan).
        self._discovery_mode: str = "general"
        # Stored security/pairing config (0x15-0x21 handlers); see handler docs.
        self._filter_accept_list: list = []
        self._mitm: bool = False
        self._privacy: bool = False
        # Bonded peers' IRKs, snapshotted per START_DISCOVERY for host-side
        # RPA resolution — see _refresh_rpa_irks.
        self._rpa_irks: list = []
        # Session key + IV for Encrypted Advertising Data, pushed by
        # SET_EAD_KEY_MATERIAL (0x31).
        self._ead_material: object | None = None
        self._sc_only: bool = False
        self._sc: bool = False
        # Armed when the IUT enters Limited Discoverable mode; fires after
        # TGAP(lim_adv_timeout) to take the Limited-flag advertising off the
        # air (LIMM/* pass criteria).
        self._lim_adv_task: "asyncio.Task | None" = None
        # Set when the SMP stack surfaces a displayed passkey (display role);
        # PAIR waits on it so auto-pts's "enter Secure Id" WID (1002) can read
        # stack.gap.passkey.data instead of racing the background pairing.
        self._passkey_displayed: asyncio.Event | None = None
        self._min_enc_key_size: int = 0
        self._ext_advertising: bool = False
        # Background CREATE_BIG chain (BIG + per-BIS ISO data paths); tests
        # await it to observe the data-path events it emits.
        self._big_task: "asyncio.Task | None" = None

    async def _handle_op_01(self, controller_index: int, data: bytes):
        """READ_SUPPORTED_COMMANDS — bitfield of supported GAP opcodes."""
        cmds = self.supported_commands()
        if not cmds:
            return op.BTP_STATUS_SUCCESS, bytes(0)
        n_bytes = (max(cmds) // 8) + 1
        out = bytearray(n_bytes)
        for code in cmds:
            # Bit n = opcode n (auto-pts Stack.is_cmd_supported checks 1 << cmd).
            out[code // 8] |= 1 << (code % 8)
        return op.BTP_STATUS_SUCCESS, bytes(out)

    async def _handle_op_02(self, controller_index: int, data: bytes):
        """READ_CONTROLLER_INDEX_LIST — PyBlueHost is single-controller, index 0."""
        return op.BTP_STATUS_SUCCESS, bytes([1, 0])

    async def _handle_op_03(self, controller_index: int, data: bytes):
        """READ_CONTROLLER_INFO — BD_ADDR + settings + class_of_device + name."""
        local_addr = getattr(self._actions, "local_address", None)
        if local_addr is not None and hasattr(local_addr, "to_hci"):
            # BDAddress: auto-pts decodes the address little-endian
            # (le_bytes_to_hex_str), so send HCI byte order.
            addr_bytes = local_addr.to_hci()
        elif isinstance(local_addr, (bytes, bytearray)) and len(local_addr) == 6:
            addr_bytes = bytes(local_addr)
        else:
            addr_bytes = bytes(6)

        # PyBlueHost capability advertisement (auto-pts defs.py settings bits):
        # CONNECTABLE=1, BONDABLE=4, LE=9, ADVERTISING=10, PRIVACY=13,
        # SC_ONLY=16. PRIVACY must be advertised or every GAP/PRIV and
        # private-address case bails out at `if not stack.gap.iut_has_privacy()`.
        supported_settings = 0
        for bit in (1, 4, 9, 10, _GAP_SETTINGS_PRIVACY, 16):
            supported_settings |= (1 << bit)
        current_settings = self._current_settings

        out = bytearray()
        out.extend(addr_bytes)
        out.extend(supported_settings.to_bytes(4, "little"))
        out.extend(current_settings.to_bytes(4, "little"))
        out.extend(bytes(3))                                  # class_of_device = 0
        name = b"PyBlueHost"
        out.extend(name.ljust(249, b"\x00"))                  # 249-byte name
        out.extend(name[:11].ljust(11, b"\x00"))              # 11-byte short name
        return op.BTP_STATUS_SUCCESS, bytes(out)

    async def _handle_op_04(self, controller_index: int, data: bytes):
        """RESET — clear per-session GAP state."""
        self._current_settings = 0
        return op.BTP_STATUS_SUCCESS, b""

    _SETTINGS_BITS = {
        op.OP_GAP_SET_POWERED: 0,
        op.OP_GAP_SET_CONNECTABLE: 1,
        op.OP_GAP_SET_FAST_CONNECTABLE: 2,
        op.OP_GAP_SET_DISCOVERABLE: 3,
        op.OP_GAP_SET_BONDABLE: 4,
        op.OP_GAP_SET_PRIVACY: _GAP_SETTINGS_PRIVACY,
        op.OP_GAP_SET_SC_ONLY: 16,
    }

    def _set_settings_bit(self, opcode: int, value: int) -> bytes:
        bit = self._SETTINGS_BITS[opcode]
        if value:
            self._current_settings |= (1 << bit)
        else:
            self._current_settings &= ~(1 << bit)
        return self._current_settings.to_bytes(4, "little")

    async def _handle_op_05(self, controller_index: int, data: bytes):
        """SET_POWERED."""
        if len(data) != 1:
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, self._set_settings_bit(op.OP_GAP_SET_POWERED, data[0])

    async def _handle_op_06(self, controller_index: int, data: bytes):
        """SET_CONNECTABLE — LE advertising mode AND BR/EDR page scan."""
        if len(data) != 1:
            return op.BTP_STATUS_FAILED, b""
        self._adv_connectable = bool(data[0])
        # BR/EDR: page scan on/off so the Lower Tester can page us (SDP/RFCOMM
        # server-role cases). ClassicDiscoverability handles the HCI writes.
        cd = getattr(self._actions._stack.gap, "classic_discoverability", None)             if getattr(self._actions, "_stack", None) is not None else None
        if cd is not None:
            try:
                import asyncio
                asyncio.get_running_loop().create_task(cd.set_connectable(bool(data[0])))
            except Exception:
                logger.exception("GAP SET_CONNECTABLE: classic page scan failed")
        return op.BTP_STATUS_SUCCESS, self._set_settings_bit(op.OP_GAP_SET_CONNECTABLE, data[0])

    async def _handle_op_07(self, controller_index: int, data: bytes):
        """SET_FAST_CONNECTABLE."""
        if len(data) != 1:
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, self._set_settings_bit(op.OP_GAP_SET_FAST_CONNECTABLE, data[0])

    async def _handle_op_08(self, controller_index: int, data: bytes):
        """SET_DISCOVERABLE. Upstream payload is 1 byte (discoverable flag);
        some auto-pts variants append a 2-byte duration — we accept either."""
        if len(data) < 1:
            return op.BTP_STATUS_FAILED, b""
        self._discoverable_mode = data[0]  # 0=non, 1=general, 2=limited
        # TGAP(lim_adv_timeout) runs from the moment the IUT *enters* Limited
        # Discoverable mode. Arm once on entry; re-entering (WID 50's
        # stop->set_limited->start sequence) must not push the deadline out.
        if self._discoverable_mode == 2:
            if self._lim_adv_task is None or self._lim_adv_task.done():
                self._lim_adv_task = asyncio.create_task(
                    self._stop_limited_advertising_after_tgap())
        elif self._lim_adv_task is not None and not self._lim_adv_task.done():
            self._lim_adv_task.cancel()
        # BR/EDR: inquiry scan for general/limited discoverable (SDP SR cases —
        # PTS inquires for the IUT before paging).
        cd = getattr(self._actions._stack.gap, "classic_discoverability", None)             if getattr(self._actions, "_stack", None) is not None else None
        if cd is not None and self._discoverable_mode:
            try:
                asyncio.get_running_loop().create_task(cd.set_discoverable(True))
            except Exception:
                logger.exception("GAP SET_DISCOVERABLE: classic inquiry scan failed")
        return op.BTP_STATUS_SUCCESS, self._set_settings_bit(op.OP_GAP_SET_DISCOVERABLE, data[0])

    async def _stop_limited_advertising_after_tgap(self) -> None:
        """TGAP(lim_adv_timeout) elapsed in Limited Discoverable mode: take the
        Limited-flag advertising off the air (GAP.TS LIMM/*: past the deadline
        the LT must receive none) and re-sync the auto-pts model so a later
        gap_start_advertising isn't short-circuited by a stale ADVERTISING bit
        (the GAP/SEC/SEM BV-56 model-drift family)."""
        try:
            await asyncio.sleep(_LIM_ADV_TIMEOUT_S)
        except asyncio.CancelledError:
            return
        if self._discoverable_mode != 2:
            return
        if not self._current_settings & (1 << 10):
            return  # explicit STOP_ADVERTISING already silenced the air
        logger.info(
            "TGAP(lim_adv_timeout) elapsed in Limited Discoverable mode — "
            "stopping advertising")
        try:
            await self._actions.stop_advertising()
        except Exception:
            logger.exception(
                "limited-discoverable TGAP stop: actions.stop_advertising raised")
            return
        self._current_settings &= ~(1 << 10)
        self._emit_event(
            op.OP_GAP_EVENT_NEW_SETTINGS,
            self._current_settings.to_bytes(4, "little"))

    async def _handle_op_09(self, controller_index: int, data: bytes):
        """SET_BONDABLE — update GAP settings bit AND the SMP bonding flag.

        The SMP layer reads its bondable flag when building the Pairing
        Request/Response AuthReq; flipping only the settings bitmap would leave
        the on-air bonding bit stale (PTS SM tests toggle this per-case).
        """
        if len(data) != 1:
            return op.BTP_STATUS_FAILED, b""
        self._actions.set_bondable(bool(data[0]))
        return op.BTP_STATUS_SUCCESS, self._set_settings_bit(op.OP_GAP_SET_BONDABLE, data[0])

    # ---- Start / Stop Advertising ------------------------------------------

    async def _handle_op_0a(self, controller_index: int, data: bytes):
        """START_ADVERTISING — upstream layout:
        adv_data_len(1), scan_rsp_len(1), adv_data, scan_rsp,
        duration(4 LE), own_addr_type(1).
        """
        if len(data) < 7:    # at least 2 lengths + 4 duration + 1 own_addr_type
            return op.BTP_STATUS_FAILED, b""
        offset = 0
        adv_data_len = data[offset]; offset += 1
        scan_rsp_len = data[offset]; offset += 1
        if offset + adv_data_len + scan_rsp_len + 5 > len(data):
            return op.BTP_STATUS_FAILED, b""
        adv_data = data[offset:offset + adv_data_len]
        offset += adv_data_len
        scan_rsp = data[offset:offset + scan_rsp_len]
        offset += scan_rsp_len
        # Tail: duration(4 LE) + own_addr_type(1). auto-pts's
        # OwnAddrType is 0=identity, 1=resolvable-private, 2=non-resolvable-
        # private; hdl_wid_79/80 use it to ask for a private address
        # (GAP/BROB/BCST/BV-03/04/05). Dropping it means we advertise from the
        # public address and every private-address case fails.
        own_addr_type = data[offset + 4] if offset + 4 < len(data) else 0
        # Privacy mode (SET_PRIVACY on) means the peripheral advertises from a
        # resolvable private address, but auto-pts's generic WID 91/92 path
        # does not model that setting and always asks for identity
        # (OwnAddrType 0). GAP/PRIV/CONN/BV-10's Lower Tester resolves the RPA
        # we advertise, so the IUT's own privacy state wins over the default;
        # an explicit private request (1/2, BCST/BV-03/04/05) is untouched.
        if own_addr_type == 0 and self._privacy:
            own_addr_type = 1
        # BTP AD structs are {type, len, data}; convert to on-air [len][type][data]
        # and apply the connectable/discoverable mode (PDU type + AD Flags byte).
        adv_structs = _parse_btp_ad(bytes(adv_data))
        scan_structs = _parse_btp_ad(bytes(scan_rsp))
        # The scan/connection requests are filtered by the controller when an
        # accept list is programmed (GAP/BROB/BCST/BV-05-C expects the IUT to
        # ignore the Lower Tester scan requests because only the accept-listed
        # address may elicit a scan response).
        adv_type, adv_structs = _apply_mode_to_adv(
            adv_structs,
            connectable=self._adv_connectable,
            discoverable=self._discoverable_mode,
            scannable=bool(scan_structs),
        )
        # The EAD cases (GAP/ADV/BV-21) are decided entirely by what ends up on
        # the air, and the AD budget is 31 octets — log the type list and total
        # so an oversize or dropped structure is visible without a sniffer.
        hci_adv = _ad_to_hci(adv_structs)
        logger.debug(
            "GAP START_ADVERTISING adv_type=0x%02X structs=%s total=%d bytes",
            adv_type, [(hex(t), len(d)) for t, d in adv_structs], len(hci_adv),
        )
        if len(hci_adv) > 31:
            logger.warning(
                "GAP START_ADVERTISING: advertising data is %d octets, over the "
                "31-octet legacy limit — the controller will reject or truncate it",
                len(hci_adv),
            )
        try:
            await self._actions.advertise(
                adv_type=adv_type,
                data=hci_adv,
                scan_rsp=_ad_to_hci(scan_structs) if scan_structs else b"",
                # 0x03 = process scan+connection requests only from accept-listed
                # devices; the WID 80 accept list deliberately excludes the PTS
                # dongle, so its scan requests must be ignored on air.
                filter_policy=0x03 if self._filter_accept_list else 0x00,
                own_addr_type=own_addr_type,
            )
        except Exception:
            logger.exception("GAP START_ADVERTISING: actions.advertise raised")
            return op.BTP_STATUS_FAILED, b""
        self._current_settings |= (1 << 10)   # GAP_SETTINGS_ADVERTISING
        return op.BTP_STATUS_SUCCESS, self._current_settings.to_bytes(4, "little")

    async def _handle_op_0b(self, controller_index: int, data: bytes):
        """STOP_ADVERTISING — no body."""
        try:
            await self._actions.stop_advertising()
        except Exception:
            logger.exception("GAP STOP_ADVERTISING: actions.stop_advertising raised")
            return op.BTP_STATUS_FAILED, b""
        self._current_settings &= ~(1 << 10)  # GAP_SETTINGS_ADVERTISING
        return op.BTP_STATUS_SUCCESS, self._current_settings.to_bytes(4, "little")

    # ---- Start / Stop Discovery -------------------------------------------

    async def _maybe_disable_controller_resolution(self) -> None:
        """PYBLUEHOST_SCAN_RESOLUTION=off: switch RPA resolution to host-side.

        On the 2026-10 BE200 rig, with controller address resolution enabled
        and the peer's identity in the resolving list, the LT's post-bond RPA
        advertisement never surfaced in extended scan reports (0 of 645
        reports in the observation window, across attempts) while RPA-shaped
        reports from non-resolving-list devices flowed fine — so the firmware
        appears to drop reports it resolves. Flipping to host-side resolution
        (see _resolve_rpa_identity) delivers the raw RPA and resolves here.
        """
        if os.environ.get("PYBLUEHOST_SCAN_RESOLUTION", "").strip().lower() != "off":
            return
        privacy = getattr(
            getattr(getattr(self._actions, "stack", None), "gap", None),
            "ble_privacy",
            None,
        )
        if privacy is None or not hasattr(privacy, "set_address_resolution"):
            return
        try:
            await privacy.set_address_resolution(False)
            logger.info("GAP START_DISCOVERY: controller RPA resolution disabled (host-side resolution active)")
        except Exception:
            logger.exception("GAP START_DISCOVERY: disabling controller RPA resolution failed")

    async def _refresh_rpa_irks(self) -> None:
        """Snapshot the bonded peers' IRKs for host-side RPA resolution.

        auto-pts's check_discovery_results compares DEVICE_FOUND against the
        peer's **identity** address. If the controller reports an unresolved
        resolvable-private address (resolving list not programmed, firmware
        that declines to resolve), the report can never match. The bonds are
        read once per START_DISCOVERY — the RPA cases pair *before* they scan,
        so the peer IRK is in storage by then.
        """
        self._rpa_irks = []
        stack = getattr(self._actions, "stack", None)
        if stack is None:
            return
        storage = getattr(getattr(stack, "config", None), "bond_storage", None)
        if storage is None:
            storage = getattr(getattr(stack, "_smp", None), "_bond_storage", None)
        if storage is None or not hasattr(storage, "list_bonds"):
            return
        try:
            bonds = await storage.list_bonds()
        except Exception:
            logger.exception("GAP: list_bonds failed; host-side RPA resolution off")
            return
        for bond in bonds:
            irk = getattr(bond, "irk", None)
            peer = getattr(bond, "peer_address", None)
            if not irk or peer is None:
                continue
            to_hci = getattr(peer, "to_hci", None)
            addr_bytes = to_hci() if callable(to_hci) else bytes(peer)[:6]
            self._rpa_irks.append((bytes(irk), int(getattr(bond, "address_type", 0)), addr_bytes))

    def _resolve_rpa_identity(self, addr_type_value: int, addr_bytes: bytes):
        """Resolve a resolvable-private report address against the bond IRKs.

        Returns (addr_type, addr_bytes) — identity when a bond's IRK matches,
        the input otherwise. ``resolve_rpa`` handles the wire-order reversal
        inside ``ah`` (Core Vol 3 Part H §2.2.2).
        """
        if addr_type_value != 0x01:  # only resolvable private addresses
            return addr_type_value, addr_bytes
        for irk, ident_type, ident_bytes in self._rpa_irks:
            from pybluehost.ble.gap import PrivacyManager

            if PrivacyManager.resolve_rpa(addr_bytes, irk):
                logger.debug(
                    "GAP DEVICE_FOUND: resolved RPA %s -> identity %s",
                    addr_bytes.hex(), ident_bytes.hex(),
                )
                return ident_type, ident_bytes
        return addr_type_value, addr_bytes

    async def _handle_op_0c(self, controller_index: int, data: bytes):
        """START_DISCOVERY. Body: flags(u8) — auto-pts's GAP_DISCOVERY_FLAG_*:
        LE=0x01, BR/EDR=0x02, LIMITED=0x04, LE_ACTIVE_SCAN=0x08, LE_OBSERVE=0x10.

        The active-scan bit is **0x08** (bit 3), not 0x04 — 0x04 is the
        *limited* discovery bit. Reading the wrong one made every active scan a
        passive one: no SCAN_REQ went out, no scan response came back, and every
        report had an empty response half (GAP/BROB/OBSV/BV-05/06, whose WID
        checks the scan-response payload).
        """
        if len(data) != 1:
            return op.BTP_STATUS_FAILED, b""
        flags = data[0]
        active = bool(flags & 0x08)
        if flags & 0x10:
            self._discovery_mode = "observe"
        elif flags & 0x04:
            self._discovery_mode = "limited"
        else:
            self._discovery_mode = "general"
        await self._maybe_disable_controller_resolution()
        await self._refresh_rpa_irks()
        try:
            if flags & 0x02:  # BR/EDR transport: classic inquiry
                await self._actions.inquire(on_result=self._on_inquiry_result)
            else:
                await self._actions.scan(active=active,
                                         on_result=self._on_scan_result)
        except Exception:
            logger.exception("GAP START_DISCOVERY: scan() raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_0d(self, controller_index: int, data: bytes):
        """STOP_DISCOVERY. No body."""
        stop_fn = getattr(self._actions, "stop_scan", None)
        if stop_fn is not None:
            try:
                await stop_fn()
            except Exception:
                logger.exception("GAP STOP_DISCOVERY: stop_scan raised")
                return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    def _on_scan_result(self, result) -> None:
        """Adapter: BLEScanner ScanResult -> BTP DEVICE_FOUND event."""
        if self._tester is None:
            return
        addr_obj = getattr(result, "address", None)
        if addr_obj is None:
            return

        # Normalise address type — may be IntEnum or plain int.
        addr_type = getattr(addr_obj, "address_type", 0)
        addr_type_value = int(getattr(addr_type, "value", addr_type)) & 0xFF

        # 6-byte address. auto-pts parses this with le_bytes_to_hex_str
        # (reverses the bytes), so it must be HCI little-endian — the same
        # convention as read_controller_info (op_03). Prefer to_hci(); fall
        # back to .bytes/.address for test fakes.
        to_hci = getattr(addr_obj, "to_hci", None)
        if callable(to_hci):
            addr_bytes = to_hci()
        else:
            addr_bytes = getattr(addr_obj, "bytes", None)
            if addr_bytes is None:
                addr_bytes = getattr(addr_obj, "address", None)
        if addr_bytes is None:
            try:
                addr_bytes = bytes(addr_obj)
            except Exception:
                addr_bytes = bytes(6)
        addr_bytes = bytes(addr_bytes)[:6].ljust(6, b"\x00")

        addr_type_value, addr_bytes = self._resolve_rpa_identity(addr_type_value, addr_bytes)

        rssi = int(getattr(result, "rssi", 0)) & 0xFF

        ad = getattr(result, "advertising_data", None)
        # Prefer the raw EIR: AdvertisingData only models a few AD types, so
        # re-serialising it drops URI / service data / manufacturer data and
        # auto-pts's byte-level comparisons then fail against data the IUT
        # demonstrably received (GAP/BROB/OBSV/BV-05/06 verify the scan
        # response, whose payload is a URI AD structure).
        raw = getattr(result, "raw_advertising_data", None)
        if raw:
            eir = bytes(raw)
        elif ad is None:
            eir = b""
        elif hasattr(ad, "to_bytes"):
            try:
                eir = ad.to_bytes()
            except Exception:
                eir = b""
        elif isinstance(ad, (bytes, bytearray)):
            eir = bytes(ad)
        else:
            eir = b""

        flags = 0
        if getattr(result, "connectable", False):
            flags |= 0x01

        # Discovery is not a raw scan: only surface devices whose AD Flags mark
        # them discoverable in the mode being run. The negative DISC cases
        # (GAP/DISC/GENP/BV-03/04/05, LIMP/BV-02/03/04/05) fail at the "confirm
        # PTS is NOT discovered" step when the IUT reports the Lower Tester's
        # non-discoverable advertising; observation (OBSV) keeps reporting all.
        if self._discovery_mode != "observe":
            ad_flags = _ad_flags_from_eir(eir)
            if self._discovery_mode == "limited":
                if not (ad_flags & _AD_FLAG_LIMITED_DISC):
                    return
            elif not (ad_flags & (_AD_FLAG_GENERAL_DISC | _AD_FLAG_LIMITED_DISC)):
                return

        payload = bytearray()
        payload.append(addr_type_value)
        payload.extend(addr_bytes)
        payload.append(rssi)
        payload.append(flags & 0xFF)
        payload.extend(len(eir).to_bytes(2, "little"))
        payload.extend(eir)

        frame = BtpFrame(
            service=op.SERVICE_GAP,
            opcode=op.OP_GAP_EVENT_DEVICE_FOUND,
            controller_index=self._controller_index,
            data=bytes(payload),
        )
        try:
            asyncio.create_task(self._tester.emit_event(frame))
        except RuntimeError:
            # No running event loop — should not happen in normal usage.
            logger.exception("GAP DEVICE_FOUND: no event loop; dropping")

    # ---- Connect / Disconnect ---------------------------------------------

    async def _handle_op_0e(self, controller_index: int, data: bytes):
        """CONNECT — body: addr_type(1), addr(6, LE), own_addr_type(1, optional).

        Upstream btp_gap.txt makes Own_Addr_Type mandatory (8-byte body); we
        accept 7 too for forward/backward tolerance. Address all-zero means "use
        filter accept list" (ACEP) — resolved to the stored accept-list entry.
        """
        if len(data) not in (7, 8):
            return op.BTP_STATUS_FAILED, b""
        addr_type = data[0]
        addr_bytes = bytes(data[1:7])
        # ACEP: all-zero address means "connect via filter accept list". PTS first
        # pushes its address with SET_FILTER_ACCEPT_LIST (op 0x1c), then issues a
        # connect to 00:00:00:00:00:00. Pass the stored entry as the nominal peer
        # for bookkeeping, but let the CONTROLLER do the matching
        # (Initiator_Filter_Policy 0x01) — that is what the Auto Connection
        # Establishment procedure actually asserts. Substituting the address and
        # connecting directly was a shortcut that PTS rejects.
        use_filter_accept_list = not any(addr_bytes) and bool(self._filter_accept_list)
        use_rpa = False
        if use_filter_accept_list:
            addr_type, addr_bytes = self._filter_accept_list[0]
            # ACEP BV-03/04: the LT advertises (and expects us to initiate
            # from) resolvable private addresses. The per-case registration
            # turns privacy on before WID 400; privacy on = prepare the
            # resolving list + our own RPA and initiate with Own_Address_Type
            # 0x01. Public-identity cases (BV-01/02) keep the plain flow.
            use_rpa = self._privacy
            if use_rpa:
                prepare = getattr(self._actions, "prepare_auto_connection", None)
                if prepare is None:
                    logger.warning(
                        "GAP CONNECT: privacy on but the actions layer has no "
                        "prepare_auto_connection — connecting without the RPA preamble"
                    )
                    use_rpa = False
                else:
                    peer_str = bytes(addr_bytes[::-1]).hex(":")
                    try:
                        await prepare(peer_str)
                    except Exception:
                        logger.exception(
                            "GAP CONNECT: auto-connection preamble raised")
                        return op.BTP_STATUS_FAILED, b""
            logger.info(
                "GAP CONNECT: all-zero addr -> filter-policy connect (own_address_type=%s), "
                "accept list %s", 0x01 if self._privacy else 0x00, addr_bytes.hex(),
            )
        peer = _decode_bd_addr(addr_bytes, addr_type=addr_type)
        try:
            if addr_type == 0xE0:  # BTP_BR_ADDRESS_TYPE: page the Classic peer
                await self._actions.connect_classic(peer)
            else:
                connect_kwargs: dict = {
                    "le": True,
                    "filter_policy": 0x01 if use_filter_accept_list else 0x00,
                }
                if self._privacy:
                    # Own_Address_Type 0x01 = use the random address programmed
                    # by SET_PRIVACY. This is required for ACEP's accept-list
                    # flow and for ordinary General Connection Establishment:
                    # GAP/PRIV/CONN/BV-11 checks that InitA is an RPA minted
                    # from the IRK the LT learned during bonding, and silently
                    # ignores CONNECT_IND from our public identity.
                    connect_kwargs["own_address_type"] = 0x01
                await self._actions.connect(peer, **connect_kwargs)
        except Exception:
            logger.exception("GAP CONNECT: actions.connect raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_0f(self, controller_index: int, data: bytes):
        """DISCONNECT — body: addr_type(1), addr(6). Resolve to handle via session table."""
        if len(data) != 7:
            return op.BTP_STATUS_FAILED, b""
        addr_bytes = bytes(data[1:7])
        try:
            session = self._actions.status()
            target_handle = None
            for h, info in session.connections.items():
                if _encode_bd_addr(info.peer) == addr_bytes:
                    target_handle = h
                    break
            if target_handle is None:
                # Second pass: with privacy on, the Lower Tester connects from
                # its own a resolvable private address, so the session holds the
                # RPA while auto-pts still addresses it by the identity it knows
                # (TSPX_peer_addr). GAP/PRIV/CONN/BV-10's final disconnect is
                # exactly this: without the bond-IRK lookup it stays unmatched
                # and the case waits out TSPX_time_guard.
                peer_identity = getattr(self._actions, "peer_identity", None)
                if peer_identity is not None:
                    for h, info in session.connections.items():
                        identity = await peer_identity(info.peer)
                        if identity is not None and _encode_bd_addr(identity) == addr_bytes:
                            target_handle = h
                            logger.debug(
                                "GAP DISCONNECT: %s resolved to identity %s",
                                info.peer, identity,
                            )
                            break
            if target_handle is None:
                # Third pass: auto-pts always addresses the Lower Tester's link
                # (TSPX_peer_addr), and PTS generates its on-air RPA from an IRK
                # it never hands to the IUT — hardware capture of
                # GAP/PRIV/CONN/BV-10 shows the LT's connection event carrying an
                # RPA that resolves against neither the IRK it distributed
                # during pairing nor ours. When exactly one connection exists
                # the request is unambiguous, so terminate it rather than let
                # the case sit until TSPX_time_guard.
                if len(session.connections) == 1:
                    target_handle = next(iter(session.connections))
                    logger.warning(
                        "GAP DISCONNECT: %s matches no known peer; using the only "
                        "connection (peer %s)",
                        bytes(addr_bytes[::-1]).hex(":"),
                        bytes(_encode_bd_addr(
                            session.connections[target_handle].peer)[::-1]).hex(":"),
                    )
            if target_handle is None:
                # Unmatched disconnects used to strand the case until
                # TSPX_time_guard without any trace; name both sides.
                logger.warning(
                    "GAP DISCONNECT: no connection for %s (connected: %s)",
                    bytes(addr_bytes[::-1]).hex(":"),
                    [
                        bytes(_encode_bd_addr(info.peer)[::-1]).hex(":")
                        for info in session.connections.values()
                    ],
                )
                return op.BTP_STATUS_FAILED, b""
            await self._actions.disconnect(target_handle)
        except Exception:
            logger.exception("GAP DISCONNECT: actions.disconnect raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    # ---- Set IO Cap -------------------------------------------------------

    _IO_CAP_NAMES = {
        op.GAP_IO_CAP_DISPLAY_ONLY: "DisplayOnly",
        op.GAP_IO_CAP_DISPLAY_YESNO: "DisplayYesNo",
        op.GAP_IO_CAP_KEYBOARD_ONLY: "KeyboardOnly",
        op.GAP_IO_CAP_NO_INPUT_NO_OUTPUT: "NoInputNoOutput",
        op.GAP_IO_CAP_KEYBOARD_DISPLAY: "KeyboardDisplay",
    }

    async def _handle_op_10(self, controller_index: int, data: bytes):
        """SET_IO_CAP — body: 1 byte IO capability enum."""
        if len(data) != 1 or data[0] not in self._IO_CAP_NAMES:
            return op.BTP_STATUS_FAILED, b""
        try:
            self._actions.set_io_cap(self._IO_CAP_NAMES[data[0]])
        except Exception:
            logger.exception("GAP Set IO Cap raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    # ---- Pair / Unpair / Passkey -----------------------------------------

    async def _handle_op_11(self, controller_index: int, data: bytes):
        """PAIR — body: addr_type(1) + addr(6). Resolve addr → handle, initiate pairing.

        Upstream contract (btp_gap.txt 0x11): the success response is returned once
        pairing is *initiated*; completion/failure is reported asynchronously via
        SEC_LEVEL_CHANGED / PAIRING_FAILED events. Blocking the response until
        pairing finishes deadlocks passkey flows — auto-pts's main thread is stuck
        in ``gap_pair()`` and cannot service the passkey-entry MMI (WID 104) that
        the over-air exchange is waiting on.
        """
        if len(data) != 7:
            return op.BTP_STATUS_FAILED, b""
        addr_type = data[0]
        addr_bytes = bytes(data[1:7])
        session = self._actions.status()
        target_handle = None
        for h, info in session.connections.items():
            if _encode_bd_addr(info.peer) == addr_bytes:
                target_handle = h
                break
        if target_handle is None:
            return op.BTP_STATUS_FAILED, b""
        if addr_type == 0xE0:  # BTP_BR_ADDRESS_TYPE: SSP over the BR/EDR ACL
            # RFCOMM DEVA cases pair over BR/EDR before opening the DLC
            # (upstream hdl_wid_20). Our Classic SSP pairing runs on-demand at
            # the HCI level; acknowledge initiation — PTS observes the SSP
            # exchange on air. (No LE SMP context exists on a Classic ACL.)
            return op.BTP_STATUS_SUCCESS, b""
        # Wait for a displayed passkey (display role) before acknowledging: the
        # pairing runs in the background and surfaces the passkey only once the
        # peer's Pairing Response arrives, but auto-pts's "enter Secure Id" WID
        # (1002) reads stack.gap.passkey.data immediately after this response —
        # a race that leaves it None (GAP/DISC/RPA/BV-01 INDCSV). A short wait
        # (display role) costs nothing; input role has no display, so it just
        # times out and proceeds.
        self._passkey_displayed = asyncio.Event()
        self._spawn_pair(target_handle, addr_type=addr_type, addr=addr_bytes)
        try:
            await asyncio.wait_for(self._passkey_displayed.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass
        finally:
            self._passkey_displayed = None
        return op.BTP_STATUS_SUCCESS, b""

    def _spawn_pair(self, handle: int, *, addr_type: int, addr: bytes) -> None:
        """Run ``actions.pair`` in the background, reporting the outcome via events."""

        async def _run() -> None:
            try:
                await self._actions.pair(handle)
            except Exception as exc:
                logger.exception("GAP Pair (async) failed")
                # Surface the SMP's own reason: the negative SM cases are judged
                # on it (WID 175 expects Confirm Value Failed 0x04, EKS expects
                # Encryption Key Size 0x06). A constant 0x05 reads as a wrong
                # verdict even when the IUT aborted for exactly the right cause.
                reason = getattr(exc, "reason", None)
                self.on_pairing_failed(
                    addr=addr, addr_type=addr_type,
                    reason=0x05 if reason is None else reason,
                )
            else:
                # Pairing succeeded → security is up. Best-effort level: 3 when
                # MITM/authenticated, else 2. No current SM flow gates on the exact
                # level; PTS observes over-air completion for the positive cases.
                level = 3 if self._actions_mitm_on() else 2
                self.on_sec_level_changed(addr=addr, addr_type=addr_type, sec_level=level)

        try:
            asyncio.create_task(_run())
        except RuntimeError:
            logger.exception("GAP Pair: no running event loop")

    def _actions_mitm_on(self) -> bool:
        try:
            return bool(self._actions._stack.config.security.mitm_required)
        except Exception:
            return False

    async def _handle_op_12(self, controller_index: int, data: bytes):
        """UNPAIR — body: addr_type(1) + addr(6). Phase 1 has no unpair → FAILED."""
        if len(data) != 7:
            return op.BTP_STATUS_FAILED, b""
        unpair_fn = getattr(self._actions, "unpair", None)
        if unpair_fn is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            await unpair_fn(_decode_bd_addr(bytes(data[1:7])))
        except Exception:
            logger.exception("GAP Unpair raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_13(self, controller_index: int, data: bytes):
        """PASSKEY_ENTRY_REPLY — body: addr_type(1) + addr(6) + passkey(u32 LE)."""
        if len(data) != 11:
            return op.BTP_STATUS_FAILED, b""
        passkey_fn = getattr(self._actions, "submit_passkey", None)
        if passkey_fn is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            await passkey_fn(int.from_bytes(data[7:11], "little"))
        except Exception:
            logger.exception("GAP Passkey Entry Reply raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_14(self, controller_index: int, data: bytes):
        """PASSKEY_CONFIRM_REPLY — body: addr_type(1) + addr(6) + match(u8)."""
        if len(data) != 8:
            return op.BTP_STATUS_FAILED, b""
        confirm_fn = getattr(self._actions, "confirm_passkey", None)
        if confirm_fn is None:
            return op.BTP_STATUS_FAILED, b""
        try:
            await confirm_fn(bool(data[7]))
        except Exception:
            logger.exception("GAP Passkey Confirm Reply raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    # ---- Extended settings / filter accept list / OOB (0x15-0x20) ----------
    # These configure pairing/security/advertising mode. We store the intent and
    # acknowledge so WID handlers don't abort on UNKNOWN_CMD; whether the IUT
    # actually enforces them depends on stack support and is reflected in the
    # PTS verdict.

    async def _handle_op_15(self, controller_index: int, data: bytes):
        """START_DIRECT_ADV — directed connectable advertising toward a peer.

        Body: addr_type(1) + addr(6, LE) (+ options). Drives ADV_DIRECT_IND
        (high duty cycle) targeting the given peer; the controller sends no AD
        payload for directed PDUs. PTS observes the directed report and connects.
        """
        if len(data) < 7:
            return op.BTP_STATUS_FAILED, b""
        addr_type = data[0]
        peer = _decode_bd_addr(bytes(data[1:7]), addr_type=addr_type)
        try:
            await self._actions.advertise(adv_type=_ADV_DIRECT_IND, peer=peer)
        except Exception:
            logger.exception("GAP START_DIRECT_ADV: advertise raised")
            return op.BTP_STATUS_FAILED, b""
        self._current_settings |= (1 << 10)   # GAP_SETTINGS_ADVERTISING
        logger.info("GAP START_DIRECT_ADV toward %s (ADV_DIRECT_IND driven)", peer)
        return op.BTP_STATUS_SUCCESS, self._current_settings.to_bytes(4, "little")

    async def _handle_op_16(self, controller_index: int, data: bytes):
        """CONN_PARAM_UPDATE — body: addr_type(1)+addr(6)+itvl_min(2)+itvl_max(2)
        +latency(2)+timeout(2). Forward to actions if supported, else ack."""
        if len(data) < 7:
            return op.BTP_STATUS_FAILED, b""
        fn = getattr(self._actions, "conn_param_update", None)
        if fn is not None:
            try:
                await fn(bytes(data[1:7]), data[7:])
            except Exception:
                logger.exception("GAP Conn Param Update raised")
                return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_17(self, controller_index: int, data: bytes):
        """PAIRING_CONSENT_RSP — body: addr_type(1)+addr(6). Acknowledge consent."""
        if len(data) < 7:
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_18(self, controller_index: int, data: bytes):
        """OOB_LEGACY_SET_DATA — body: 16-byte legacy OOB TK (LE bytes). Store it
        so the next pairing advertises oob_data_flag=1 and uses it as the TK."""
        if len(data) < 16:
            return op.BTP_STATUS_FAILED, b""
        fn = getattr(self._actions, "set_oob_legacy_data", None)
        if fn is not None:
            fn(bytes(data[:16]))
        logger.info("GAP OOB_LEGACY_SET_DATA: provisioned legacy OOB TK")
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_19(self, controller_index: int, data: bytes):
        """OOB_SC_GET_LOCAL_DATA — return local SC OOB rand+conf (16+16, LE).

        SM/*/SCOB: WID 147 (conf) / 148 (rand) read this and hand it to the Lower
        Tester as the IUT's out-of-band block. Real SC OOB: the SMP layer lazily
        generates a P-256 keypair + random and commits C = f4(PKx, PKx, r, 0)."""
        fn = getattr(self._actions, "get_oob_sc_local_data", None)
        if fn is None:
            return op.BTP_STATUS_SUCCESS, bytes(32)
        rand, conf = fn()
        return op.BTP_STATUS_SUCCESS, bytes(rand) + bytes(conf)

    async def _handle_op_1a(self, controller_index: int, data: bytes):
        """OOB_SC_SET_REMOTE_DATA — body: peer rand(16) + conf(16) (LE). Store it
        so the next SC pairing verifies the peer's public key against conf and
        uses rand as the peer's OOB random input to f6."""
        if len(data) < 32:
            return op.BTP_STATUS_FAILED, b""
        fn = getattr(self._actions, "set_oob_sc_remote_data", None)
        if fn is not None:
            fn(bytes(data[:16]), bytes(data[16:32]))
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_1b(self, controller_index: int, data: bytes):
        """SET_MITM — body: 1 byte enable. Propagate to the security config."""
        if len(data) != 1:
            return op.BTP_STATUS_FAILED, b""
        self._mitm = bool(data[0])
        self._actions.set_mitm(bool(data[0]))
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_1c(self, controller_index: int, data: bytes):
        """SET_FILTER_ACCEPT_LIST — body: count(1) + per-entry addr_type(1)+addr(6).
        Store the accept list; used by Auto Connection Establishment (ACEP)."""
        if len(data) < 1:
            return op.BTP_STATUS_FAILED, b""
        count = data[0]
        entries = []
        off = 1
        for _ in range(count):
            if off + 7 > len(data):
                break
            entries.append((data[off], bytes(data[off + 1:off + 7])))
            off += 7
        self._filter_accept_list = entries
        # The controller has its own copy: with Initiator_Filter_Policy 0x01 it
        # is the controller that matches advertisers against this list, so BTP
        # bookkeeping alone changes nothing on the air.
        try:
            await self._actions.program_filter_accept_list(entries)
        except Exception:
            logger.exception("GAP SET_FILTER_ACCEPT_LIST: programming raised")
        logger.info("GAP filter accept list: %s", [(t, a.hex()) for t, a in entries])
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_1d(self, controller_index: int, data: bytes):
        """SET_PRIVACY — body: 1 byte enable.

        Must also flip the current-settings PRIVACY bit: auto-pts's WID handlers
        gate every private-address case on ``stack.gap.iut_has_privacy()``,
        which reads that bit (GAP/PRIV, GAP/BROB/BCST/BV-03/05, ...).
        """
        if len(data) < 1:
            return op.BTP_STATUS_FAILED, b""
        self._privacy = bool(data[0])
        stack = getattr(self._actions, "_stack", None)
        privacy_mgr = getattr(getattr(stack, "gap", None), "ble_privacy", None)
        if privacy_mgr is not None:
            try:
                if self._privacy:
                    # Privacy implies a resolvable private address (built from
                    # the stack IRK the peer learned during pairing).
                    await self._actions.program_private_address(resolvable=True)
                else:
                    await privacy_mgr.disable()
            except Exception:
                logger.exception("GAP SET_PRIVACY: programming the address raised")
        return op.BTP_STATUS_SUCCESS, self._set_settings_bit(
            op.OP_GAP_SET_PRIVACY, data[0]
        )

    async def _handle_op_1e(self, controller_index: int, data: bytes):
        """SET_SC_ONLY — body: 1 byte enable. Store Secure-Connections-only mode
        and propagate to the security config the SMP layer reads — SC-only
        rejects legacy pairing with Pairing Failed 0x03 (GAP/SEC/SEM/BV-28/29)."""
        if len(data) != 1:
            return op.BTP_STATUS_FAILED, b""
        self._sc_only = bool(data[0])
        settings_rsp = self._set_settings_bit(op.OP_GAP_SET_SC_ONLY, data[0])
        stack = getattr(self._actions, "_stack", None)
        sec = getattr(stack, "config", None)
        if sec is not None:
            sec = getattr(sec, "security", None)
        if sec is not None:
            sec.sc_only_mode = self._sc_only
        # auto-pts parses the response payload as the new current_settings
        # bitmap (gap_enable_secure_connections_only -> __gap_current_settings_
        # update): an empty payload raises BTPError "Invalid data length".
        return op.BTP_STATUS_SUCCESS, settings_rsp

    async def _handle_op_1f(self, controller_index: int, data: bytes):
        """SET_SC — body: 1 byte enable. Store Secure-Connections support."""
        if len(data) != 1:
            return op.BTP_STATUS_FAILED, b""
        self._sc = bool(data[0])
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_20(self, controller_index: int, data: bytes):
        """SET_MIN_ENC_KEY_SIZE — body: 1 byte size.

        Drives the SMP key-size floor. PTS models "LE security mode 1 level 3/4"
        as requiring a 16-octet key, so the GAP/SEC/SEM invalid-key-size cases
        set 16 here and then expect Pairing Failed 0x06 for every
        Max_Encryption_Key_Size in [7,15].
        """
        if len(data) != 1:
            return op.BTP_STATUS_FAILED, b""
        self._min_enc_key_size = data[0]
        stack = getattr(self._actions, "_stack", None)
        sec = getattr(getattr(stack, "config", None), "security", None)
        if sec is not None:
            sec.min_encryption_key_size = int(data[0])
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_21(self, controller_index: int, data: bytes):
        """SET_EXTENDED_ADVERTISING — body: 1 byte enable. Store (ext-adv not driven)."""
        if len(data) != 1:
            return op.BTP_STATUS_FAILED, b""
        self._ext_advertising = bool(data[0])
        return op.BTP_STATUS_SUCCESS, b""

    # ---- Periodic advertising (GAP/PADV, opcodes 0x22-0x29) ---------------

    async def _handle_op_22(self, controller_index: int, data: bytes):
        """PADV_CONFIGURE — include_tx_power(1), intvl_min(2 LE), intvl_max(2 LE).

        auto-pts sends a 5-byte body for plain periodic advertising and appends
        a 5-byte subevent config when it means PAwR; the extra bytes are ignored
        here (PAwR is out of scope).
        """
        if len(data) < 5:
            return op.BTP_STATUS_FAILED, b""
        include_tx_power = bool(data[0])
        interval_min, interval_max = struct.unpack_from("<HH", data, 1)
        try:
            await self._actions.padv_configure(
                include_tx_power=include_tx_power,
                interval_min=interval_min, interval_max=interval_max,
            )
        except Exception:
            logger.exception("GAP PADV_CONFIGURE raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, self._periodic_adv_settings()

    async def _handle_op_23(self, controller_index: int, data: bytes):
        """PADV_START — flags(1). Starts periodic advertising on the set."""
        if len(data) < 1:
            return op.BTP_STATUS_FAILED, b""
        try:
            await self._actions.padv_start()
        except Exception:
            logger.exception("GAP PADV_START raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, self._current_settings.to_bytes(4, "little")

    async def _handle_op_24(self, controller_index: int, data: bytes):
        """PADV_STOP — no body."""
        try:
            await self._actions.padv_stop()
        except Exception:
            logger.exception("GAP PADV_STOP raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, self._current_settings.to_bytes(4, "little")

    async def _handle_op_25(self, controller_index: int, data: bytes):
        """PADV_SET_DATA — data_len(2 LE) + data."""
        if len(data) < 2:
            return op.BTP_STATUS_FAILED, b""
        data_len = struct.unpack_from("<H", data, 0)[0]
        payload = bytes(data[2:2 + data_len])
        if len(payload) != data_len:
            return op.BTP_STATUS_FAILED, b""
        try:
            await self._actions.padv_set_data(payload)
        except Exception:
            logger.exception("GAP PADV_SET_DATA raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_26(self, controller_index: int, data: bytes):
        """PADV_CREATE_SYNC — addr_type(1) addr(6) adv_sid(1) skip(2 LE)
        sync_timeout(2 LE) flags(1)."""
        if len(data) < 13:
            return op.BTP_STATUS_FAILED, b""
        address_type = data[0]
        address = bytes(data[1:7])
        adv_sid = data[7]
        skip, sync_timeout = struct.unpack_from("<HH", data, 8)
        flags = data[12]
        try:
            await self._actions.padv_create_sync(
                adv_sid=adv_sid, skip=skip, sync_timeout=sync_timeout,
                flags=flags, address_type=address_type, address=address,
            )
        except Exception:
            logger.exception("GAP PADV_CREATE_SYNC raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_27(self, controller_index: int, data: bytes):
        """PADV_SYNC_TRANSFER_SET_INFO — addr_type(1) addr(6) service_data(2)."""
        if len(data) < 9:
            return op.BTP_STATUS_FAILED, b""
        try:
            await self._actions.padv_sync_transfer_set_info(
                address_type=data[0], address=bytes(data[1:7]),
                service_data=struct.unpack_from("<H", data, 7)[0],
            )
        except Exception:
            logger.exception("GAP PADV_SYNC_TRANSFER_SET_INFO raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_28(self, controller_index: int, data: bytes):
        """PADV_SYNC_TRANSFER_START — addr_type(1) addr(6) service_data(2).

        (auto-pts's client packs op 0x27's layout for this helper too.)
        """
        if len(data) < 9:
            return op.BTP_STATUS_FAILED, b""
        try:
            await self._actions.padv_sync_transfer_set_info(
                address_type=data[0], address=bytes(data[1:7]),
                service_data=struct.unpack_from("<H", data, 7)[0],
            )
            await self._actions.padv_sync_transfer_start()
        except Exception:
            logger.exception("GAP PADV_SYNC_TRANSFER_START raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    async def _handle_op_29(self, controller_index: int, data: bytes):
        """PADV_SYNC_TRANSFER_RECV — addr_type(1) addr(6) skip(2 LE)
        sync_timeout(2 LE) flags(1)."""
        if len(data) < 12:
            return op.BTP_STATUS_FAILED, b""
        skip, sync_timeout = struct.unpack_from("<HH", data, 7)
        try:
            await self._actions.padv_sync_transfer_recv(
                skip=skip, sync_timeout=sync_timeout, flags=data[11],
                address_type=data[0], address=bytes(data[1:7]),
            )
        except Exception:
            logger.exception("GAP PADV_SYNC_TRANSFER_RECV raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    def _periodic_adv_settings(self) -> bytes:
        return self._current_settings.to_bytes(4, "little")

    async def _handle_op_2b(self, controller_index: int, data: bytes):
        """SUBRATE_REQUEST (0x2b) — addr_type(1)+addr(6)+subrate_min(2)+
        subrate_max(2)+conn_latency(2)+cont_num(2)+supervision_timeout(2).

        Drives both GAP/CSUB cases: Core §7.8.124 has the single HCI command
        LE_Subrate_Request cover the Central's "Subrate Update" and the
        Peripheral's "Subrate Request". The result arrives asynchronously as an
        LE Subrate Change event, which pts-tester forwards as BTP 0x92."""
        if len(data) < 17:
            return op.BTP_STATUS_FAILED, b""
        try:
            await self._actions.subrate_request(bytes(data[1:7]), data[7:17])
        except Exception:
            logger.exception("GAP SUBRATE_REQUEST raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    # ---- Broadcast Isochronous Group (GAP/BIS/BBM/BV-01-C) -----------------

    async def _handle_op_2d(self, controller_index: int, data: bytes):
        """CREATE_BIG (0x2d) — auto-pts ``gap_create_big``:
        bis_id(1) num_bis(1) sdu_interval(u32 µs) max_latency(u16 ms)
        rtn(1) phy(1) packing(1) framing(1) encryption(1) [broadcast_code(16)].

        Establishing a BIG takes seconds on air, so the command answers SUCCESS
        immediately (the same shape that fixed the PAIR 0x11 deadlock) and the
        create + per-BIS data-path chain runs as a background task. Each BIS
        whose HCI data path is wired emits one BIS_DATA_PATH_SETUP (ev 0x95) —
        that is what auto-pts's ``hdl_wid_357`` waits on.
        """
        if len(data) < 13:
            return op.BTP_STATUS_FAILED, b""
        encryption = data[12]
        broadcast_code = None
        if encryption:
            if len(data) < 29:
                return op.BTP_STATUS_FAILED, b""
            broadcast_code = bytes(data[13:29])
        sdu_interval, max_latency = struct.unpack_from("<IH", data, 2)
        self._big_task = asyncio.create_task(self._create_big_and_emit(
            bis_id=data[0], num_bis=data[1], sdu_interval_us=sdu_interval,
            max_transport_latency_ms=max_latency, rtn=data[8], phy=data[9],
            packing=data[10], framing=data[11], encryption=encryption,
            broadcast_code=broadcast_code,
        ))
        return op.BTP_STATUS_SUCCESS, b""

    async def _create_big_and_emit(self, **kwargs) -> None:
        try:
            handles = await self._actions.create_big(**kwargs)
        except Exception:
            # The BTP response is already gone; a failure here (controller
            # rejected LE_Create_BIG, BIG Complete timeout) must only be logged.
            logger.exception("GAP CREATE_BIG failed")
            return
        for bis_id in sorted(handles):
            # <B6sB>: addr_type(1) + addr(6) + bis_id(1). auto-pts's parser
            # ignores the address fields and appends only bis_id.
            payload = bytes([0x00]) + bytes(6) + bytes([bis_id & 0xFF])
            self._emit_event(op.OP_GAP_EVENT_BIS_DATA_PATH_SETUP, payload)

    async def _handle_op_2e(self, controller_index: int, data: bytes):
        """BIS_BROADCAST (0x2e) — bis_id(1) + len(1) + data."""
        if len(data) < 2:
            return op.BTP_STATUS_FAILED, b""
        bis_id = data[0]
        length = data[1]
        payload = bytes(data[2:2 + length])
        if len(payload) != length:
            return op.BTP_STATUS_FAILED, b""
        try:
            await self._actions.bis_broadcast(bis_id, payload)
        except Exception:
            logger.exception("GAP BIS_BROADCAST raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    # ---- Encrypted Advertising Data (CSS v15 §1.23) ------------------------

    async def _handle_op_31(self, controller_index: int, data: bytes):
        """SET_EAD_KEY_MATERIAL (0x31) — session key(16) + IV(8).

        auto-pts pushes the same pair it configures in PTS as IXIT values, so
        both sides encrypt identically.
        """
        from pybluehost.ble.ead import (
            EAD_KEY_LEN, EAD_KEY_MATERIAL_LEN, EADKeyMaterial,
        )

        if len(data) < 24:
            return op.BTP_STATUS_FAILED, b""
        try:
            # auto-pts hands the IV over little-endian: PTS treats its IXIT
            # value as a big-endian number and auto-pts converts with
            # `hex_str_to_le_bytes` (autopts/pybtp/btp/gap.py). EADKeyMaterial
            # keeps the CSS's most-significant-first form — `_nonce` reverses it
            # into the CCM nonce — so undo the conversion here. Without this the
            # IV is reversed twice and PTS decrypts our advertising to garbage
            # (GAP/ADV/BV-21 FAIL, with the EAD structure demonstrably on air).
            material = EADKeyMaterial(
                session_key=bytes(data[:EAD_KEY_LEN]),
                iv=bytes(data[EAD_KEY_LEN:EAD_KEY_MATERIAL_LEN])[::-1],
            )
        except ValueError:
            logger.exception("GAP SET_EAD_KEY_MATERIAL: bad key material")
            return op.BTP_STATUS_FAILED, b""
        self._ead_material = material
        # Publish it through the hosted Encrypted Data Key Material
        # characteristic: GAP/ADV/BV-21's Lower Tester reads it from the IUT and
        # then decrypts the Encrypted Advertising Data we broadcast.
        self._publish_ead_key_material(bytes(data[:24]))
        return op.BTP_STATUS_SUCCESS, b""

    def _publish_ead_key_material(self, value: bytes) -> None:
        stack = getattr(self._actions, "_stack", None)
        server = getattr(stack, "gatt_server", None) if stack is not None else None
        db = getattr(server, "db", None) if server is not None else None
        if db is None:
            return
        from pybluehost.core.uuid import UUID16

        attrs = db.find_by_type_in_range(0x0001, db.last_handle, UUID16(0x2B88))
        if not attrs:
            logger.debug("SET_EAD_KEY_MATERIAL: no hosted 0x2B88 characteristic")
            return
        try:
            db.write(attrs[0].handle, value)
        except Exception:
            logger.exception("SET_EAD_KEY_MATERIAL: publishing the value failed")

    async def _handle_op_32(self, controller_index: int, data: bytes):
        """ENCRYPT_EAD_DATA (0x32) — len(1) + payload; reply len(1) + EAD."""
        from pybluehost.ble.ead import encrypt_ead

        if self._ead_material is None or not data:
            return op.BTP_STATUS_FAILED, b""
        length = data[0]
        payload = bytes(data[1:1 + length])
        if len(payload) != length:
            return op.BTP_STATUS_FAILED, b""
        ead = encrypt_ead(payload, self._ead_material)
        return op.BTP_STATUS_SUCCESS, bytes([len(ead)]) + ead

    async def _handle_op_33(self, controller_index: int, data: bytes):
        """DECRYPT_EAD_DATA (0x33) — len(1) + EAD; reply len(1) + plaintext."""
        from pybluehost.ble.ead import decrypt_ead

        if self._ead_material is None or not data:
            return op.BTP_STATUS_FAILED, b""
        length = data[0]
        ead = bytes(data[1:1 + length])
        if len(ead) != length:
            return op.BTP_STATUS_FAILED, b""
        try:
            plaintext = decrypt_ead(ead, self._ead_material)
        except Exception:
            logger.exception("GAP DECRYPT_EAD_DATA failed")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, bytes([len(plaintext)]) + plaintext

    # ---- Pairing event emission helpers -----------------------------------

    def on_pairing_failed(self, *, addr: bytes, addr_type: int, reason: int) -> None:
        if self._tester is None:
            return
        payload = (
            bytes([addr_type & 0xFF])
            + bytes(addr)[:6].ljust(6, b"\x00")
            + bytes([reason & 0xFF])
        )
        self._emit_event(op.OP_GAP_EVENT_PAIRING_FAILED, payload)

    def on_bond_lost(self, *, addr: bytes, addr_type: int) -> None:
        """BTP GAP BOND_LOST (ev 0x8B) — body addr_type(1) + addr(6, LE).

        PTS wants this when the peer refuses to encrypt with the LTK it
        distributed earlier ("PIN or Key Missing"), i.e. the bond is gone on the
        other side (GAP/SEC/AUT/BV-21/22).
        """
        if self._tester is None:
            return
        payload = bytes([addr_type & 0xFF]) + bytes(addr)[:6].ljust(6, b"\x00")
        self._emit_event(op.OP_GAP_EVENT_BOND_LOST, payload)

    def on_sec_level_changed(self, *, addr: bytes, addr_type: int, sec_level: int) -> None:
        if self._tester is None:
            return
        payload = (
            bytes([addr_type & 0xFF])
            + bytes(addr)[:6].ljust(6, b"\x00")
            + bytes([sec_level & 0xFF])
        )
        self._emit_event(op.OP_GAP_EVENT_SEC_LEVEL_CHANGED, payload)

    def on_subrate_change(
        self, *, addr: bytes, addr_type: int, status: int, handle: int,
        subrate_factor: int, peripheral_latency: int, continuation_number: int,
        supervision_timeout: int,
    ) -> None:
        """BTP GAP SUBRATE_CHANGE (ev 0x92) — the Controller completed the
        Connection Subrate Update procedure (GAP/CSUB/CSR + CSU, both roles).

        Layout matches auto-pts ``gap_subrate_change_ev_`` exactly:
        ``<B6sBHHHHH`` = addr_type(1)+addr(6)+status(1)+handle(2)+factor(2)
        +latency(2)+continuation(2)+supervision_timeout(2). auto-pts rejects the
        event unless the address matches its own LT address, so ``addr`` must be
        the peer's (LE byte order), not ours.
        """
        if self._tester is None:
            return
        payload = (
            bytes([addr_type & 0xFF])
            + bytes(addr)[:6].ljust(6, b"\x00")
            + struct.pack(
                "<BHHHHH", status & 0xFF, handle & 0x0FFF, subrate_factor,
                peripheral_latency, continuation_number, supervision_timeout,
            )
        )
        self._emit_event(op.OP_GAP_EVENT_SUBRATE_CHANGE, payload)

    def on_passkey_display(self, *, addr: bytes, addr_type: int, passkey: int) -> None:
        if self._tester is None:
            return
        if self._passkey_displayed is not None:
            self._passkey_displayed.set()
        payload = (
            bytes([addr_type & 0xFF])
            + bytes(addr)[:6].ljust(6, b"\x00")
            + passkey.to_bytes(4, "little")
        )
        self._emit_event(op.OP_GAP_EVENT_PASSKEY_DISPLAY, payload)

    def _emit_event(self, opcode: int, payload: bytes) -> None:
        if self._tester is None:
            return
        frame = BtpFrame(
            service=op.SERVICE_GAP, opcode=opcode,
            controller_index=self._controller_index, data=payload,
        )
        try:
            asyncio.create_task(self._tester.emit_event(frame))
        except RuntimeError:
            logger.exception("GAP event %#x: no event loop; dropping", opcode)

    # ---- Periodic advertising events (GAP/PADV, 0x8D-0x90) -----------------

    def wire_periodic_advertising(self) -> None:
        """Register HCI fan-in hooks so periodic-advertising events reach the
        tester as BTP events. Called once from the pts-tester bring-up."""
        padv = getattr(getattr(self._actions, "_stack", None), "gap", None)
        padv = getattr(padv, "periodic_advertising", None)
        if padv is None:
            return
        padv.set_handlers(
            on_sync_established=self._on_periodic_sync_established,
            on_sync_lost=self._on_periodic_sync_lost,
            on_report=self._on_periodic_report,
            on_transfer_received=self._on_periodic_transfer_received,
        )

    def _on_periodic_sync_established(self, sync) -> None:
        # auto-pts's parser (gap_padv_sync_established_ev_) only flips a flag;
        # the raw sync descriptor is still useful in the trace.
        self._emit_event(op.OP_GAP_EVENT_PERIODIC_SYNC_ESTABLISHED, b"")

    def _on_periodic_sync_lost(self, sync_handle: int) -> None:
        self._emit_event(op.OP_GAP_EVENT_PERIODIC_SYNC_LOST, b"")

    def _on_periodic_report(self, data: bytes) -> None:
        """Periodic advertising report: Sync_Handle(2) TxPower(1) RSSI(1)
        CTE_Type(1) Data_Status(1) Data_Length(1) then the data — the exact
        layout auto-pts unpacks with '<HBBBBB'."""
        payload = (
            bytes([0x00, 0x00])          # sync handle (single active sync)
            + bytes([0x7F])              # Tx_Power: not available
            + bytes([0x7F])              # RSSI: not available
            + bytes([0x00])              # CTE_Type: none
            + bytes([0x00])              # Data_Status: complete
            + bytes([len(data) & 0xFF])
            + bytes(data)
        )
        self._emit_event(op.OP_GAP_EVENT_PERIODIC_REPORT, payload)

    def _on_periodic_transfer_received(self) -> None:
        self._emit_event(op.OP_GAP_EVENT_PERIODIC_TRANSFER_RECEIVED, b"")

    # ---- Connection state event hook --------------------------------------

    def on_connection_state_change(
        self, *, handle: int, addr: bytes, addr_type: int, connected: bool,
        conn_params: tuple[int, int, int] | None = None,
    ) -> None:
        """Synthesize a DEVICE_CONNECTED or DEVICE_DISCONNECTED BTP event.

        Wire this method as a callback into stack.on_connection_event when
        registering GapService in `pts-tester` (Task 8). ``conn_params`` is the
        current (interval, latency, supervision_timeout) in raw HCI units;
        auto-pts's DEVICE_CONNECTED handler stores it as the connection-params
        baseline that the Connection Parameter Update procedure (GAP/CONN/CPUP)
        reads — zeros would make WID 46 request an invalid itvl=0 update.
        """
        if self._tester is None:
            return
        opcode = (
            op.OP_GAP_EVENT_DEVICE_CONNECTED if connected
            else op.OP_GAP_EVENT_DEVICE_DISCONNECTED
        )
        payload = bytearray()
        payload.append(addr_type & 0xFF)
        payload.extend(bytes(addr)[:6].ljust(6, b"\x00"))
        if connected:
            # conn_interval(u16) + latency(u16) + supervision_timeout(u16), raw
            # HCI units (interval N*1.25ms, timeout N*10ms). Fall back to zeros
            # if the stack didn't capture them (e.g. non-LE or test fake).
            import struct as _struct
            itvl, latency, timeout = conn_params if conn_params else (0, 0, 0)
            payload.extend(_struct.pack("<HHH", itvl, latency, timeout))
        frame = BtpFrame(
            service=op.SERVICE_GAP, opcode=opcode,
            controller_index=self._controller_index, data=bytes(payload),
        )
        try:
            asyncio.create_task(self._tester.emit_event(frame))
        except RuntimeError:
            logger.exception("GAP connection event: no event loop; dropping")

        # A formed connection stops legacy advertising. Push a NEW_SETTINGS event
        # with the ADVERTISING bit cleared so auto-pts's GAP model re-syncs —
        # otherwise gap_start_advertising() thinks we're still advertising and
        # short-circuits the re-advertise on the next round (PTS GAP/SEC/SEM
        # multi-round cases stall waiting for a reconnect that never comes).
        if connected and (self._current_settings & (1 << 10)):
            self._current_settings &= ~(1 << 10)  # GAP_SETTINGS_ADVERTISING
            self._emit_event(
                op.OP_GAP_EVENT_NEW_SETTINGS,
                self._current_settings.to_bytes(4, "little"),
            )

    def _on_inquiry_result(self, info) -> None:
        """Adapter: ClassicDiscovery inquiry result -> BTP DEVICE_FOUND event
        with the BR/EDR address type (0xE0) so auto-pts's
        check_discovery_results(addr_type=BTP_BR_ADDRESS_TYPE) matches."""
        if self._tester is None:
            return
        addr_obj = getattr(info, "address", None)
        if addr_obj is None:
            return
        to_hci = getattr(addr_obj, "to_hci", None)
        addr_bytes = to_hci() if callable(to_hci) else getattr(addr_obj, "address", None)
        if addr_bytes is None:
            return
        addr_bytes = bytes(addr_bytes)[:6].ljust(6, b"\x00")

        eir = bytes(getattr(info, "eir", b"") or b"")
        rssi = int(getattr(info, "rssi", 0) or 0) & 0xFF

        payload = bytearray()
        payload.append(0xE0)  # BTP_BR_ADDRESS_TYPE
        payload.extend(addr_bytes)
        payload.append(rssi)
        payload.append(0x01)  # connectable
        payload.extend(len(eir).to_bytes(2, "little"))
        payload.extend(eir)
        frame = BtpFrame(
            service=op.SERVICE_GAP, opcode=op.OP_GAP_EVENT_DEVICE_FOUND,
            controller_index=self._controller_index, data=bytes(payload),
        )
        try:
            asyncio.create_task(self._tester.emit_event(frame))
        except Exception:
            logger.exception("GAP inquiry DEVICE_FOUND emit failed")
