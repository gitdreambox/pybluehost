"""Parse --target string into (BDAddress, AddressType)."""
from __future__ import annotations

from pybluehost.core.address import AddressType, BDAddress


TARGET_HELP = "BD_ADDR, e.g. A0:90:B5:10:40:82 or A090B5104082"


def _normalize_bd_addr(addr: str) -> str:
    if ":" in addr or len(addr) != 12:
        return addr
    try:
        int(addr, 16)
    except ValueError:
        return addr
    return ":".join(addr[i : i + 2] for i in range(0, 12, 2))


def parse_target_arg(s: str) -> tuple[BDAddress, AddressType]:
    """Parse a --target CLI argument.

    Formats:
        AA:BB:CC:DD:EE:FF              → public address
        AA:BB:CC:DD:EE:FF/public       → public
        AA:BB:CC:DD:EE:FF/random       → random
    """
    if "/" in s:
        addr_s, type_s = s.split("/", 1)
        type_s = type_s.lower()
        if type_s == "public":
            atype = AddressType.PUBLIC
        elif type_s == "random":
            atype = AddressType.RANDOM
        else:
            raise ValueError(f"Unknown address type: {type_s!r}")
    else:
        addr_s = s
        atype = AddressType.PUBLIC
    addr_s = _normalize_bd_addr(addr_s)
    return (BDAddress.from_string(addr_s, type=atype), atype)
