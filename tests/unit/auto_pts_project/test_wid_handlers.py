"""pybluehost_iut.wid.* — function-style WID adapters (auto-pts master shape)."""
from __future__ import annotations

import importlib
import sys
import types

import pytest

PROFILES = ("gap", "gatt", "l2cap", "sm")
HANDLER = {"gap": "gap_wid_hdl", "gatt": "gatt_wid_hdl",
           "l2cap": "l2cap_wid_hdl", "sm": "sm_wid_hdl"}


def _import_fresh(profile):
    """Import the wid module, dropping any cached copy first."""
    fullname = f"auto_pts_project.pybluehost_iut.wid.{profile}"
    sys.modules.pop(fullname, None)
    return importlib.import_module(fullname)


def test_wid_modules_expose_function_handlers_without_autopts():
    """All four WID modules import cleanly and expose a callable handler."""
    for profile in PROFILES:
        mod = _import_fresh(profile)
        hdl = getattr(mod, HANDLER[profile])
        assert callable(hdl)


def test_wid_handler_signature_is_three_arg():
    import inspect
    for profile in PROFILES:
        mod = _import_fresh(profile)
        sig = inspect.signature(getattr(mod, HANDLER[profile]))
        assert list(sig.parameters) == ["wid", "description", "test_case_name"]


def test_wid_handler_raises_without_autopts(monkeypatch):
    """Without autoptsclient, dispatch must fail loudly (not silently no-op)."""
    monkeypatch.setitem(sys.modules, "autopts.wid", None)  # force ImportError
    for profile in PROFILES:
        mod = _import_fresh(profile)
        with pytest.raises(RuntimeError):
            getattr(mod, HANDLER[profile])(1, "desc", "TC")


def test_wid_search_path_prefers_local_then_upstream(monkeypatch):
    """generic_wid_hdl is called with [local_module, 'autopts.wid.<profile>']."""
    captured = {}

    def _fake_generic(wid, description, test_case_name, module_names):
        captured["module_names"] = module_names
        return "OK"

    autopts_wid = types.ModuleType("autopts.wid")
    autopts_wid.generic_wid_hdl = _fake_generic
    monkeypatch.setitem(sys.modules, "autopts.wid", autopts_wid)

    for profile in PROFILES:
        mod = _import_fresh(profile)
        result = getattr(mod, HANDLER[profile])(7, "d", "TC")
        assert result == "OK"
        assert captured["module_names"] == [mod.__name__, f"autopts.wid.{profile}"]


def test_gatt_hdl_wid_402_initiates_eatt_bearer(monkeypatch):
    """GATT/CL/GAR/BV-10 ("Read Multiple Variable Length over multiple bearers")
    aborts with MissingWIDError at WID 402 — upstream autopts/wid/gatt.py has no
    handler for it. The MMI asks the IUT to initiate an L2CAP Credit-Based
    Connection (the EATT bearer, fixed SPSM 0x0027); we drive it for real via
    btp.eatt_conn instead of mynewt's bare `return True` no-op, since our stack
    has a working EATT client (GATT EATT_CONNECT 0x1f)."""
    mod = _import_fresh("gatt")
    calls = {}

    # `from autopts.pybtp import btp` resolves via the parent package's cached
    # attribute, so patch the real module's attributes (a sys.modules swap is
    # never consulted here).
    from autopts.pybtp import btp
    monkeypatch.setattr(
        btp, "eatt_conn",
        lambda bd_addr, bd_addr_type, num=1: calls.update(
            bd_addr=bd_addr, bd_addr_type=bd_addr_type, num=num))

    assert mod.hdl_wid_402(types.SimpleNamespace(test_case_name="GATT/CL/GAR/BV-10-C")) is True
    # (None, None): the PTS address is resolved inside eatt_conn.
    assert calls == {"bd_addr": None, "bd_addr_type": None, "num": 1}


def test_gatt_hdl_wid_147_stores_the_read_multiple_values(monkeypatch):
    """Upstream hdl_wid_147 fires the two Read Multiple Variable Length
    commands and returns True without storing any verify value, so the case's
    WID 55 (verify_multiple_read_description) always answers No. Our override
    must fire both commands, then drain both bearer responses and store the
    value blob that WID 55 compares as a substring."""
    mod = _import_fresh("gatt")
    sent = []

    from autopts.pybtp import btp
    from autopts.pybtp.btp import gatt as btp_gatt

    monkeypatch.setattr(btp, "pts_addr_type_get", lambda: 0x00)
    monkeypatch.setattr(btp, "pts_addr_get", lambda: 0x01)
    monkeypatch.setattr(
        btp, "gattc_read_multiple_var",
        lambda at, ad, hdl1, hdl2: sent.append((at, ad, hdl1, hdl2)))
    stored = []
    monkeypatch.setattr(
        btp, "gattc_read_multiple_var_rsp",
        lambda *, store_rsp, store_val: stored.append((store_rsp, store_val)))

    class _Socket:
        def __init__(self):
            self.reads = 0

        def read(self):
            self.reads += 1

    iut = types.SimpleNamespace(btp_socket=_Socket())
    monkeypatch.setattr(btp_gatt, "get_iut", lambda: iut)

    description = ("Please send two Read Multiple Variable Length characteristic "
                   "requests using these handles: '031C'O '0195'O")
    params = types.SimpleNamespace(
        description=description, test_case_name="GATT/CL/GAR/BV-10-C")

    assert mod.hdl_wid_147(params) is True
    # Two BTP commands on the same handle pair — the ATT and EATT bearers.
    assert sent == [(0x00, 0x01, "031C", "0195"), (0x00, 0x01, "031C", "0195")]
    # First response's values are kept for WID 55; the second is drained.
    assert stored == [(False, True)]
    assert iut.btp_socket.reads == 1
