"""VirtualController — software-only HCI controller for testing.

Processes HCI commands and returns synthetic Command Complete events,
allowing full HCI stack testing without hardware.
"""

from __future__ import annotations

import asyncio
import struct
from typing import Callable

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import (
    ErrorCode,
    EventCode,
    HCI_ACL_PACKET,
    HCI_COMMAND_PACKET,
    HCI_SCO_PACKET,
    HCI_HOST_BUFFER_SIZE,
    HCI_IO_CAPABILITY_REQUEST_REPLY,
    HCI_IO_CAPABILITY_REQUEST_NEGATIVE_REPLY,
    HCI_LE_LONG_TERM_KEY_REQUEST_NEGATIVE_REPLY,
    HCI_LE_LONG_TERM_KEY_REQUEST_REPLY,
    HCI_LE_READ_BUFFER_SIZE,
    HCI_LE_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_LE_SET_ADVERTISE_ENABLE,
    HCI_LE_SET_ADVERTISING_DATA,
    HCI_LE_SET_ADVERTISING_PARAMS,
    HCI_LE_SET_EVENT_MASK,
    HCI_LE_SET_RANDOM_ADDRESS,
    HCI_LE_SET_SCAN_RESPONSE_DATA,
    HCI_LE_SET_SCAN_PARAMS,
    HCI_LE_START_ENCRYPTION,
    HCI_LINK_KEY_REQUEST_REPLY,
    HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY,
    HCI_READ_BD_ADDR,
    HCI_READ_BUFFER_SIZE,
    HCI_READ_LOCAL_EXTENDED_FEATURES,
    HCI_READ_LOCAL_SUPPORTED_COMMANDS,
    HCI_READ_LOCAL_SUPPORTED_FEATURES,
    HCI_READ_LOCAL_VERSION,
    HCI_RESET,
    HCI_SET_EVENT_MASK,
    HCI_SETUP_SYNCHRONOUS_CONNECTION,
    HCI_USER_CONFIRMATION_REQUEST_REPLY,
    HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY,
    HCI_WRITE_LE_HOST_SUPPORTED,
    HCI_WRITE_SCAN_ENABLE,
    HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT,
    HCI_WRITE_SIMPLE_PAIRING_MODE,
    LEMetaSubEvent,
)
from pybluehost.hci.packets import (
    HCI_Command_Complete_Event,
    HCI_Command_Status_Event,
    HCI_LE_LTK_Request_Negative_Reply_Command,
    HCI_LE_LTK_Request_Reply_Command,
    HCI_LE_Start_Encryption_Command,
    HCIACLData,
    HCICommand,
    HCIEvent,
    HCISCOData,
    decode_hci_packet,
)
from pybluehost.transport.base import Transport, TransportInfo


class VirtualController:
    """Software-only HCI controller for testing.

    Accepts raw H4+HCI command bytes, decodes the command, dispatches to a
    handler, and returns raw H4+HCI Command Complete event bytes.
    """

    def __init__(self, address: BDAddress) -> None:
        self._address = address
        self._host_sink: object | None = None  # set by create(); used for async event injection
        self._acl_forwarder = None  # set by VirtualLELink to bridge ACL frames
        self._sco_forwarder = None  # set by VirtualClassicLink to bridge SCO frames
        # Optional async hook for VirtualClassicLink to intercept Setup_Synchronous_Connection.
        # Signature: async (acl_handle: int, raw_params: bytes) -> Optional[bytes]
        # If it returns non-None bytes, that becomes the HCI response; the local stub is skipped.
        self._sco_setup_hook = None
        # Optional async hook called by VirtualLELink to intercept encryption starts.
        # Signature: async (handle, rand, ediv, ltk) -> None
        # When set, the VirtualController skips its own ENCRYPTION_CHANGE emission
        # and delegates the full Central↔Peripheral encryption dance to the hook.
        self._encryption_start_hook = None
        # Optional async hook for LTK_Request_Reply from the Peripheral side.
        # Signature: async (handle, ltk) -> None
        self._ltk_reply_hook = None
        # Generic bridge entry point (VirtualClassicLink). Called at top of
        # process() after the ACL branch. Signature:
        #   async (opcode: int, raw_params: bytes) -> Optional[bytes]
        # If it returns non-None bytes, that becomes the HCI response; None
        # falls through to default dispatch.
        self.command_interceptor = None
        # BR/EDR scan-enable flags, updated by HCI_Write_Scan_Enable.
        self._inquiry_scan = False
        self._page_scan = False
        self._handlers: dict[int, Callable[[HCICommand], bytes]] = {
            HCI_RESET: self._handle_reset,
            HCI_READ_BD_ADDR: self._handle_read_bd_addr,
            HCI_READ_LOCAL_VERSION: self._handle_read_local_version,
            HCI_READ_BUFFER_SIZE: self._handle_read_buffer_size,
            HCI_LE_READ_BUFFER_SIZE: self._handle_le_read_buffer_size,
            HCI_READ_LOCAL_SUPPORTED_COMMANDS: self._handle_read_local_supported_commands,
            HCI_READ_LOCAL_SUPPORTED_FEATURES: self._handle_read_local_supported_features,
            HCI_READ_LOCAL_EXTENDED_FEATURES: self._handle_read_local_extended_features,
            HCI_LE_READ_LOCAL_SUPPORTED_FEATURES: self._handle_le_read_local_supported_features,
            HCI_SET_EVENT_MASK: self._handle_status_only,
            HCI_LE_SET_EVENT_MASK: self._handle_status_only,
            HCI_WRITE_LE_HOST_SUPPORTED: self._handle_status_only,
            HCI_WRITE_SIMPLE_PAIRING_MODE: self._handle_status_only,
            HCI_WRITE_SECURE_CONNECTIONS_HOST_SUPPORT: self._handle_status_only,
            HCI_WRITE_SCAN_ENABLE: self._handle_status_only,
            HCI_HOST_BUFFER_SIZE: self._handle_status_only,
            HCI_LE_SET_ADVERTISE_ENABLE: self._handle_status_only,
            HCI_LE_SET_ADVERTISING_DATA: self._handle_status_only,
            HCI_LE_SET_ADVERTISING_PARAMS: self._handle_status_only,
            HCI_LE_SET_SCAN_RESPONSE_DATA: self._handle_status_only,
            HCI_LE_SET_SCAN_PARAMS: self._handle_status_only,
            HCI_LE_SET_RANDOM_ADDRESS: self._handle_status_only,
            # SSP reply commands — just acknowledge them
            HCI_IO_CAPABILITY_REQUEST_REPLY: self._handle_status_only,
            HCI_IO_CAPABILITY_REQUEST_NEGATIVE_REPLY: self._handle_status_only,
            HCI_USER_CONFIRMATION_REQUEST_REPLY: self._handle_status_only,
            HCI_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY: self._handle_status_only,
            HCI_LINK_KEY_REQUEST_REPLY: self._handle_link_key_request_reply,
            HCI_LINK_KEY_REQUEST_NEGATIVE_REPLY: self._handle_status_only,
        }

    @classmethod
    async def create(
        cls,
        address: BDAddress | None = None,
    ) -> tuple["VirtualController", Transport]:
        """Create a VirtualController with an opened host-side transport."""
        if address is None:
            address = BDAddress.from_string("AA:BB:CC:DD:EE:01")
        vc = cls(address=address)
        host_t, ctrl_t = _HCIPipe.pair()

        class _VCSink:
            async def on_transport_data(self, data: bytes) -> None:
                response = await vc.process(data)
                if response is not None and host_t._sink is not None:
                    await host_t._sink.on_transport_data(response)

        ctrl_t.set_sink(_VCSink())
        await host_t.open()
        await ctrl_t.open()
        # Give the controller a way to push async events to the host
        vc._host_sink = host_t._sink  # type: ignore[attr-defined]
        # Intercept future sink assignments so the reference stays current
        _orig_set_sink = host_t.set_sink

        def _patched_set_sink(sink: object) -> None:
            _orig_set_sink(sink)
            vc._host_sink = sink

        host_t.set_sink = _patched_set_sink  # type: ignore[method-assign]
        return vc, host_t

    async def _send_event_to_host(self, event: HCIEvent) -> None:
        """Push a raw HCI event to the host-side sink."""
        sink = self._host_sink
        if sink is not None:
            await sink.on_transport_data(event.to_bytes())  # type: ignore[union-attr]

    def set_acl_forwarder(self, forwarder) -> None:
        """Register an async callback invoked with each ACL frame coming from the host.

        forwarder: async callable taking HCIACLData. Used by VirtualLELink to bridge
        ACL frames between two VirtualControllers.
        """
        self._acl_forwarder = forwarder

    async def _inject_acl_to_host(self, acl) -> None:
        """Push an ACL frame to the host-side sink. Used by the loopback bridge."""
        sink = self._host_sink
        if sink is not None:
            await sink.on_transport_data(acl.to_bytes())  # type: ignore[union-attr]

    def set_sco_forwarder(self, forwarder) -> None:
        """Register an async callback invoked with each SCO frame coming from the host.

        forwarder: async callable taking HCISCOData. Used by VirtualClassicLink to bridge
        SCO frames between two VirtualControllers.
        """
        self._sco_forwarder = forwarder

    async def _inject_sco_to_host(self, sco: HCISCOData) -> None:
        """Push an SCO frame (with H4 indicator) to the host-side sink."""
        sink = self._host_sink
        if sink is not None:
            # Prepend H4 SCO indicator byte
            raw = bytes([HCI_SCO_PACKET]) + sco.to_bytes()
            await sink.on_transport_data(raw)  # type: ignore[union-attr]

    async def process(self, data: bytes) -> bytes | None:
        """Process raw H4+HCI bytes and return a response event.

        For most commands returns a Command Complete event.
        For HCI_LE_Start_Encryption returns a Command Status event and
        schedules an async Encryption_Change event via _send_event_to_host.
        Returns None if the packet is not a command.
        """
        if not data:
            return None

        # Route SCO frames to the registered forwarder (if any)
        if data[0] == HCI_SCO_PACKET:
            if self._sco_forwarder is not None and len(data) >= 4:
                raw_body = data[1:]  # strip H4 indicator
                sco = HCISCOData.from_bytes(raw_body)
                asyncio.create_task(self._sco_forwarder(sco))
            return None

        # Route ACL frames to the registered forwarder (if any)
        if data[0] == HCI_ACL_PACKET:
            if self._acl_forwarder is not None and len(data) >= 5:
                h_f = int.from_bytes(data[1:3], "little")
                handle = h_f & 0x0FFF
                pb_flag = (h_f >> 12) & 0x03
                bc_flag = (h_f >> 14) & 0x03
                length = int.from_bytes(data[3:5], "little")
                payload = data[5:5 + length]
                acl = HCIACLData(
                    handle=handle, pb_flag=pb_flag,
                    bc_flag=bc_flag, data=payload,
                )
                asyncio.create_task(self._acl_forwarder(acl))
                # Replenish host's ACL-flow credit: emit Number_Of_Completed_Packets
                # for this handle. Without this, the host stalls after exhausting
                # the buffer pool advertised in Read_(LE_)Buffer_Size. Required for
                # long PDU exchanges such as SC Passkey Entry (≈80 PDUs per side).
                asyncio.create_task(self._emit_num_completed_packets(handle, count=1))
            return None

        if data[0] != HCI_COMMAND_PACKET:
            return None

        # Parse opcode and raw parameters directly from the H4 frame so that
        # fields are always correct (typed subclasses may not implement from_bytes
        # and their __post_init__ can overwrite self.parameters with defaults).
        if len(data) < 4:
            return None
        opcode = struct.unpack_from("<H", data, 1)[0]
        param_len = data[3]
        raw_params = data[4 : 4 + param_len]

        # --- Scan-enable flag tracking (BR/EDR). The default handler dict still
        # builds the Command_Complete reply; this just keeps the controller's
        # _inquiry_scan / _page_scan state current so VirtualClassicLink can
        # consult them. ---
        if opcode == HCI_WRITE_SCAN_ENABLE and param_len >= 1:
            enable = raw_params[0]
            self._inquiry_scan = bool(enable & 0x01)
            self._page_scan = bool(enable & 0x02)

        # --- Generic bridge interceptor: VirtualClassicLink installs a
        # command_interceptor that returns synthetic responses for the BR/EDR
        # opcodes it owns. None means "pass through to default dispatch". ---
        if self.command_interceptor is not None:
            result = await self.command_interceptor(opcode, raw_params)
            if result is not None:
                return result

        # --- Encryption commands with special response sequences ---
        if opcode == HCI_LE_START_ENCRYPTION:
            handle = struct.unpack_from("<H", raw_params, 0)[0]
            if self._encryption_start_hook is not None:
                # VirtualLELink loopback: delegate the full Central↔Peripheral dance.
                rand = raw_params[2:10]   # 8-byte random value
                ediv = struct.unpack_from("<H", raw_params, 10)[0]
                ltk  = raw_params[12:28]  # 16-byte LTK
                asyncio.create_task(self._encryption_start_hook(handle, rand, ediv, ltk))
            else:
                # Stand-alone controller: immediately simulate encryption success.
                asyncio.create_task(
                    self._emit_simulated_encryption_change(handle, status=0, enabled=1)
                )
            return self._make_command_status(opcode, status=0)

        if opcode == HCI_LE_LONG_TERM_KEY_REQUEST_REPLY:
            handle = struct.unpack_from("<H", raw_params, 0)[0]
            if self._ltk_reply_hook is not None:
                ltk = raw_params[2:18]  # 16-byte LTK
                asyncio.create_task(self._ltk_reply_hook(handle, ltk))
            else:
                asyncio.create_task(
                    self._emit_simulated_encryption_change(handle, status=0, enabled=1)
                )
            return self._make_command_complete(
                opcode, b"\x00" + struct.pack("<H", handle)
            )

        if opcode == HCI_LE_LONG_TERM_KEY_REQUEST_NEGATIVE_REPLY:
            handle = struct.unpack_from("<H", raw_params, 0)[0]
            asyncio.create_task(
                self._emit_simulated_encryption_change(handle, status=0x06, enabled=0)
            )
            return self._make_command_complete(
                opcode, b"\x00" + struct.pack("<H", handle)
            )

        # --- Setup_Synchronous_Connection — Command Status + async event ---
        if opcode == HCI_SETUP_SYNCHRONOUS_CONNECTION and len(raw_params) >= 2:
            acl_handle = struct.unpack_from("<H", raw_params, 0)[0]
            if self._sco_setup_hook is not None:
                # VirtualClassicLink intercepts: allocates handles, populates maps,
                # and emits Synchronous_Connection_Complete on both controllers.
                result = await self._sco_setup_hook(acl_handle, raw_params)
                if result is not None:
                    return result
            # Stand-alone (no bridge): synthesize the event locally.
            sco_handle = 0x0100  # synthetic SCO handle issued by the virtual controller
            asyncio.create_task(
                self._emit_synchronous_connection_complete(acl_handle, sco_handle)
            )
            return self._make_command_status(opcode, status=0)

        # --- Standard Command Complete dispatch ---
        packet = decode_hci_packet(data)
        if not isinstance(packet, HCICommand):
            return None

        handler = self._handlers.get(opcode)
        if handler is not None:
            return_params = handler(packet)
        else:
            return_params = bytes([ErrorCode.UNKNOWN_COMMAND])

        return self._make_command_complete(opcode, return_params)

    def _make_command_complete(self, opcode: int, return_params: bytes) -> bytes:
        """Build a full H4+HCI Command Complete event."""
        event = HCI_Command_Complete_Event(
            num_hci_command_packets=1,
            command_opcode=opcode,
            return_parameters=return_params,
        )
        return event.to_bytes()

    def _make_command_status(self, opcode: int, status: int) -> bytes:
        """Build a full H4+HCI Command Status event."""
        event = HCI_Command_Status_Event(
            status=status,
            num_hci_command_packets=1,
            command_opcode=opcode,
        )
        return event.to_bytes()

    async def _emit_num_completed_packets(self, handle: int, count: int = 1) -> None:
        """Emit an HCI Number_Of_Completed_Packets event for *handle*.

        Releases *count* buffers back to the host's ACL flow controller so that
        long PDU exchanges (e.g. SC Passkey Entry's ~80-PDU loop) don't stall
        once the advertised buffer pool is exhausted.
        """
        # num_handles(1) + handle(2) + count(2)
        params = bytes([1]) + struct.pack("<HH", handle, count)
        event = HCIEvent(
            event_code=int(EventCode.NUM_COMPLETED_PACKETS), parameters=params,
        )
        await self._send_event_to_host(event)

    async def _emit_synchronous_connection_complete(
        self, acl_handle: int, sco_handle: int
    ) -> None:
        """Emit a synthetic Synchronous_Connection_Complete event.

        Layout per Core §7.7.35:
          status(1) + sco_handle(2 LE) + bd_addr(6) + link_type(1) +
          tx_interval(1) + retransmission_window(1) + rx_packet_length(2 LE) +
          tx_packet_length(2 LE) + air_mode(1)   [= 17 bytes total]
        """
        await asyncio.sleep(0)  # let Command Status reach the host first
        params = (
            bytes([0x00])                          # status = success
            + struct.pack("<H", sco_handle)        # SCO connection handle
            + bytes(self._address.address)         # BD_ADDR (6 bytes)
            + bytes([0x02])                        # link_type = eSCO
            + bytes([0x06])                        # tx_interval (placeholder)
            + bytes([0x02])                        # retransmission_window
            + struct.pack("<H", 0x003C)            # rx_packet_length (60 bytes)
            + struct.pack("<H", 0x003C)            # tx_packet_length (60 bytes)
            + bytes([0x02])                        # air_mode = transparent (mSBC-compatible)
        )
        event = HCIEvent(
            event_code=int(EventCode.SYNCHRONOUS_CONNECTION_COMPLETE),
            parameters=params,
        )
        await self._send_event_to_host(event)

    async def _emit_simulated_encryption_change(
        self, handle: int, status: int, enabled: int
    ) -> None:
        """Emit an HCI_Encryption_Change event after yielding to the event loop."""
        await asyncio.sleep(0)  # let Command Status/Complete reach the host first
        params = bytes([status]) + struct.pack("<H", handle) + bytes([enabled])
        event = HCIEvent(event_code=int(EventCode.ENCRYPTION_CHANGE), parameters=params)
        await self._send_event_to_host(event)

    def simulate_le_ltk_request(self, *, handle: int, rand: bytes, ediv: int) -> None:
        """Test hook: inject an LE_LTK_Request subevent from the controller to the host."""
        if len(rand) != 8:
            raise ValueError("rand must be 8 bytes")
        subevent_data = (
            bytes([int(LEMetaSubEvent.LE_LONG_TERM_KEY_REQUEST)])
            + struct.pack("<H", handle)
            + rand
            + struct.pack("<H", ediv)
        )
        meta_event = HCIEvent(
            event_code=int(EventCode.LE_META), parameters=subevent_data
        )
        asyncio.create_task(self._send_event_to_host(meta_event))

    def simulate_ssp_pairing(self, *, bd_addr: bytes, key_type: int = 0x07) -> None:
        """Test hook: inject the BR/EDR SSP event sequence.

        Emits, in order, with small async gaps:
          1. IO_Capability_Request(addr)
          2. User_Confirmation_Request(addr, numeric=0x12345678)
          3. Simple_Pairing_Complete(status=0, addr)
          4. Link_Key_Notification(addr, link_key=0x88*16, key_type=key_type)

        Args:
            bd_addr: 6-byte BD_ADDR (BT wire format, little-endian).
            key_type: Link Key type byte (default 0x07 = SC Unauthenticated P-256).
        """
        if len(bd_addr) != 6:
            raise ValueError("bd_addr must be 6 bytes")

        async def _emit():
            # 1. IO_Capability_Request
            await asyncio.sleep(0)
            evt = HCIEvent(event_code=int(EventCode.IO_CAPABILITY_REQUEST), parameters=bd_addr)
            await self._send_event_to_host(evt)

            # 2. User_Confirmation_Request — give host time to reply to step 1 first
            await asyncio.sleep(0.01)
            numeric_value = (0x12345678).to_bytes(4, "little")
            evt = HCIEvent(
                event_code=int(EventCode.USER_CONFIRMATION_REQUEST),
                parameters=bd_addr + numeric_value,
            )
            await self._send_event_to_host(evt)

            # 3. Simple_Pairing_Complete
            await asyncio.sleep(0.01)
            evt = HCIEvent(
                event_code=int(EventCode.SIMPLE_PAIRING_COMPLETE),
                parameters=bytes([0x00]) + bd_addr,
            )
            await self._send_event_to_host(evt)

            # 4. Link_Key_Notification
            await asyncio.sleep(0.01)
            link_key = b"\x88" * 16
            evt = HCIEvent(
                event_code=int(EventCode.LINK_KEY_NOTIFICATION),
                parameters=bd_addr + link_key + bytes([key_type]),
            )
            await self._send_event_to_host(evt)

        asyncio.create_task(_emit())

    # -- Handlers --------------------------------------------------------------

    def _handle_status_only(self, cmd: HCICommand) -> bytes:
        """Handler for commands that only return a status byte."""
        return b"\x00"

    def _handle_reset(self, cmd: HCICommand) -> bytes:
        return b"\x00"

    def _handle_read_bd_addr(self, cmd: HCICommand) -> bytes:
        # Address in HCI is little-endian (reversed from network order)
        return b"\x00" + bytes(reversed(self._address.address))

    def _handle_read_local_version(self, cmd: HCICommand) -> bytes:
        # status + HCI_Version(1) + HCI_Revision(2) + LMP_Version(1) + Manufacturer(2) + LMP_Subversion(2)
        return b"\x00" + struct.pack("<BHBHH", 0x0C, 0x0001, 0x0C, 0xFFFF, 0x0001)

    def _handle_read_buffer_size(self, cmd: HCICommand) -> bytes:
        # status + acl_data_packet_length(2) + sco_data_packet_length(1) + total_num_acl(2) + total_num_sco(2)
        return b"\x00" + struct.pack("<HBHH", 1024, 64, 8, 4)

    def _handle_le_read_buffer_size(self, cmd: HCICommand) -> bytes:
        # status + le_acl_data_packet_length(2) + total_num_le_acl(1)
        return b"\x00" + struct.pack("<HB", 251, 8)

    def _handle_read_local_supported_commands(self, cmd: HCICommand) -> bytes:
        """Return a permissive Supported_Commands bitmap.

        We advertise all the commands HCIController.initialize() issues so the
        tolerant-init gating (Task 3) doesn't skip anything. Tests that need a
        restricted bitmap subclass VirtualController and override this method.
        """
        from pybluehost.hci.capabilities import _OPCODE_BIT_POSITIONS

        bitmap = bytearray(64)
        for octet, bit in _OPCODE_BIT_POSITIONS.values():
            bitmap[octet] |= 1 << bit
        return b"\x00" + bytes(bitmap)

    def _handle_read_local_supported_features(self, cmd: HCICommand) -> bytes:
        # status + 8 bytes of LMP features
        return b"\x00" + b"\x00" * 8

    def _handle_read_local_extended_features(self, cmd: HCICommand) -> bytes:
        """Return an empty extended-features page with max_page=2 advertised.

        Per Core Spec 5.4 Vol 4 Part E §7.4.4 the response is:
            status(1) + page_number(1) + max_page_number(1) + features(8)
        """
        page = cmd.parameters[0] if cmd.parameters else 0
        return b"\x00" + bytes([page, 2]) + b"\x00" * 8

    def _handle_le_read_local_supported_features(self, cmd: HCICommand) -> bytes:
        # status + 8 bytes of LE features
        return b"\x00" + b"\x00" * 8

    def _handle_link_key_request_reply(self, cmd: HCICommand) -> bytes:
        # Return: status(1) + BD_ADDR(6) — spec vol4 part E 7.1.11
        # The first 6 bytes of cmd.parameters are the BD_ADDR
        bd_addr = cmd.parameters[:6] if cmd.parameters and len(cmd.parameters) >= 6 else b"\x00" * 6
        return b"\x00" + bd_addr


class _HCIPipe(Transport):
    """Private in-memory pipe used by VirtualController.create()."""

    def __init__(self) -> None:
        super().__init__()
        self._peer: "_HCIPipe | None" = None
        self._open = False

    @classmethod
    def pair(cls) -> tuple["_HCIPipe", "_HCIPipe"]:
        a = cls()
        b = cls()
        a._peer = b
        b._peer = a
        return a, b

    async def open(self) -> None:
        self._open = True

    async def close(self) -> None:
        self._open = False

    async def send(self, data: bytes) -> None:
        if not self._open:
            raise RuntimeError("_HCIPipe not open")
        if self._peer is None:
            raise RuntimeError("_HCIPipe has no peer")
        if self._peer._open and self._peer._sink is not None:
            await self._peer._sink.on_transport_data(data)

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def info(self) -> TransportInfo:
        return TransportInfo(
            type="virtual",
            description="VirtualController pipe",
            platform="any",
            details={},
        )
