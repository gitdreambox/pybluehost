"""GAP BTP service — translates GAP opcodes into Phase 1 IutActions calls.

See design spec §11.5 + auto-pts doc/btp_gap.txt for the wire format.

Command handlers land in P.6 Tasks 2-7; this file is the skeleton.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from pybluehost.pts.btp import opcodes as op
from pybluehost.pts.btp.protocol import BtpFrame
from pybluehost.pts.btp.services.base import BtpService

if TYPE_CHECKING:
    from pybluehost.pts.actions import IutActions
    from pybluehost.pts.btp.tester import BtpTester

logger = logging.getLogger(__name__)


def _decode_bd_addr(addr_bytes: bytes) -> "BDAddress":
    """6-byte BTP address (little-endian per BD_ADDR convention) → BDAddress.

    The default address type is PUBLIC; callers wanting RANDOM must override
    via the surrounding command (BTP commands carry the type as a separate byte).
    """
    from pybluehost.core.address import AddressType, BDAddress
    return BDAddress(address=bytes(addr_bytes), type=AddressType.PUBLIC)


def _encode_bd_addr(addr) -> bytes:
    """BDAddress → 6 bytes (matches the wire format `address` field)."""
    if addr is None:
        return bytes(6)
    # Real BDAddress uses `.address`; test fakes may use `.bytes`.
    raw = getattr(addr, "address", None)
    if raw is None:
        raw = getattr(addr, "bytes", None)
    if raw is None:
        try:
            raw = bytes(addr)
        except Exception:
            raw = bytes(6)
    return bytes(raw)[:6].ljust(6, b"\x00")


class GapService(BtpService):
    """LE GAP BTP service. Routes opcodes to IutActions calls; emits async
    GAP events to autoptsclient via BtpTester.emit_event."""

    SERVICE_ID = op.SERVICE_GAP

    def __init__(self, *, actions: "IutActions", tester: "BtpTester") -> None:
        self._actions = actions
        self._tester = tester
        self._current_settings: int = 0
        self._controller_index: int = 0

    async def _handle_op_01(self, controller_index: int, data: bytes):
        """READ_SUPPORTED_COMMANDS — bitfield of supported GAP opcodes."""
        cmds = self.supported_commands()
        if not cmds:
            return op.BTP_STATUS_SUCCESS, bytes(0)
        n_bytes = (max(cmds) // 8) + 1
        out = bytearray(n_bytes)
        for code in cmds:
            bit_index = code - 1
            out[bit_index // 8] |= 1 << (bit_index % 8)
        return op.BTP_STATUS_SUCCESS, bytes(out)

    async def _handle_op_02(self, controller_index: int, data: bytes):
        """READ_CONTROLLER_INDEX_LIST — PyBlueHost is single-controller, index 0."""
        return op.BTP_STATUS_SUCCESS, bytes([1, 0])

    async def _handle_op_03(self, controller_index: int, data: bytes):
        """READ_CONTROLLER_INFO — BD_ADDR + settings + class_of_device + name."""
        local_addr = getattr(self._actions, "local_address", None)
        if isinstance(local_addr, bytes) and len(local_addr) == 6:
            addr_bytes = local_addr
        elif local_addr is not None and hasattr(local_addr, "address_bytes"):
            addr_bytes = bytes(local_addr.address_bytes)[:6]
        else:
            addr_bytes = bytes(6)

        # PyBlueHost LE-only capability advertisement (auto-pts settings bits).
        supported_settings = 0
        for bit in (1, 4, 8, 9):    # connectable, bondable, BLE, advertising
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
        """SET_CONNECTABLE."""
        if len(data) != 1:
            return op.BTP_STATUS_FAILED, b""
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
        return op.BTP_STATUS_SUCCESS, self._set_settings_bit(op.OP_GAP_SET_DISCOVERABLE, data[0])

    async def _handle_op_09(self, controller_index: int, data: bytes):
        """SET_BONDABLE."""
        if len(data) != 1:
            return op.BTP_STATUS_FAILED, b""
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
        # scan_rsp accepted but discarded — Phase 1 IutActions doesn't expose it.
        offset += scan_rsp_len
        # duration + own_addr_type tail present but not used in P.6.
        try:
            await self._actions.advertise(data=bytes(adv_data))
        except Exception:
            logger.exception("GAP START_ADVERTISING: actions.advertise raised")
            return op.BTP_STATUS_FAILED, b""
        self._current_settings |= (1 << 9)
        return op.BTP_STATUS_SUCCESS, self._current_settings.to_bytes(4, "little")

    async def _handle_op_0b(self, controller_index: int, data: bytes):
        """STOP_ADVERTISING — no body."""
        try:
            await self._actions.stop_advertising()
        except Exception:
            logger.exception("GAP STOP_ADVERTISING: actions.stop_advertising raised")
            return op.BTP_STATUS_FAILED, b""
        self._current_settings &= ~(1 << 9)
        return op.BTP_STATUS_SUCCESS, self._current_settings.to_bytes(4, "little")

    # ---- Start / Stop Discovery -------------------------------------------

    async def _handle_op_0c(self, controller_index: int, data: bytes):
        """START_DISCOVERY. Body: flags(u8) — bit 0=LE, bit 1=BR/EDR, bit 2=active."""
        if len(data) != 1:
            return op.BTP_STATUS_FAILED, b""
        flags = data[0]
        active = bool(flags & 0x04)
        try:
            await self._actions.scan(active=active, on_result=self._on_scan_result)
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

        # 6-byte address. Real BDAddress uses `.address`; test fakes may use `.bytes`.
        addr_bytes = getattr(addr_obj, "bytes", None)
        if addr_bytes is None:
            addr_bytes = getattr(addr_obj, "address", None)
        if addr_bytes is None:
            try:
                addr_bytes = bytes(addr_obj)
            except Exception:
                addr_bytes = bytes(6)
        addr_bytes = bytes(addr_bytes)[:6].ljust(6, b"\x00")

        rssi = int(getattr(result, "rssi", 0)) & 0xFF

        ad = getattr(result, "advertising_data", None)
        if ad is None:
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
        """CONNECT — body: addr_type(1), addr(6)."""
        if len(data) != 7:
            return op.BTP_STATUS_FAILED, b""
        addr_bytes = bytes(data[1:7])
        peer = _decode_bd_addr(addr_bytes)
        try:
            await self._actions.connect(peer, le=True)
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
                return op.BTP_STATUS_FAILED, b""
            await self._actions.disconnect(target_handle)
        except Exception:
            logger.exception("GAP DISCONNECT: actions.disconnect raised")
            return op.BTP_STATUS_FAILED, b""
        return op.BTP_STATUS_SUCCESS, b""

    # ---- Connection state event hook --------------------------------------

    def on_connection_state_change(
        self, *, handle: int, addr: bytes, addr_type: int, connected: bool,
    ) -> None:
        """Synthesize a DEVICE_CONNECTED or DEVICE_DISCONNECTED BTP event.

        Wire this method as a callback into stack.on_connection_event when
        registering GapService in `pts-tester` (Task 8).
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
            # conn_interval(u16) + latency(u16) + supervision_timeout(u16) — zeros
            # for now; the real stack will supply once wired (Task 8).
            payload.extend(b"\x00" * 6)
        frame = BtpFrame(
            service=op.SERVICE_GAP, opcode=opcode,
            controller_index=self._controller_index, data=bytes(payload),
        )
        try:
            asyncio.create_task(self._tester.emit_event(frame))
        except RuntimeError:
            logger.exception("GAP connection event: no event loop; dropping")
