from __future__ import annotations

from typing import Iterator


H4_COMMAND = 0x01
H4_ACL = 0x02
H4_SCO = 0x03
H4_EVENT = 0x04
H4_ISO = 0x05


# indicator → (header_len_after_indicator, length_field_offset_in_header, length_field_bytes)
_HEADER_SHAPE: dict[int, tuple[int, int, int]] = {
    H4_COMMAND: (3, 2, 1),
    H4_ACL:     (4, 2, 2),
    H4_SCO:     (3, 2, 1),
    H4_EVENT:   (2, 1, 1),
    H4_ISO:     (4, 2, 2),
}


class H4Framer:
    """Accumulate bytes and yield complete H4 packets (indicator + header + payload)."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> Iterator[bytes]:
        self._buf.extend(data)
        while True:
            if not self._buf:
                return
            indicator = self._buf[0]
            if indicator not in _HEADER_SHAPE:
                raise ValueError(f"Unknown H4 indicator 0x{indicator:02x}")
            header_len, len_off, len_bytes = _HEADER_SHAPE[indicator]
            if len(self._buf) < 1 + header_len:
                return
            if len_bytes == 1:
                payload_len = self._buf[1 + len_off]
            else:
                payload_len = int.from_bytes(
                    self._buf[1 + len_off : 1 + len_off + len_bytes], "little"
                )
                if indicator == H4_ISO:
                    payload_len &= 0x3FFF
            total = 1 + header_len + payload_len
            if len(self._buf) < total:
                return
            packet = bytes(self._buf[:total])
            del self._buf[:total]
            yield packet
