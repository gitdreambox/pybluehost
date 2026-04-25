"""Parse --target string into (BDAddress, AddressType)."""
from __future__ import annotations

from pybluehost.core.address import AddressType, BDAddress


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
    return (BDAddress.from_string(addr_s), atype)
