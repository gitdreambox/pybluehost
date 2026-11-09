"""GATT WID handler adapter for PyBlueHost. Same shape as ``gap.py``."""
from __future__ import annotations

import struct

try:
    from autopts.wid import generic_wid_hdl
except ImportError:  # autoptsclient not installed (PyBlueHost CI)
    generic_wid_hdl = None

_UPSTREAM_MODULE = "autopts.wid.gatt"


def _char_value_handles(pred):
    """Return the value handles of characteristics whose (value_perm, char_prop)
    satisfy ``pred``, in handle order. Queries the committed server db via BTP
    GET_ATTRIBUTES/GET_ATTRIBUTE_VALUE (modeled on upstream hdl_wid_110)."""
    from autopts.pybtp import btp
    from autopts.pybtp.types import Perm, Prop  # noqa: F401  (used by callers' preds)

    handles = []
    chrcs = btp.gatts_get_attrs(type_uuid='2803')
    for chrc in chrcs:
        handle, _perm, _type_uuid = chrc
        chrc_val = btp.gatts_get_attr_val(btp.pts_addr_type_get(),
                                          btp.pts_addr_get(), handle)
        if not chrc_val:
            continue
        _att_rsp, val_len, val = chrc_val
        hdr_len = struct.calcsize('<BH')
        uuid_len = val_len - hdr_len
        prop, value_handle, _chrc_uuid = struct.unpack(f"<BH{uuid_len}s", val)
        chrc_value_attr = btp.gatts_get_attrs(start_handle=value_handle,
                                              end_handle=value_handle)
        if not chrc_value_attr:
            continue
        vhandle, vperm, _vtype = chrc_value_attr[0]
        if pred(vperm, prop):
            handles.append(vhandle)
    return handles


def _plain_readable_handles():
    from autopts.pybtp.types import Perm, Prop
    return _char_value_handles(lambda vperm, prop: (vperm & Perm.read) and (prop & Prop.read))


def _read_multiple_handles(params):
    """Pick the (first, second) char-value handle pair for a Read Multiple WID
    (123/124). Normal cases (GAR/BV-05) need two plain-readable chars; the
    security BI cases (BI-20 authz / BI-21 authn / BI-22 enc-key-size, and the
    variable-length BI-40/42/44) need a handle of a char GATED by that security
    level so the IUT's Read Multiple fails with the expected ATT error."""
    from autopts.pybtp.types import Perm
    name = (getattr(params, "test_case_name", "") or "")
    if "BI-20" in name or "BI-40" in name:      # Insufficient Authorization
        sec = _char_value_handles(lambda v, p: v & Perm.read_authz)
    elif "BI-21" in name or "BI-42" in name:    # Insufficient Authentication
        sec = _char_value_handles(lambda v, p: v & Perm.read_authn)
    elif "BI-22" in name or "BI-44" in name:    # Insufficient Encryption Key Size
        sec = _char_value_handles(lambda v, p: v & Perm.read_enc)
    elif "BI-18" in name or "BI-36" in name:    # Read Not Permitted
        sec = _char_value_handles(
            lambda v, p: not (v & (Perm.read | Perm.read_enc
                                   | Perm.read_authn | Perm.read_authz)))
    else:
        sec = []
    if sec:
        first = sec[0]
        rest = [h for h in _plain_readable_handles() if h != first]
        return first, (rest[0] if rest else first)
    plain = _plain_readable_handles()
    first = plain[0] if plain else 0
    second = plain[1] if len(plain) > 1 else first
    return first, second


def hdl_wid_123(params):
    """WID 123: "Enter the First Handle(0x) for Read Multiple that will satisfy
    the test case." Returns a plain-readable char for normal cases, or a
    security-gated char for the Read Multiple security BI cases."""
    first, _ = _read_multiple_handles(params)
    return f'{first:04x}'


def hdl_wid_124(params):
    """WID 124: "Enter the Second Handle(0x) for Read Multiple." """
    _, second = _read_multiple_handles(params)
    return f'{second:04x}'


def hdl_wid_402(params):
    """WID 402: "Please initiate an L2CAP Credit Based Connection using LE
    signaling channel to the PTS." GATT/CL/GAR/BV-10 (Read Multiple Variable
    Length over multiple bearers) aborts with MissingWIDError here — upstream
    autopts/wid/gatt.py has no handler for this WID number in the GATT space
    (mynewt's project module answers a bare True without opening anything).
    Our stack has a working EATT client (BTP EATT_CONNECT 0x1f over the fixed
    SPSM 0x0027), so actually open the bearer: the case's EATT-bearer reads
    later in the flow need the channel up. One channel suffices — the other
    bearer of BV-10 is the unenhanced ATT fixed channel."""
    from autopts.pybtp import btp

    # (None, None) = resolve the PTS address internally, the same idiom as
    # upstream hdl_wid_144's l2cap_disconn_eatt_chans(None, None, 1).
    btp.eatt_conn(None, None, num=1)
    return True


def hdl_wid_147(params):
    """WID 147: "Please send two Read Multiple Variable Length characteristic
    requests using these handles ... Required Bearers are ATT and EATT bearer."
    (GATT/CL/GAR/BV-10). Upstream fires the two BTP commands and returns True
    WITHOUT storing any verify value, so the case's WID 55
    (verify_multiple_read_description) always runs on an empty verify_values
    and answers No — no reference project registers BV-10, so the gap was
    never exercised upstream. Override: after firing the two commands, drain
    both bearer responses (the IUT answers command #1 from the ATT bearer and
    command #2 from the EATT bearer) and store the value blob once — the same
    shape hdl_wid_140 stores for BV-08's WID-55 substring check."""
    from autopts.ptsprojects.testcase import MMI
    from autopts.pybtp import btp
    from autopts.pybtp.btp.gatt import get_iut

    MMI.reset()
    MMI.parse_description(params.description)

    hdl1 = MMI.args[0]
    hdl2 = MMI.args[1]
    at, ad = btp.pts_addr_type_get(), btp.pts_addr_get()
    btp.gattc_read_multiple_var(at, ad, hdl1, hdl2)
    btp.gattc_read_multiple_var(at, ad, hdl1, hdl2)

    if params.test_case_name.startswith("GATT/CL/GAR/BV"):
        # Both requests carry the same handle set, so both bearer responses
        # hold the same value blob; store one and drain the other so no stale
        # response frame is left for a later read().
        btp.gattc_read_multiple_var_rsp(store_rsp=False, store_val=True)
        get_iut().btp_socket.read()
    return True


def gatt_wid_hdl(wid, description, test_case_name):
    if generic_wid_hdl is None:
        raise RuntimeError("autoptsclient is not installed; cannot dispatch GATT WID")
    return generic_wid_hdl(wid, description, test_case_name,
                           [__name__, _UPSTREAM_MODULE])
