"""VirtualSnifferSink — a TraceSink that injects HCI into an analyzer backend."""
from __future__ import annotations

import logging

from pybluehost.core.trace import TraceEvent
from pybluehost.sniffer.backend import KNOWN_H4_TYPES, SnifferBackend

logger = logging.getLogger(__name__)

_HCI_LAYER = "hci"


class VirtualSnifferSink:
    """TraceSink that injects HCI events into an Ellisys / WPS analyzer.

    See design spec §5.2.

    - filters source_layer == "hci"
    - strips raw_bytes[0] (H4 type) and dispatches to the backend
    - unknown H4 types are skipped + warned once per type
    """

    def __init__(self, backend: SnifferBackend) -> None:
        self._backend = backend
        self._warned_unknown_h4: set[int] = set()

    async def on_trace(self, event: TraceEvent) -> None:
        if event.source_layer != _HCI_LAYER:
            return
        raw = event.raw_bytes
        if len(raw) < 1:
            return
        h4_type = raw[0]
        if h4_type not in KNOWN_H4_TYPES:
            if h4_type not in self._warned_unknown_h4:
                logger.warning(
                    "VirtualSnifferSink: skipping unknown H4 type 0x%02X", h4_type
                )
                self._warned_unknown_h4.add(h4_type)
            return
        await self._backend.inject(h4_type, event.direction, raw[1:], event.wall_clock)

    async def flush(self) -> None:
        # Injection is fire-and-forget; no buffered file to flush.
        pass

    async def close(self) -> None:
        await self._backend.stop()


import sys  # noqa: E402

from pybluehost.cli._sniffer_arg import SnifferSpec  # noqa: E402
from pybluehost.core.errors import SnifferUnavailableError  # noqa: E402


async def build_virtual_sniffer_sink(spec: SnifferSpec) -> "VirtualSnifferSink":
    """Construct backend + start it + wrap in a VirtualSnifferSink.

    Must be called BEFORE Stack._build so HCI init traffic is captured.
    Non-Windows → SnifferUnavailableError (clear message).
    """
    if sys.platform != "win32":
        raise SnifferUnavailableError(
            "virtual sniffer requires Windows + Ellisys/WPS analyzer software"
        )

    if spec.backend == "ellisys":
        from pybluehost.sniffer.ellisys import (
            DEFAULT_ELLISYS_TCP_PORT,
            DEFAULT_ELLISYS_UDP_PORT,
            EllisysBackend,
        )
        backend: SnifferBackend = EllisysBackend(
            host=spec.options.get("host", "127.0.0.1"),
            tcp_port=int(spec.options.get("tcp", DEFAULT_ELLISYS_TCP_PORT)),
            udp_port=int(spec.options.get("udp", DEFAULT_ELLISYS_UDP_PORT)),
            ellisys_path=spec.options.get("ellisys-path"),
        )
    elif spec.backend == "wps":
        from pybluehost.sniffer.wps import (
            LiveImportLibrary,
            WpsBackend,
            find_wps_install,
            validate_wps_install,
        )
        wps_path = spec.options.get("wps-path") or find_wps_install()
        if wps_path is None:
            raise SnifferUnavailableError(
                "未检测到 Teledyne WPS 安装。\n"
                "  如何解决: 安装 Wireless Protocol Suite 4.60+，或用 "
                "--virtual-sniffer=wps:wps-path=<安装根目录> 指定。"
            )
        validate_wps_install(wps_path)   # raises SnifferError with how-to-fix
        backend = WpsBackend(
            library=LiveImportLibrary.load_default(wps_path), wps_path=wps_path
        )
    else:   # parser already enforces but be defensive
        raise SnifferUnavailableError(f"unknown sniffer backend: {spec.backend}")

    await backend.start()
    return VirtualSnifferSink(backend)
