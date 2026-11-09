"""IXIT — Implementation eXtra Information for Testing.

Hand-written test parameters PTS asks for. autoptsclient passes these values
to PTS via the PTSControl COM API.

Values are strings (PTS XML is string-typed). Hex addresses are uppercase
without separators.

``TSPX_bd_addr_iut`` is the IUT public address. Currently a **BE200**
(``A085272F6015``, ``usb:8087:0036#1``); the PTS dongle is the other BE200
(``6&1687A1FD&0&3``). Both roles are BE200 because bare-HCI probing shows the
AX201 has none of the newer LE commands at all — no subrate
(``0x207D``/``0x207E``), no ISO (``0x2061``, ``0x2068``) — while the BE200
implements the subrate and ISO/BIS families.

Neither supports the BT 5.1 PAST commands (``0x2059``/``0x205A``/``0x205C``/
``0x205D`` all answer 0x01 Unknown HCI Command on both dongles), so the
GAP/PADV sync-transfer cases are hardware-blocked whichever dongle is the IUT.

BE200 dongles are prone to a firmware hang (they accept the USB claim and then
never answer HCI Reset; software recovery does not work, only a physical
replug or reboot).

The profile pre-conditions also push the address dynamically from the live
controller via ``update_pixit_param``; the static value here is the fallback.

⚠️ The ``8087:0036`` enumeration order swaps across replug/reboot. Re-read each
dongle with HCI_Read_BD_ADDR and confirm which occurrence is which before a run.
"""
from __future__ import annotations

import logging
import xmlrpc.client

logger = logging.getLogger(__name__)


def apply_pixits(pts, profile: str, mapping: "dict[str, str]") -> None:
    """Push a {pixit_name: value} mapping into the PTS workspace for `profile`.

    Resilient to PIXIT-name drift: a parameter the workspace's PTS version does
    not define (BadPixitException / PTSCONTROL_E_PIXIT_PARAM_NOT_FOUND) is logged
    and skipped rather than aborting the whole run, so one stale name in our
    hand-written IXIT doesn't kill testing of an entire profile. Any other XML-RPC
    fault is re-raised.
    """
    for name, value in mapping.items():
        try:
            pts.set_pixit(profile, name, value)
        except xmlrpc.client.Fault as fault:
            msg = str(fault)
            if "PIXIT_PARAM_NOT_FOUND" in msg or "BadPixit" in msg:
                logger.warning(
                    "IXIT %s.%s not present in this PTS workspace; skipping", profile, name,
                )
                continue
            raise


def update_pixit(pts, profile: str, name: str, value) -> None:
    """Like ``pts.update_pixit_param`` but resilient to PIXIT_PARAM_NOT_FOUND.

    The dynamic address PIXITs pushed from the profile pre-conditions
    (``TSPX_bd_addr_iut`` / ``TSPX_using_public_device_address`` / …) are not
    defined in every PTS workspace — e.g. the zephyr reference workspace omits
    some. A missing PIXIT must not abort the whole test case; log and skip. Any
    other XML-RPC fault is re-raised.

    ``value`` may be a callable, in which case it is invoked lazily at
    pre-condition time (so the live controller address is read then, not at
    module import).
    """
    try:
        v = value() if callable(value) else value
        pts.update_pixit_param(profile, name, v)
    except xmlrpc.client.Fault as fault:
        msg = str(fault)
        if "PIXIT_PARAM_NOT_FOUND" in msg or "BadPixit" in msg:
            logger.warning("PIXIT %s.%s not present; skipping update", profile, name)
            return
        raise

IXIT_GAP: dict[str, str] = {
    "TSPX_bd_addr_iut": "A085272F6015",         # 6-byte hex, no separators
    "TSPX_bd_addr_iut_le": "A085272F6015",
    "TSPX_iut_role_initiator": "TRUE",
    "TSPX_iut_role_acceptor": "TRUE",
    "TSPX_pin_code": "0000",
    "TSPX_delete_link_key": "TRUE",
    "TSPX_security_enabled": "FALSE",
    "TSPX_use_implicit_send": "FALSE",
    # PTS per-test watchdog. The CSR8510 IUT->PTS initiator link is flaky
    # (~50% 0x3E drops -> retry), so slow connection procedures otherwise die
    # with "UNKNOWN VERDICT: Timeout. Adjust TSPX_time_guard". 300s matches the
    # bluez reference workspace. Omitted silently if this PTS version lacks it.
    "TSPX_time_guard": "300000",
}

IXIT_GATT: dict[str, str] = {
    "TSPX_bd_addr_iut": "A085272F6015",
    "TSPX_delete_link_key": "TRUE",
    "TSPX_iut_use_dynamic_pts_address": "FALSE",
    "TSPX_time_guard": "300000",                # see IXIT_GAP note
}

IXIT_L2CAP: dict[str, str] = {
    "TSPX_bd_addr_iut": "A085272F6015",
    "TSPX_security_enabled": "FALSE",
    "TSPX_psm": "0080",                         # default LE PSM for tests
    "TSPX_le_psm": "0080",
    "TSPX_time_guard": "300000",                # see IXIT_GAP note
    # Supported MTU/MPS ranges for Enhanced Credit-Based channels. These are not
    # optional knobs: several ECFC cases terminate early with a Pass verdict when
    # the range collapses to a single value (L2CAP.TS 4.9.1.17/4.9.1.18 step 1),
    # and the per-case overrides that trigger that need the PIXITs to exist.
    # Values mirror upstream zephyr.
    "TSPX_l2ca_cbmps_min": "0040",
    "TSPX_l2ca_cbmps_max": "0100",
    "TSPX_l2ca_cbmtu_min": "0040",
    "TSPX_l2ca_cbmtu_max": "0100",
    # ECFC/BV-38 + LE/CFC/BV-29 ("Dynamically Allocated Source CID") repeat the
    # connect/disconnect cycle this many times. The workspace default is far
    # larger than the LT script's own buffer, which dies mid-case; both
    # reference IUTs (zephyr set_pixits, mynewt common pre-conditions) pin 2.
    "TSPX_l2ca_num_concurrent_credit_based_connections": "2",
}

IXIT_SMP: dict[str, str] = {
    "TSPX_bd_addr_iut": "A085272F6015",
    "TSPX_io_capability": "DisplayOnly",
    "TSPX_oob_data": "00000000000000000000000000000000",  # 16-byte TK as hex
    "TSPX_fixed_passkey": "000000",
    "TSPX_time_guard": "300000",                # see IXIT_GAP note
}
