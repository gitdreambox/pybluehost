"""RFCOMM WID handler adapter for PyBlueHost — same shape as ``sdp.py``.

Routes through ``generic_wid_hdl`` with THIS module first in the search path
so any ``hdl_wid_<N>`` defined below overrides upstream, then falls back to
``autopts.wid.rfcomm``.
"""
from __future__ import annotations

try:
    from autopts.wid import generic_wid_hdl
except ImportError:  # autoptsclient not installed (PyBlueHost CI)
    generic_wid_hdl = None

_UPSTREAM_MODULE = "autopts.wid.rfcomm"


def hdl_wid_20(params):
    """Take action to initiate an RFCOMM service level connection (l2cap).

    RFCOMM/DEVA/RFC/BV-01-C only wants the SESSION initialised (SABM(0)↔UA)
    — PTS drops the ACL when an un-invited PN/DLC for DLCI n follows (there
    is no server channel registered in that case). Our BTP service treats
    channel 0 as "session only, no DLC", so re-issue the connect with it.
    Every other case uses the upstream full session+DLC flow.
    """
    if params.test_case_name in ("RFCOMM/DEVA/RFC/BV-01-C",):
        from autopts.pybtp import btp
        from autopts.pybtp import defs
        from autopts.pybtp.types import addr_str_to_le_bytes
        stack = __import__("autopts.ptsprojects.stack", fromlist=["get_stack"]).get_stack()
        stack.gap.set_passkey(None)
        if not stack.gap.is_connected():
            btp.gap_connect(bd_addr_type=defs.BTP_BR_ADDRESS_TYPE)
            btp.gap_wait_for_connection()
        btp.gap_pair(bd_addr_type=defs.BTP_BR_ADDRESS_TYPE)
        # Session-only connect: RFCOMM CONNECT with channel 0 opens the
        # multiplexer (SABM 0 / UA) and stops there.
        bd_addr = btp.pts_addr_get(None)
        data = bytearray([defs.BTP_BR_ADDRESS_TYPE])
        data += addr_str_to_le_bytes(bd_addr)
        data += bytes([0])
        get_iut = __import__("autopts.pybtp.btp.btp", fromlist=["get_iut"]).get_iut
        iutctl = get_iut()
        iutctl.btp_socket.send_wait_rsp(0x20, 0x02, 0, bytes(data))
        return True
    from autopts.wid.rfcomm import hdl_wid_20 as _upstream
    return _upstream(params)


def hdl_wid_14(params):
    """Take action to close the DLC (session shutdown in BV-04's flow).

    Upstream sends DISC on the data channel, but by the time WID 14 arrives
    in BV-04 PTS has already released the DLC — the remaining action is the
    multiplexer shutdown. Re-issue the disconnect with channel 0 (our BTP
    convention for DISC on DLCI 0); other cases delegate upstream.
    """
    if params.test_case_name in ("RFCOMM/DEVA-DEVB/RFC/BV-04-C",):
        # Shutdown-session flow: DISC on the DLC first (if still open), then
        # DISC on the control channel — PTS judges both halves.
        from autopts.pybtp import btp
        from autopts.pybtp import defs
        from autopts.pybtp.types import addr_str_to_le_bytes
        bd_addr = btp.pts_addr_get(None)
        get_iut = __import__("autopts.pybtp.btp.btp", fromlist=["get_iut"]).get_iut
        iutctl = get_iut()
        for channel in (5, 0):
            data = bytearray([defs.BTP_BR_ADDRESS_TYPE])
            data += addr_str_to_le_bytes(bd_addr)
            data += bytes([channel])
            try:
                iutctl.btp_socket.send_wait_rsp(0x20, 0x03, 0, bytes(data))
            except Exception:
                pass  # DLC already released by PTS -> session DISC still goes
        return True
    from autopts.wid.rfcomm import hdl_wid_14 as _upstream
    return _upstream(params)


def rfcomm_wid_hdl(wid, description, test_case_name):
    if generic_wid_hdl is None:
        raise RuntimeError("autoptsclient is not installed; cannot dispatch RFCOMM WID")
    return generic_wid_hdl(wid, description, test_case_name,
                           [__name__, _UPSTREAM_MODULE])
