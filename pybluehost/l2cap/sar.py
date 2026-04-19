"""SAR engine for L2CAP PDU reassembly and segmentation."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from pybluehost.hci.constants import ACL_PB_FIRST_AUTO_FLUSH, ACL_PB_CONTINUING

# L2CAP basic header size: 2 bytes length + 2 bytes CID
_L2CAP_HDR_SIZE = 4


@dataclass
class _ReassemblyState:
    """Per-handle reassembly state."""
    cid: int = 0
    expected_len: int = 0
    buf: bytearray = field(default_factory=bytearray)


class Reassembler:
    """Reassemble ACL fragments into complete L2CAP PDUs.

    Each connection handle has independent reassembly state.
    A new FIRST fragment for the same handle resets any in-progress reassembly.
    """

    def __init__(self) -> None:
        self._states: dict[int, _ReassemblyState] = {}

    def feed(self, handle: int, pb_flag: int, data: bytes) -> tuple[int, bytes] | None:
        """Feed an ACL fragment.

        Args:
            handle: ACL connection handle.
            pb_flag: Packet Boundary flag from the ACL header.
            data: Fragment payload bytes.

        Returns:
            ``(cid, payload)`` when a full L2CAP PDU is assembled,
            or ``None`` if more fragments are needed.
        """
        if pb_flag == ACL_PB_FIRST_AUTO_FLUSH:
            # Parse L2CAP basic header from the first fragment
            if len(data) < _L2CAP_HDR_SIZE:
                # Malformed — not enough data for a header; discard
                self._states.pop(handle, None)
                return None

            length, cid = struct.unpack_from("<HH", data, 0)
            payload = data[_L2CAP_HDR_SIZE:]

            if len(payload) >= length:
                # Complete PDU in a single fragment
                self._states.pop(handle, None)
                return (cid, payload[:length])

            # Incomplete — start accumulating
            state = _ReassemblyState(cid=cid, expected_len=length, buf=bytearray(payload))
            self._states[handle] = state
            return None

        elif pb_flag == ACL_PB_CONTINUING:
            state = self._states.get(handle)
            if state is None:
                # No reassembly in progress — discard orphan continuation
                return None

            state.buf.extend(data)

            if len(state.buf) >= state.expected_len:
                cid = state.cid
                payload = bytes(state.buf[: state.expected_len])
                del self._states[handle]
                return (cid, payload)

            return None

        # Unknown PB flag — ignore
        return None


class Segmenter:
    """Segment an L2CAP PDU into ACL-sized fragments.

    Args:
        max_size: Maximum ACL payload size per segment.
    """

    def __init__(self, max_size: int) -> None:
        if max_size < 1:
            raise ValueError("max_size must be at least 1")
        self._max_size = max_size

    def segment(self, pdu: bytes) -> list[tuple[int, bytes]]:
        """Split an L2CAP PDU into ``(pb_flag, payload)`` tuples.

        The first segment uses ``ACL_PB_FIRST_AUTO_FLUSH``; subsequent
        segments use ``ACL_PB_CONTINUING``.
        """
        if not pdu:
            return []

        segments: list[tuple[int, bytes]] = []
        offset = 0
        first = True

        while offset < len(pdu):
            chunk = pdu[offset : offset + self._max_size]
            pb = ACL_PB_FIRST_AUTO_FLUSH if first else ACL_PB_CONTINUING
            segments.append((pb, chunk))
            offset += self._max_size
            first = False

        return segments
