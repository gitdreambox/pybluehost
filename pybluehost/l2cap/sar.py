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

    def reset(self, handle: int) -> None:
        """Drop any in-progress reassembly for ``handle``.

        Used when a framing violation is detected on the first fragment of a
        K-frame: the peer will never send the remaining fragments, so the
        buffered partial PDU must be discarded rather than held forever.
        """
        self._states.pop(handle, None)

    def feed(self, handle: int, pb_flag: int, data: bytes) -> list[tuple[int, bytes]]:
        """Feed an ACL fragment and return every L2CAP PDU it completes.

        A single ACL packet may carry several complete L2CAP PDUs back to back —
        the controller is free to coalesce, and PTS does. Returning only the
        first one silently drops the rest: for L2CAP/COS/CED/BI-29-C the Lower
        Tester packs its two response PDUs into one packet, so the second (the
        refusal carrying the identifier we were waiting on) was discarded and
        the pending LE CoC connect sat until its 5 s timeout → BTP ERROR.

        Args:
            handle: ACL connection handle.
            pb_flag: Packet Boundary flag from the ACL header.
            data: Fragment payload bytes.

        Returns:
            The ``(cid, payload)`` PDUs completed by this fragment — empty if
            more fragments are needed.
        """
        out: list[tuple[int, bytes]] = []

        if pb_flag == ACL_PB_FIRST_AUTO_FLUSH:
            # A new FIRST fragment resets any in-progress reassembly.
            self._states.pop(handle, None)
            rest = data
            while len(rest) >= _L2CAP_HDR_SIZE:
                length, cid = struct.unpack_from("<HH", rest, 0)
                body = rest[_L2CAP_HDR_SIZE:]
                if len(body) < length:
                    # Trailing partial PDU — hold it for the continuations.
                    self._states[handle] = _ReassemblyState(
                        cid=cid, expected_len=length, buf=bytearray(body),
                    )
                    return out
                out.append((cid, body[:length]))
                rest = body[length:]
            if rest:
                # A tail shorter than an L2CAP header is unrecoverable.
                self._states.pop(handle, None)
            return out

        if pb_flag == ACL_PB_CONTINUING:
            state = self._states.get(handle)
            if state is None:
                # No reassembly in progress — discard orphan continuation.
                return out
            state.buf.extend(data)
            if len(state.buf) >= state.expected_len:
                cid = state.cid
                payload = bytes(state.buf[: state.expected_len])
                del self._states[handle]
                out.append((cid, payload))
            return out

        # Unknown PB flag — ignore
        return out


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
