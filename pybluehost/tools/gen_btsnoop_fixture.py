"""Generate minimal btsnoop fixture files for testing."""
import logging
import struct
from pathlib import Path

from pybluehost.logging_config import configure_logging

logger = logging.getLogger(__name__)

BTSNOOP_MAGIC = b"btsnoop\x00"
BTSNOOP_VERSION = 1
BTSNOOP_DLT = 1002  # H4

# HCI Reset Command (0x0C03)
HCI_RESET = bytes([0x01, 0x03, 0x0C, 0x00])
# Command Complete for Reset: status=0
HCI_CC_RESET = bytes([0x04, 0x0E, 0x04, 0x01, 0x03, 0x0C, 0x00])
# HCI Read_BD_ADDR Command
HCI_READ_BD_ADDR = bytes([0x01, 0x09, 0x10, 0x00])
# Command Complete for Read_BD_ADDR: status=0, addr=AA:BB:CC:DD:EE:01
HCI_CC_READ_BD_ADDR = bytes([
    0x04, 0x0E, 0x0A, 0x01, 0x09, 0x10, 0x00,
    0x01, 0xEE, 0xDD, 0xCC, 0xBB, 0xAA,
])


def write_btsnoop(path: str, packets: list[tuple[bytes, int]]) -> None:
    """Write minimal btsnoop file. packets = list of (data, direction_flag)."""
    with open(path, "wb") as f:
        f.write(BTSNOOP_MAGIC)
        f.write(struct.pack(">II", BTSNOOP_VERSION, BTSNOOP_DLT))
        ts = 0x00E26C4A3E3C0000  # arbitrary timestamp
        for data, flags in packets:
            orig_len = len(data)
            inc_len = orig_len
            f.write(struct.pack(">IIIIq", orig_len, inc_len, flags, 0, ts))
            f.write(data)
            ts += 1000


if __name__ == "__main__":
    configure_logging()
    outdir = Path(__file__).parent.parent.parent / "tests" / "data"
    outdir.mkdir(parents=True, exist_ok=True)
    packets = [
        (HCI_RESET, 0x02),            # host→controller
        (HCI_CC_RESET, 0x03),          # controller→host
        (HCI_READ_BD_ADDR, 0x02),      # host→controller
        (HCI_CC_READ_BD_ADDR, 0x03),   # controller→host
    ]
    out = outdir / "hci_reset.btsnoop"
    write_btsnoop(str(out), packets)
    logger.info("Generated %s", out)
