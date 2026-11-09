"""pybluehost_iut.{gap,gatt,l2cap} — profile modules expose set_pixits/test_cases.

autopts is not installed in CI, so we stub the slice of the autopts surface the
profile modules (and their PyBlueHostTestCase base) touch.
"""
from __future__ import annotations

import importlib
import sys
import types
from enum import IntFlag
from types import SimpleNamespace

import pytest


class _Perm(IntFlag):
    read = 0x01
    write = 0x02
    read_enc = 0x04
    write_enc = 0x08
    read_authn = 0x10
    write_authn = 0x20
    read_authz = 0x40
    write_authz = 0x80


class _Prop(IntFlag):
    broadcast = 0x01
    read = 0x02
    write_no_rsp = 0x04
    write_wo_resp = 0x04  # autopts names it write_wo_resp
    write = 0x08
    notify = 0x10
    indicate = 0x20
    auth_sign = 0x40
    ext_prop = 0x80

PROFILE_IXIT = {
    "gap": "IXIT_GAP",
    "gatt": "IXIT_GATT",
    "l2cap": "IXIT_L2CAP",
    "sm": "IXIT_SMP",
}
PROFILE_HANDLER = {"gap": "gap_wid_hdl", "gatt": "gatt_wid_hdl",
                   "l2cap": "l2cap_wid_hdl", "sm": "sm_wid_hdl"}
PROFILE_UPPER = {"gap": "GAP", "gatt": "GATT", "l2cap": "L2CAP", "sm": "SM"}


class _FakeFunc:
    """Stands in for autopts.ptsprojects.testcase.TestFunc."""

    def __init__(self, func, *args, **kwds):
        self.func = func
        self.args = args
        self.kwds = kwds


class _FakeFuncCleanUp(_FakeFunc):
    pass


class _FakeTestCaseLT1:
    def __init__(self, project_name, test_case_name, cmds=None,
                 ptsproject_name=None, generic_wid_hdl=None, **kw):
        self.project_name = project_name
        self.name = test_case_name
        self.cmds = list(cmds) if cmds else []
        self.ptsproject_name = ptsproject_name
        self.generic_wid_hdl = generic_wid_hdl


class _FakeGapLayer:
    def __init__(self):
        self.privacy = False

    def iut_addr_get_str(self):
        return "001A7DDA7111"

    def iut_addr_is_random(self):
        return False

    def iut_has_privacy(self):
        return self.privacy


class _FakeL2capModel:
    """Client-side L2CAP model (stack.l2cap) — just the knobs the per-case
    L2CAP registrations touch."""

    def __init__(self):
        self.initial_mtu = None

    def initial_mtu_set(self, mtu):
        self.initial_mtu = mtu


class _FakeStack:
    def __init__(self):
        self.gap = _FakeGapLayer()
        self.l2cap = _FakeL2capModel()

    def gap_init(self, *a, **k):
        pass

    def gatt_init(self, *a, **k):
        pass

    def l2cap_init(self, *a, **k):
        pass

    def cleanup(self):
        pass


class _FakePts:
    def __init__(self, cases):
        self.q_bd_addr = b"\x11\x22\x33\x44\x55\x66"
        self._cases = cases
        self.pixits = []
        self.updated = []

    def set_pixit(self, profile, name, value):
        self.pixits.append((profile, name, value))

    def update_pixit_param(self, profile, name, value):
        self.updated.append((profile, name, value))

    def get_test_case_list(self, profile):
        return list(self._cases)


@pytest.fixture
def autopts_stub(monkeypatch):
    stack_obj = _FakeStack()

    # autopts.ptsprojects.testcase
    testcase_mod = types.ModuleType("autopts.ptsprojects.testcase")
    testcase_mod.TestCaseLT1 = _FakeTestCaseLT1
    testcase_mod.TestFunc = _FakeFunc
    testcase_mod.TestFuncCleanUp = _FakeFuncCleanUp

    # autopts.ptsprojects.stack
    stack_mod = types.ModuleType("autopts.ptsprojects.stack")
    stack_mod.get_stack = lambda: stack_obj

    # autopts.client
    client_mod = types.ModuleType("autopts.client")
    client_mod.get_unique_name = lambda pts: "PyBlueHost-IUT"

    # autopts.pybtp.btp — helpers only need to exist (TestFunc wraps, never calls)
    btp_mod = types.ModuleType("autopts.pybtp.btp")
    for fn in ("core_reg_svc_gap", "core_reg_svc_gatt", "core_reg_svc_l2cap",
               "gap_reset", "gap_read_controller_info", "gap_set_bondable_on",
               "gap_set_mitm_on", "gap_set_io_capability", "gap_unpair", "set_pts_addr",
               "l2cap_le_listen", "gap_enable_secure_connections_only",
               "gap_set_min_enc_key_size", "gap_set_privacy_on",
               "gatts_add_svc", "gatts_add_char", "gatts_set_val",
               "gatts_add_desc", "gatts_add_inc_svc", "gatts_set_enc_key_size",
               "gatts_start_server"):
        setattr(btp_mod, fn, lambda *a, **k: None)

    # SET_PRIVACY has to be visible to the client model: the GAP module publishes
    # TSPX_iut_privacy_enabled from stack.gap.iut_has_privacy() *after* the
    # per-case pre-conditions, so the fake must flip the bit like PTS does.
    btp_mod.gap_set_privacy_on = lambda *a, **k: setattr(
        stack_obj.gap, "privacy", True)

    # autopts.pybtp.btp.gap — EAD key constants the GAP set_pixits pushes
    # (values mirror upstream autopts/pybtp/btp/gap.py).
    btp_gap_mod = types.ModuleType("autopts.pybtp.btp.gap")
    btp_gap_mod.EAD_ENCRYPTION_KEY = "00112233445566778899AABBCCDDEEFF"
    btp_gap_mod.EAD_INITIALIZATION_VECTOR = "0001020304050607"
    btp_mod.gap = btp_gap_mod

    # autopts.pybtp.types
    types_mod = types.ModuleType("autopts.pybtp.types")
    types_mod.Addr = SimpleNamespace(le_public=0)
    types_mod.IOCap = SimpleNamespace(display_only=0, no_input_output=3)
    types_mod.Perm = _Perm
    types_mod.Prop = _Prop
    types_mod.AdType = SimpleNamespace(flags=1, name_full=9)
    types_mod.AdFlags = SimpleNamespace(br_edr_not_supp=0x04)
    types_mod.UriScheme = SimpleNamespace(https=b"\x17")
    types_mod.UUID = SimpleNamespace(
        VND16_1=0xAA50, VND16_2=0xAA52, VND16_3=0xAA53, VND16_4=0xAA54, VND16_5=0xAA55)
    # The GATT init_server sequence references the full reference-db UUID set;
    # values are arbitrary — they're wrapped in TestFunc and never called.
    types_mod.UUID = SimpleNamespace(
        SVND16_0=0xA000, SVND16_1=0xA001,
        VND16_0=0xAA00, VND16_1=0xAA50, VND16_2=0xAA52, VND16_3=0xAA53,
        VND16_4=0xAA54, VND16_5=0xAA55, VND16_6=0xAA56, VND16_7=0xAA57,
        VND16_8=0xAA58, VND16_9=0xAA59, VND16_10=0xAA60,
        VND128_1=0xAA99, CCC=0x2902, CEP=0x2900)
    types_mod.L2CAPConnectionResponse = SimpleNamespace(
        success=0, insufficient_authentication=1, insufficient_authorization=2,
        insufficient_encryption_key_size=3, insufficient_encryption=4,
        insufficient_secure_authentication=5)

    # autopts.wid (so wid adapters bind a generic_wid_hdl)
    wid_mod = types.ModuleType("autopts.wid")
    wid_mod.generic_wid_hdl = lambda wid, d, t, mods: None

    for name, mod in {
        "autopts": types.ModuleType("autopts"),
        "autopts.client": client_mod,
        "autopts.ptsprojects": types.ModuleType("autopts.ptsprojects"),
        "autopts.ptsprojects.testcase": testcase_mod,
        "autopts.ptsprojects.stack": stack_mod,
        "autopts.pybtp": types.ModuleType("autopts.pybtp"),
        "autopts.pybtp.btp": btp_mod,
        "autopts.pybtp.btp.gap": btp_gap_mod,
        "autopts.pybtp.types": types_mod,
        "autopts.wid": wid_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)

    # A fake running IUT for PyBlueHostTestCase's start/stop insertion.
    from auto_pts_project.pybluehost_iut import iutctl

    class _FakeIut:
        def start(self, tc):
            pass

        def wait_iut_ready_event(self):
            pass

        def stop(self):
            pass

    fake_iut = _FakeIut()
    monkeypatch.setattr(iutctl, "IUT", fake_iut)

    # Drop cached profile modules so they re-import against the stub.
    for name in list(sys.modules):
        if name.startswith("auto_pts_project.pybluehost_iut.") and not name.endswith("iutctl"):
            monkeypatch.delitem(sys.modules, name, raising=False)

    return SimpleNamespace(stack=stack_obj, iut=fake_iut)


@pytest.mark.parametrize("profile", ["gap", "gatt", "l2cap", "sm"])
def test_profile_module_exposes_hooks(autopts_stub, profile):
    mod = importlib.import_module(f"auto_pts_project.pybluehost_iut.{profile}")
    assert callable(mod.set_pixits)
    assert callable(mod.test_cases)


@pytest.mark.parametrize("profile", ["gap", "gatt", "l2cap", "sm"])
def test_set_pixits_pushes_ixit(autopts_stub, profile):
    from auto_pts_project.pybluehost_iut import ixit
    mod = importlib.import_module(f"auto_pts_project.pybluehost_iut.{profile}")
    pts = _FakePts([])
    mod.set_pixits([pts])

    expected = getattr(ixit, PROFILE_IXIT[profile])
    upper = PROFILE_UPPER[profile]
    for name, value in expected.items():
        assert (upper, name, value) in pts.pixits


@pytest.mark.parametrize("profile", ["gap", "gatt", "l2cap", "sm"])
def test_test_cases_builds_pybluehost_testcases(autopts_stub, profile):
    mod = importlib.import_module(f"auto_pts_project.pybluehost_iut.{profile}")
    cases = [f"{PROFILE_UPPER[profile]}/FOO/BV-01-C", f"{PROFILE_UPPER[profile]}/FOO/BV-02-C"]
    pts = _FakePts(cases)

    tc_list = mod.test_cases([pts])

    assert len(tc_list) == len(cases)
    assert [tc.name for tc in tc_list] == cases
    for tc in tc_list:
        assert isinstance(tc, _FakeTestCaseLT1)
        assert tc.ptsproject_name == "pybluehost_iut"
        # First cmd starts the IUT, second waits for READY; cleanups appended last.
        assert tc.cmds[0].func == autopts_stub.iut.start
        assert tc.cmds[1].func == autopts_stub.iut.wait_iut_ready_event
        assert isinstance(tc.cmds[-1], _FakeFuncCleanUp)
        assert tc.cmds[-1].func == autopts_stub.iut.stop
        # generic_wid_hdl routed to the profile's adapter
        wid_mod = importlib.import_module(f"auto_pts_project.pybluehost_iut.wid.{profile}")
        assert tc.generic_wid_hdl is getattr(wid_mod, PROFILE_HANDLER[profile])


def test_l2cap_security_responder_listener_levels(autopts_stub):
    """Each security-responder case must register a listener demanding the exact
    level the TS expects for it (L2CAP.TS Tables 4.57-4.65).

    Getting this wrong is invisible on the wire until PTS times out: we answer a
    *different* refusal code than the one the case asserts. LE/CFC/BV-25 and its
    ECFC twin BV-32 are the Insufficient *Encryption* pair (0x0008), not the
    authentication pair (0x0005) — BV-25 was mapped to authen and ECFC/BV-32 had
    no mapping at all, so both ran a listener PTS could never be satisfied by.
    """
    from autopts.pybtp import btp, types

    mod = importlib.import_module("auto_pts_project.pybluehost_iut.l2cap")
    R = types.L2CAPConnectionResponse
    expected = {
        "L2CAP/LE/CFC/BV-11-C": R.insufficient_authentication,
        "L2CAP/LE/CFC/BV-13-C": R.insufficient_authorization,
        "L2CAP/LE/CFC/BV-15-C": R.insufficient_encryption_key_size,
        "L2CAP/LE/CFC/BV-25-C": R.insufficient_encryption,
        "L2CAP/ECFC/BV-11-C": R.insufficient_authentication,
        "L2CAP/ECFC/BV-13-C": R.insufficient_authorization,
        "L2CAP/ECFC/BV-15-C": R.insufficient_encryption_key_size,
        "L2CAP/ECFC/BV-32-C": R.insufficient_encryption,
    }
    pts = _FakePts(list(expected))
    by_name = {tc.name: tc for tc in mod.test_cases([pts])}

    def listen_level(tc):
        for cmd in tc.cmds:
            if getattr(cmd, "func", None) is btp.l2cap_le_listen:
                return cmd.args[-1]
        return None

    for name, level in expected.items():
        assert listen_level(by_name[name]) == level, (
            f"{name}: listener level {listen_level(by_name[name])!r} != expected {level!r}"
        )


def test_l2cap_ixit_defines_the_ecfc_mtu_mps_ranges(autopts_stub):
    """The ECFC renegotiation cases escape via a L2CAP.TS step-1 short circuit:
    4.9.1.17/4.9.1.18 end with a Pass verdict when the supported MTU/MPS range
    collapses to one value. The per-case overrides that collapse it call
    ``update_pixit``, which *skips silently* when the PIXIT is undefined — so
    the ranges must exist in the IXIT set or the override quietly does nothing
    and the case times out waiting for a renegotiation we never send (there is
    no BTP command that carries an MPS, so BV-24 has no other route at all)."""
    from auto_pts_project.pybluehost_iut.ixit import IXIT_L2CAP

    for name in ("TSPX_l2ca_cbmps_min", "TSPX_l2ca_cbmps_max",
                 "TSPX_l2ca_cbmtu_min", "TSPX_l2ca_cbmtu_max"):
        assert name in IXIT_L2CAP, f"{name} missing — per-case overrides would no-op"


def test_gap_publishes_the_periodic_advertising_data_pixit(autopts_stub):
    """GAP/PADV/PAM/BV-01 and PASM/BV-01 are decided entirely by this PIXIT:
    the Lower Tester compares the periodic advertising it receives from the IUT
    against TSPX_periodic_advertising_data.  The workspace default is the PTS
    sample device's own data, so leaving it unpushed makes the two cases
    unwinnable no matter what the IUT broadcasts.

    The value has to be the exact AD structure WID 300 pushes to us — the
    one-octet length, then the AD type, then the payload — which is also what
    the zephyr reference publishes.
    """
    from autopts.pybtp import btp

    mod = importlib.import_module("auto_pts_project.pybluehost_iut.gap")
    pts = _FakePts(["GAP/PADV/PAM/BV-01-C"])
    (tc,) = mod.test_cases([pts])

    for cmd in tc.cmds:
        if getattr(cmd, "func", None) is not None and cmd.func.__name__ == "<lambda>":
            cmd.func()

    pushed = [v for _p, name, v in pts.updated
              if name == "TSPX_periodic_advertising_data"]
    assert pushed == ["0c08504144565f546573746572"], (
        "missing or wrong TSPX_periodic_advertising_data — PAM/PASM compare "
        "the on-air train against it"
    )


def test_gap_every_case_drops_the_previous_pts_bond(autopts_stub):
    """Every GAP case — including the "previous bond exists" pair — must start by
    unpairing the PTS address, exactly like the bluez reference IUT.

    GAP/SEC/AUT/BV-13-C (Central) and BV-14-C (Peripheral) look like exceptions:
    GAP.TS gives them the Initial Condition "Previous bond exists between the IUT
    and the Lower Tester with unauthenticated pairing" and both procedures open
    with "the IUT initiates and completes the encryption of the link", so an
    unpair appears to delete the very thing the case is built on.

    It does not help to special-case them.  The Lower Tester never creates that
    bond — PTS deletes its own host LTK at case start and BV-13's MMI script has
    a single entry (WID 78, "send an LE connect request").  The moment the IUT
    encrypts with the pre-existing LTK, PTS's controller raises
    HCI_LE_LONG_TERM_KEY_REQUESTED_EVENT and PTS answers
    HCI_LONG_TERM_KEY_REQUESTED_NEGATIVE_REPLY -> "Security Failed. result = 8"
    -> INDCSV.  That reproduces with the special case in place, and the bluez
    reference registers both with the plain pre-conditions; auto-pts lists them
    as errata ES-28650.  So the guard here is parity with the reference: nobody
    should "fix" these two by dropping the unpair.
    """
    from autopts.pybtp import btp

    mod = importlib.import_module("auto_pts_project.pybluehost_iut.gap")
    cases = ["GAP/SEC/AUT/BV-12-C", "GAP/SEC/AUT/BV-13-C",
             "GAP/SEC/AUT/BV-14-C"]
    by_name = {tc.name: tc for tc in mod.test_cases([_FakePts(cases)])}

    def unpairs(tc):
        return any(getattr(c, "func", None) is btp.gap_unpair for c in tc.cmds)

    for name in cases:
        assert unpairs(by_name[name]), f"{name} must drop the stale PTS bond"

    # And the three really are configured identically — no hidden per-case delta.
    counts = {len(by_name[name].cmds) for name in cases}
    assert len(counts) == 1


def test_gap_invalid_key_size_cases_configure_the_key_size_floor(autopts_stub):
    """GAP.TS 4.5.4 (Table 4.19): the negative key-size cases are decided by the
    IUT's *configured* security level — with a 16-octet floor it must answer any
    Maximum_Encryption_Key_Size in [7,15] with Pairing Failed 0x06. auto-pts
    exposes no other lever for that level, so the per-case pre-condition pushes
    it. BI-10 (Central, mode 1 level 4) was missing from the mapping while its
    table-mates BI-22/BI-23 were present."""
    from autopts.pybtp import btp

    mod = importlib.import_module("auto_pts_project.pybluehost_iut.gap")
    cases = [
        "GAP/SEC/SEM/BI-09-C", "GAP/SEC/SEM/BI-10-C", "GAP/SEC/SEM/BI-20-C",
        "GAP/SEC/SEM/BI-21-C", "GAP/SEC/SEM/BI-22-C", "GAP/SEC/SEM/BI-23-C",
    ]
    by_name = {tc.name: tc for tc in mod.test_cases([_FakePts(cases)])}

    for name in cases:
        calls = [
            cmd.args for cmd in by_name[name].cmds
            if getattr(cmd, "func", None) is btp.gap_set_min_enc_key_size
        ]
        assert calls == [(16,)], f"{name} must set a 16-octet key-size floor"


def test_gas_bv_01_registers_the_post_wid_96_database_change(autopts_stub):
    """GATT/SR/GAS/BV-01-C drives the Service Changed indication with a WID 96
    db change after the Lower Tester disconnects (upstream zephyr post_wid=96).
    Without it the db never changes and no SC indication is ever sent, so the
    case stalls/FAILs."""
    mod = importlib.import_module("auto_pts_project.pybluehost_iut.gatt")
    (tc,) = mod.test_cases([_FakePts(["GATT/SR/GAS/BV-01-C"])])

    post96 = [c for c in tc.cmds if getattr(c, "kwds", {}).get("post_wid") == 96]
    assert post96, "BV-01 must register a post_wid=96 TestFunc"
    assert post96[0].func.__name__ == "_update_service_gas_bv_01"

    # A non-BV-01 SR case must NOT get the special handling.
    (plain,) = mod.test_cases([_FakePts(["GATT/SR/GAR/BV-01-C"])])
    assert not [c for c in plain.cmds
                if getattr(c, "kwds", {}).get("post_wid") == 96]


def test_gap_cpu_bv_05_pushes_invalid_connection_parameter_pixits(autopts_stub):
    """GAP/CONN/CPUP/BV-05-C: the Lower Tester builds its Connection Parameter
    Update Request from the four TSPX_iut_invalid_* PIXITs and PASSes only if
    the IUT answers result=0x0001 ("request rejected") and keeps using the
    default parameters (GAP.TS 4.5.2).  The workspace defaults
    (0008/00AA/0000/0800) are Core-valid, so our responder — which mirrors
    zephyr's bt_le_conn_params_valid — accepts them and the case FAILs.

    Fix follows the TSPX_advertising_data precedent: push PIXIT values that
    violate Core ranges (each field trips exactly one check, so it does not
    matter whether the LT combines them into one request or sends one request
    per field), and assert against the responder's actual rule so the PIXIT
    push and the stack cannot drift apart.  BV-04 (valid parameters) must stay
    on the plain flow — its request is Core-valid by construction and must be
    accepted."""
    from pybluehost.l2cap.manager import _le_cpu_params_valid

    mod = importlib.import_module("auto_pts_project.pybluehost_iut.gap")
    pts = _FakePts(["GAP/CONN/CPUP/BV-04-C", "GAP/CONN/CPUP/BV-05-C"])
    by_name = {tc.name: tc for tc in mod.test_cases([pts])}

    expected = {
        "TSPX_iut_invalid_connection_interval_min": "0004",
        "TSPX_iut_invalid_connection_interval_max": "0005",
        "TSPX_iut_invalid_connection_latency": "01F5",
        "TSPX_iut_invalid_conn_update_supervision_timeout": "0005",
    }
    for cmd in by_name["GAP/CONN/CPUP/BV-05-C"].cmds:
        if getattr(cmd, "func", None) is not None and cmd.func.__name__ == "<lambda>":
            cmd.func()
    pushed = {
        name: value
        for _p, name, value in pts.updated
        if name in expected
    }
    assert pushed == expected, "BV-05 must publish the invalid-parameter PIXITs"

    # Every pushed field must actually trip the responder's rule when it
    # replaces that field of an otherwise Core-valid request.
    valid = (0x0008, 0x00AA, 0x0000, 0x0800)
    assert _le_cpu_params_valid(*valid), "BV-04 baseline must stay acceptable"
    assert not _le_cpu_params_valid(0x0004, valid[1], valid[2], valid[3])
    assert not _le_cpu_params_valid(valid[0], 0x0005, valid[2], valid[3])
    assert not _le_cpu_params_valid(valid[0], valid[1], 0x01F5, valid[3])
    assert not _le_cpu_params_valid(valid[0], valid[1], valid[2], 0x0005)

    # BV-04 (valid parameters) stays on the plain pre-conditions — no PIXIT
    # push, so the LT keeps sending Core-valid parameters there.
    bv05 = by_name["GAP/CONN/CPUP/BV-05-C"]
    bv04 = by_name["GAP/CONN/CPUP/BV-04-C"]
    assert len(bv05.cmds) == len(bv04.cmds) + 4


def test_gap_acep_rpa_cases_enable_privacy_before_wid_400(autopts_stub):
    """GAP/CONN/ACEP BV-03/04 advertise with (and expect the IUT to initiate
    from) resolvable private addresses. Privacy must be ON before WID 400's
    filter-list connect so the auto-connection flow programs the resolving
    list and initiates from an RPA. The public-identity pair (BV-01/02) must
    stay on the plain flow."""
    from autopts.pybtp import btp

    mod = importlib.import_module("auto_pts_project.pybluehost_iut.gap")
    cases = [
        "GAP/CONN/ACEP/BV-01-C", "GAP/CONN/ACEP/BV-02-C",
        "GAP/CONN/ACEP/BV-03-C", "GAP/CONN/ACEP/BV-04-C",
    ]
    by_name = {tc.name: tc for tc in mod.test_cases([_FakePts(cases)])}

    def privacy_on(tc):
        return any(getattr(c, "func", None) is btp.gap_set_privacy_on
                   for c in tc.cmds)

    assert privacy_on(by_name["GAP/CONN/ACEP/BV-03-C"])
    assert privacy_on(by_name["GAP/CONN/ACEP/BV-04-C"])
    assert not privacy_on(by_name["GAP/CONN/ACEP/BV-01-C"])
    assert not privacy_on(by_name["GAP/CONN/ACEP/BV-02-C"])


def test_gap_rpa_observation_cases_scan_with_privacy_on(autopts_stub):
    """The RPA-observation cluster (DISC/RPA/BV-01, OBSV/BV-06, PRIV/CONN/
    BV-10) has the IUT observe/resolve the peer's RPA. The scan must go out
    with a random own address (privacy ON) — the untried variable after the
    resolving list was proven programmed: the earlier runs scanned from the
    public address and the controller never resolved the RPA into the report.
    The public-address sibling OBSV/BV-05 must stay on the plain flow."""
    from autopts.pybtp import btp

    mod = importlib.import_module("auto_pts_project.pybluehost_iut.gap")
    cases = [
        "GAP/BROB/OBSV/BV-05-C", "GAP/BROB/OBSV/BV-06-C",
        "GAP/DISC/RPA/BV-01-C", "GAP/PRIV/CONN/BV-10-C",
    ]
    by_name = {tc.name: tc for tc in mod.test_cases([_FakePts(cases)])}

    def privacy_on(tc):
        return any(getattr(c, "func", None) is btp.gap_set_privacy_on
                   for c in tc.cmds)

    assert privacy_on(by_name["GAP/DISC/RPA/BV-01-C"])
    assert privacy_on(by_name["GAP/BROB/OBSV/BV-06-C"])
    assert privacy_on(by_name["GAP/PRIV/CONN/BV-10-C"])
    assert not privacy_on(by_name["GAP/BROB/OBSV/BV-05-C"])


def test_gap_central_privacy_case_enables_privacy_before_connect(autopts_stub):
    """GAP/PRIV/CONN/BV-11 requires an RPA in InitA and controller resolution
    of the LT's RPA. Its per-case setup must enable privacy just like BV-10;
    otherwise CONNECT uses the default public address and the LT ignores it."""
    from autopts.pybtp import btp

    mod = importlib.import_module("auto_pts_project.pybluehost_iut.gap")
    cases = ["GAP/PRIV/CONN/BV-10-C", "GAP/PRIV/CONN/BV-11-C"]
    by_name = {tc.name: tc for tc in mod.test_cases([_FakePts(cases)])}

    for name in cases:
        assert any(
            getattr(c, "func", None) is btp.gap_set_privacy_on
            for c in by_name[name].cmds
        ), name


def test_gap_publishes_the_privacy_enabled_pixit_after_per_case_setup(autopts_stub):
    """PTS decides whether to set up its own controller for address resolution
    from ``TSPX_iut_privacy_enabled`` (bluez publishes it for exactly that
    reason). Publishing it from ``pre_conditions`` would evaluate before the
    per-case SET_PRIVACY and always report FALSE, so the Lower Tester scans
    whitelist-only and never sees the IUT's RPA — GAP/PRIV/CONN/BV-10-C ran
    its full 300 s guard with zero advertising reports. The push therefore has
    to run LAST, after any per-case pre-conditions.
    """
    from autopts.ptsprojects.stack import get_stack

    mod = importlib.import_module("auto_pts_project.pybluehost_iut.gap")
    cases = ["GAP/PRIV/CONN/BV-10-C", "GAP/BROB/OBSV/BV-05-C"]
    pts = _FakePts(cases)
    by_name = {tc.name: tc for tc in mod.test_cases([pts])}

    def run_all(tc):
        get_stack().gap.privacy = False
        pts.updated.clear()
        for cmd in tc.cmds:
            if getattr(cmd, "func", None) is not None \
                    and cmd.func.__name__ == "<lambda>":
                cmd.func()

    # Privacy case: SET_PRIVACY has run before the PIXIT is published.
    run_all(by_name["GAP/PRIV/CONN/BV-10-C"])
    assert pts.updated[-1][1] == "TSPX_iut_privacy_enabled"
    assert pts.updated[-1][2] == "TRUE", (
        "TSPX_iut_privacy_enabled must be published after SET_PRIVACY, or the "
        "LT never configures address resolution for the IUT's RPA"
    )

    run_all(by_name["GAP/BROB/OBSV/BV-05-C"])
    assert pts.updated[-1][1] == "TSPX_iut_privacy_enabled"
    assert pts.updated[-1][2] == "FALSE"


def test_gap_publishes_the_device_name_for_random_address_advertising(autopts_stub):
    """When the IUT advertises from a rotating private address the LT cannot
    track it by address; it matches the advertising data name against
    TSPX_iut_device_name_in_adv_packet_for_random_address. bluez publishes the
    IUT's name here — leaving the workspace default made PTS look for a stale
    name and discard our reports in the RPA phases."""
    mod = importlib.import_module("auto_pts_project.pybluehost_iut.gap")
    pts = _FakePts(["GAP/PRIV/CONN/BV-10-C"])
    (tc,) = mod.test_cases([pts])

    for cmd in tc.cmds:
        if getattr(cmd, "func", None) is not None \
                and cmd.func.__name__ == "<lambda>":
            cmd.func()

    pushed = [v for _p, name, v in pts.updated
              if name == "TSPX_iut_device_name_in_adv_packet_for_random_address"]
    assert pushed == ["PyBlueHost-IUT"]


def test_l2cap_kframe_cases_advertise_mtu_512(autopts_stub):
    """L2CAP.TS 4.9.3.15 (Table 4.69/4.71: BV-32 legacy, BV-80 ECFC) replays
    K-frame rounds with SDU Length up to MPS×2+1 and MTU, and passes only if
    the IUT never disconnects. The rounds are only all-legal when the IUT's
    advertised MTU ≥ MPS−1 (ALT 4A); with the model default 120 < 247−1 the LT
    takes ALT 4B and aborts right after accepting the channel."""
    from autopts.ptsprojects.stack import get_stack

    mod = importlib.import_module("auto_pts_project.pybluehost_iut.l2cap")
    names = ["L2CAP/ECFC/BV-80-C", "L2CAP/LE/CFC/BV-32-C"]
    pts = _FakePts(names)
    by_name = {tc.name: tc for tc in mod.test_cases([pts])}

    for name in names:
        stack = get_stack()
        stack.l2cap.initial_mtu = None
        mtu_raised = cbmtu_pushed = False
        for cmd in by_name[name].cmds:
            if getattr(cmd, "func", None) is not None and cmd.func.__name__ == "<lambda>":
                cmd.func()
                mtu_raised = mtu_raised or stack.l2cap.initial_mtu == 512
        cbmtu_pushed = any(
            v == "0200" for _p, n, v in pts.updated if n == "TSPX_l2ca_cbmtu_max")
        assert mtu_raised, f"{name}: no pre-condition raises the advertised MTU to 512"
        # The request MTU must stay inside the workspace's declared IUT range
        # or the LT aborts the 512 request itself (the BV-22 range check).
        assert cbmtu_pushed, f"{name}: cbmtu_max not aligned with the 512 request"


def test_l2cap_bv22_aligns_cbmtu_max_with_the_advertised_mtu(autopts_stub):
    """BV-22's LT aborts when the IUT's advertised receive MTU (512, inbound
    accept hardcode) exceeds TSPX_l2ca_cbmtu_max. Pushing the workspace value
    to 0x0200 (=512) makes TS 4.9.1.15 step 1 short-circuit to Pass
    (current MTU == max supported MTU) — the PIXIT must therefore be defined
    in IXIT_L2CAP, since update_pixit skips undefined names silently."""
    from auto_pts_project.pybluehost_iut.ixit import IXIT_L2CAP
    from autopts.pybtp import btp  # noqa: F401  (imports the autopts stub)

    assert "TSPX_l2ca_cbmtu_max" in IXIT_L2CAP

    mod = importlib.import_module("auto_pts_project.pybluehost_iut.l2cap")
    # BV-04 shares the gate: its LT reads our 0x18 MTU against the same PIXIT
    # and aborts when 512 exceeds the declared max (identical on-air shape).
    pts = _FakePts(["L2CAP/ECFC/BV-22-C", "L2CAP/COS/ECFC/BV-04-C"])
    for tc in mod.test_cases([pts]):
        for cmd in tc.cmds:
            if getattr(cmd, "func", None) is not None and cmd.func.__name__ == "<lambda>":
                cmd.func()
    pushed = [v for _p, name, v in pts.updated if name == "TSPX_l2ca_cbmtu_max"]
    assert pushed == ["0200", "0200"], f"expected one 0200 push per case, got {pushed}"


def test_l2cap_bi29_raises_the_time_guard_for_255_rounds(autopts_stub):
    """COS/CED/BI-29 runs 255 connect rounds answered with wrong / duplicate
    identifiers; every round waits for our §4.1 RTX retransmission. The
    default time guard cuts the case off mid-way (zephyr parity: 360000 ms)."""
    mod = importlib.import_module("auto_pts_project.pybluehost_iut.l2cap")
    pts = _FakePts(["L2CAP/COS/CED/BI-29-C"])
    (tc,) = mod.test_cases([pts])
    for cmd in tc.cmds:
        if getattr(cmd, "func", None) is not None and cmd.func.__name__ == "<lambda>":
            cmd.func()
    guard = [v for _p, name, v in pts.pixits if name == "TSPX_time_guard"]
    assert guard == ["360000"], f"expected one 360000 time guard, got {guard}"


def test_gap_set_pixits_shares_ead_keys_via_ixit(autopts_stub):
    """EAD cases (GAP/ADV "Encrypted Data", GAP/SCN/BV-01): the Lower Tester
    encrypts/decrypts the Encrypted Advertising Data with the workspace
    key/IV, and auto-pts's `_setup_ead_key_material` pushes the very same
    hardcoded constants to the IUT via SET_EAD_KEY_MATERIAL (0x31). Zephyr
    (ptsprojects/zephyr/gap.py) selects `keys_shared_via_ixit` so neither
    side has to round-trip the key material over GATT; we must push the same
    three PIXITs or the LT encrypts with values we never see."""
    mod = importlib.import_module("auto_pts_project.pybluehost_iut.gap")
    pts = _FakePts([])
    mod.set_pixits([pts])

    pushed = {name: value for _prof, name, value in pts.pixits}
    assert pushed.get("TSPX_ead_keys_sharing_method") == "keys_shared_via_ixit"
    assert pushed.get("TSPX_encrypted_data_key") == "00112233445566778899AABBCCDDEEFF"
    assert pushed.get("TSPX_initialization_vector") == "0001020304050607"
    # Keep one source of truth with upstream when it is importable: if the
    # pybtp constants ever move, this test breaks loudly instead of the case
    # failing on air with a MIC mismatch.
    try:
        from autopts.pybtp.btp.gap import (
            EAD_INITIALIZATION_VECTOR as upstream_iv,
            EAD_ENCRYPTION_KEY as upstream_key,
        )
    except ImportError:
        return
    assert pushed.get("TSPX_encrypted_data_key") == upstream_key
    assert pushed.get("TSPX_initialization_vector") == upstream_iv


def test_gap_sc_only_cases_enable_mitm_only_for_level_3_and_4(autopts_stub):
    """GAP.TS Tables 4.17/4.18: the SC-only SEM cases come in level pairs.

    BV-41/43 are mode 1 **level 2** (unauthenticated — MITM must stay off,
    upstream hdl_wid_224 issues gap_set_mitm_off), while BV-42/44 are level 3
    and BV-28/29/64/67 level 4 (authenticated; WID 226 does NOT set MITM, so
    those two relied on the removed SC-only force and regressed to INDCSV on
    the first hardware pass — caught here instead). The initiator takes MITM from the
    config, so the authenticated SC-only cases must enable it per case; a
    blanket "SC-only implies MITM" in the SMP layer flips the level-2 twins
    to FAIL (PTS aborts right after the public key, 2026-11-01 capture).
    """
    from autopts.pybtp import btp

    mod = importlib.import_module("auto_pts_project.pybluehost_iut.gap")
    names = ["GAP/SEC/SEM/BV-28-C", "GAP/SEC/SEM/BV-29-C",
             "GAP/SEC/SEM/BV-41-C", "GAP/SEC/SEM/BV-42-C",
             "GAP/SEC/SEM/BV-43-C", "GAP/SEC/SEM/BV-44-C",
             "GAP/SEC/SEM/BV-64-C", "GAP/SEC/SEM/BV-67-C"]
    by_name = {tc.name: tc for tc in mod.test_cases([_FakePts(names)])}

    def mitm_on(tc):
        return any(getattr(c, "func", None) is btp.gap_set_mitm_on for c in tc.cmds)

    for name in ("GAP/SEC/SEM/BV-28-C", "GAP/SEC/SEM/BV-29-C",
                 "GAP/SEC/SEM/BV-42-C", "GAP/SEC/SEM/BV-44-C",
                 "GAP/SEC/SEM/BV-64-C", "GAP/SEC/SEM/BV-67-C"):
        assert mitm_on(by_name[name]), f"{name} is authenticated: MITM on"
    for name in ("GAP/SEC/SEM/BV-41-C", "GAP/SEC/SEM/BV-43-C"):
        assert not mitm_on(by_name[name]), f"{name} is level 2: no MITM"


def test_l2cap_ixit_pins_the_concurrent_credit_based_connection_count(autopts_stub):
    """ECFC/BV-38 + LE/CFC/BV-29 repeat connect/disconnect
    TSPX_l2ca_num_concurrent_credit_based_connections times and check that
    every Source CID is fresh. Left at the workspace default the LT script
    overruns its own buffer and the case FAILs mid-way; zephyr and mynewt both
    pin this PIXIT to 2."""
    from auto_pts_project.pybluehost_iut.ixit import IXIT_L2CAP

    assert IXIT_L2CAP.get("TSPX_l2ca_num_concurrent_credit_based_connections") == "2"


def test_sm_mitm_is_per_case_not_global(autopts_stub):
    """SM/PER/PKE/BV-05 needs MITM=1 in the IUT's Pairing *Response* while its
    twins BV-06 and KDU/BV-08 must mirror the LT's 0. The responder honors the
    config, so MITM can no longer be a shared pre-condition: CEN cases (the
    initiator needs it for PKE/NC) and BV-05 alone keep it."""
    from autopts.pybtp import btp

    mod = importlib.import_module("auto_pts_project.pybluehost_iut.sm")
    names = ["SM/CEN/PKE/BV-01-C", "SM/CEN/JW/BV-01-C",
             "SM/PER/PKE/BV-05-C", "SM/PER/PKE/BV-06-C",
             "SM/PER/KDU/BV-08-C", "SM/PER/JW/BV-02-C"]
    by_name = {tc.name: tc for tc in mod.test_cases([_FakePts(names)])}

    def mitm_on(tc):
        return any(getattr(c, "func", None) is btp.gap_set_mitm_on for c in tc.cmds)

    for name in ("SM/CEN/PKE/BV-01-C", "SM/CEN/JW/BV-01-C", "SM/PER/PKE/BV-05-C"):
        assert mitm_on(by_name[name]), f"{name}: MITM required"
    for name in ("SM/PER/PKE/BV-06-C", "SM/PER/KDU/BV-08-C", "SM/PER/JW/BV-02-C"):
        assert not mitm_on(by_name[name]), f"{name}: must mirror the peer, no forced MITM"
