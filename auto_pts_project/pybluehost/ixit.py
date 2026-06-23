"""IXIT — Implementation eXtra Information for Testing.

Hand-written test parameters PTS asks for. autoptsclient passes these values
to PTS via the PTSControl COM API.

Values are strings (PTS XML is string-typed). Hex addresses are uppercase
without separators.

**Operator MUST customise ``TSPX_bd_addr_iut`` before running real PTS tests.**
Default is ``001122334455`` (placeholder — won't match any real adapter).
"""

IXIT_GAP: dict[str, str] = {
    "TSPX_bd_addr_iut": "001122334455",         # 6-byte hex, no separators
    "TSPX_bd_addr_iut_le": "001122334455",
    "TSPX_iut_role_initiator": "TRUE",
    "TSPX_iut_role_acceptor": "TRUE",
    "TSPX_pin_code": "0000",
    "TSPX_delete_link_key": "TRUE",
    "TSPX_security_enabled": "FALSE",
    "TSPX_use_implicit_send": "FALSE",
}

IXIT_GATT: dict[str, str] = {
    "TSPX_bd_addr_iut": "001122334455",
    "TSPX_delete_link_key": "TRUE",
    "TSPX_iut_use_dynamic_pts_address": "FALSE",
}

IXIT_L2CAP: dict[str, str] = {
    "TSPX_bd_addr_iut": "001122334455",
    "TSPX_security_enabled": "FALSE",
    "TSPX_psm": "0080",                         # default LE PSM for tests
    "TSPX_le_psm": "0080",
}

IXIT_SMP: dict[str, str] = {
    "TSPX_bd_addr_iut": "001122334455",
    "TSPX_io_capability": "NoInputNoOutput",
    "TSPX_oob_data": "00000000000000000000000000000000",  # 16-byte TK as hex
    "TSPX_fixed_passkey": "000000",
}
