"""Stack — top-level factory that assembles all Bluetooth layers."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pybluehost.ble.security import SecurityConfig
from pybluehost.core.address import BDAddress
from pybluehost.core.types import IOCapability


# ---------------------------------------------------------------------------
# StackMode + StackConfig
# ---------------------------------------------------------------------------

class StackMode(str, Enum):
    LIVE = "live"
    VIRTUAL = "virtual"
    REPLAY = "replay"


@dataclass
class StackConfig:
    """Configuration for a Stack instance."""

    # GAP
    device_name: str = "PyBlueHost"
    appearance: int = 0x0000
    le_io_capability: IOCapability = IOCapability.NO_INPUT_NO_OUTPUT
    classic_io_capability: IOCapability = IOCapability.DISPLAY_YES_NO

    # Security
    security: SecurityConfig = field(default_factory=SecurityConfig)

    # HCI
    command_timeout: float = 5.0

    # Trace
    trace_sinks: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Stack
# ---------------------------------------------------------------------------

class Stack:
    """Top-level Bluetooth stack — assembles HCI, L2CAP, BLE, Classic, GAP.

    Use factory methods (``virtual()``, ``from_uart()``, etc.) to create.
    """

    def __init__(self) -> None:
        self._transport: Any = None
        self._hci: Any = None
        self._l2cap: Any = None
        self._gap: Any = None
        self._gatt_server: Any = None
        self._trace: Any = None
        self._sdp: Any = None
        self._rfcomm: Any = None
        self._local_address: BDAddress | None = None
        self._powered = False
        self._mode: StackMode = StackMode.LIVE
        self._config: StackConfig = StackConfig()

    # -- Factory methods -----------------------------------------------------

    @classmethod
    async def _build(
        cls,
        transport: Any,
        config: StackConfig | None = None,
        mode: StackMode = StackMode.LIVE,
    ) -> Stack:
        """Internal factory: assemble layers on a given transport."""
        from pybluehost.ble.gap import (
            BLEAdvertiser,
            BLEConnectionManager,
            BLEScanner,
            ExtendedAdvertiser,
            PrivacyManager,
            WhiteList,
        )
        from pybluehost.ble.gatt import GATTServer
        from pybluehost.classic.gap import (
            ClassicConnectionManager,
            ClassicDiscoverability,
            ClassicDiscovery,
            SSPManager,
        )
        from pybluehost.classic.rfcomm import RFCOMMManager
        from pybluehost.classic.sdp import SDPServer
        from pybluehost.core.trace import TraceSystem
        from pybluehost.gap import GAP
        from pybluehost.hci.controller import HCIController
        from pybluehost.l2cap.manager import L2CAPManager

        cfg = config or StackConfig()
        stack = cls()
        stack._transport = transport
        stack._mode = mode
        stack._config = cfg

        # 1. Trace
        trace = TraceSystem()
        for sink in cfg.trace_sinks:
            trace.add_sink(sink)
        stack._trace = trace

        # 2. HCI Controller
        hci = HCIController(
            transport=transport,
            trace=trace,
            command_timeout=cfg.command_timeout,
        )
        stack._hci = hci

        # 3. HCI init sequence
        await asyncio.wait_for(hci.initialize(), timeout=cfg.command_timeout * 20)
        stack._powered = True

        # 3a. Read BD_ADDR for local_address
        from pybluehost.hci.packets import HCI_Read_BD_ADDR_Command
        addr_event = await hci.send_command(HCI_Read_BD_ADDR_Command())
        if hasattr(addr_event, "return_parameters") and len(addr_event.return_parameters) >= 7:
            raw_addr = addr_event.return_parameters[1:7]
            stack._local_address = BDAddress(raw_addr)

        # 4. L2CAP
        l2cap = L2CAPManager(hci=hci)
        stack._l2cap = l2cap

        # 5. BLE layers
        gatt_server = GATTServer()
        stack._gatt_server = gatt_server

        # 6. Classic layers
        sdp = SDPServer()
        stack._sdp = sdp
        rfcomm = RFCOMMManager()
        stack._rfcomm = rfcomm

        # 7. GAP (unified)
        gap = GAP(
            ble_advertiser=BLEAdvertiser(hci=hci),
            ble_scanner=BLEScanner(hci=hci),
            ble_connections=BLEConnectionManager(hci=hci),
            ble_privacy=PrivacyManager(hci=hci),
            classic_discovery=ClassicDiscovery(hci=hci),
            classic_discoverability=ClassicDiscoverability(hci=hci),
            classic_connections=ClassicConnectionManager(hci=hci),
            classic_ssp=SSPManager(hci=hci),
            whitelist=WhiteList(hci=hci),
            ble_extended_advertiser=ExtendedAdvertiser(hci=hci),
        )
        stack._gap = gap

        return stack

    @classmethod
    async def from_usb(
        cls,
        vendor: str | None = None,
        bus: int | None = None,
        address: int | None = None,
        config: StackConfig | None = None,
    ) -> Stack:
        """Build a live Stack on a USB Bluetooth adapter."""
        from pybluehost.transport.usb import USBTransport

        transport = USBTransport.auto_detect(vendor=vendor, bus=bus, address=address)
        await transport.open()
        try:
            return await cls._build(transport, config, StackMode.LIVE)
        except Exception:
            close = getattr(transport, "close", None)
            if close is not None:
                await close()
            raise

    @classmethod
    async def from_uart(
        cls,
        port: str,
        baudrate: int = 115200,
        config: StackConfig | None = None,
    ) -> Stack:
        """Build a live Stack on a UART HCI link."""
        from pybluehost.transport.uart import UARTTransport

        transport = UARTTransport(port=port, baudrate=baudrate)
        await transport.open()
        try:
            return await cls._build(transport, config, StackMode.LIVE)
        except Exception:
            close = getattr(transport, "close", None)
            if close is not None:
                await close()
            raise

    @classmethod
    async def virtual(
        cls,
        config: StackConfig | None = None,
    ) -> Stack:
        """Create a single Stack backed by a software-emulated VirtualController.

        No real Bluetooth hardware required; suitable for unit/integration tests
        and CLI experimentation.
        """
        from pybluehost.hci.virtual import VirtualController

        vc, host_t = await VirtualController.create()
        stack = await cls._build(host_t, config, StackMode.VIRTUAL)
        stack._local_address = vc._address
        return stack

    # -- Lifecycle -----------------------------------------------------------

    async def power_on(self) -> None:
        """Re-initialize HCI after power_off."""
        if not self._powered:
            await asyncio.wait_for(
                self._hci.initialize(),
                timeout=self._config.command_timeout * 20,
            )
            self._powered = True

    async def power_off(self) -> None:
        """Shut down connections and advertising, keep transport open."""
        self._powered = False

    async def close(self) -> None:
        """Release all resources."""
        self._powered = False
        if self._transport is not None and hasattr(self._transport, "close"):
            await self._transport.close()

    async def __aenter__(self) -> Stack:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # -- Properties ----------------------------------------------------------

    @property
    def hci(self) -> Any:
        return self._hci

    @property
    def l2cap(self) -> Any:
        return self._l2cap

    @property
    def gap(self) -> Any:
        return self._gap

    @property
    def gatt_server(self) -> Any:
        return self._gatt_server

    @property
    def sdp(self) -> Any:
        return self._sdp

    @property
    def rfcomm(self) -> Any:
        return self._rfcomm

    @property
    def trace(self) -> Any:
        return self._trace

    @property
    def local_address(self) -> BDAddress | None:
        return self._local_address

    @property
    def is_powered(self) -> bool:
        return self._powered

    @property
    def mode(self) -> StackMode:
        return self._mode
