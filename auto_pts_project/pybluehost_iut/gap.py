"""GAP profile wiring for autoptsclient (auto-pts master contract).

Exposes the two hooks ``setup_project_pixits``/``setup_test_cases`` call via
``getattr(autoprojects, 'gap')``:

- ``set_pixits(ptses)`` — push our IXIT_GAP values into the PTS workspace.
- ``test_cases(ptses)`` — build one PyBlueHostTestCase per enabled GAP case.

autopts helpers are imported inside ``test_cases`` so the module stays cheap to
load; the PTS workspace supplies PICS (our old ``pics.py`` is not used here).
"""
from __future__ import annotations

import logging

from auto_pts_project.pybluehost_iut.ixit import IXIT_GAP, apply_pixits, update_pixit
from auto_pts_project.pybluehost_iut.testcase import PyBlueHostTestCase
from auto_pts_project.pybluehost_iut.wid.gap import gap_wid_hdl
from pybluehost.pts.actions import PTS_IUT_IRK

logger = logging.getLogger(__name__)

# Device Identity used for resolvable private addresses. PTS resolves the RPAs
# the IUT advertises (and mints its directed TargetA) with the IRK from this
# PIXIT, so both sides must agree; the value comes from
# `pybluehost.pts.actions.PTS_IUT_IRK` (sixteen equal bytes — non-zero so the
# Intel controller actually uses it for resolving-list operations, and
# byte-order-agnostic under any hex parse PTS applies).
IUT_IRK_HEX = PTS_IUT_IRK.hex().upper()


def set_pixits(ptses) -> None:
    """Setup GAP PIXITs for the workspace. ptses -- list of PyPTS instances."""
    apply_pixits(ptses[0], "GAP", IXIT_GAP)
    try:
        ptses[0].set_pixit(
            "GAP",
            "TSPX_iut_device_IRK_for_resolvable_privacy_address_generation_procedure",
            IUT_IRK_HEX,
        )
        logger.info("GAP PIXIT device IRK pushed as %s", IUT_IRK_HEX)
    except Exception:
        # not present in every PTS build — but a silent pass hid a rejected
        # value for a whole debugging session, so say so loudly.
        logger.warning(
            "GAP PIXIT device IRK could not be pushed (%s); PTS keeps its "
            "workspace value and will not resolve our RPA",
            IUT_IRK_HEX, exc_info=True,
        )

    # EAD cases (GAP/ADV "Encrypted Data", GAP/SCN/BV-01): the Lower Tester
    # encrypts/decrypts the Encrypted Advertising Data with these workspace
    # values, and auto-pts's `_setup_ead_key_material` (autopts/pybtp/btp/gap.py)
    # pushes the very same constants to the IUT via SET_EAD_KEY_MATERIAL (0x31).
    # keys_shared_via_ixit (zephyr parity) keeps both sides off the GATT
    # round-trip: PTS never reads the IUT's Encrypted Data Key Material
    # characteristic and we never read the LT's.
    try:
        from autopts.pybtp.btp.gap import (
            EAD_INITIALIZATION_VECTOR, EAD_ENCRYPTION_KEY,
        )
        ptses[0].set_pixit("GAP", "TSPX_ead_keys_sharing_method",
                           "keys_shared_via_ixit")
        ptses[0].set_pixit("GAP", "TSPX_encrypted_data_key", EAD_ENCRYPTION_KEY)
        ptses[0].set_pixit("GAP", "TSPX_initialization_vector",
                           EAD_INITIALIZATION_VECTOR)
    except Exception:
        pass  # EAD PIXITs not present in every PTS build


def test_cases(ptses):
    """Return a list of GAP test cases. ptses -- list of PyPTS instances."""
    from autopts.client import get_unique_name
    from autopts.ptsprojects.stack import get_stack
    from autopts.ptsprojects.testcase import TestFunc
    from autopts.pybtp import btp
    from autopts.pybtp.types import Addr, AdFlags, AdType, IOCap, Perm, Prop, UUID, UriScheme

    pts = ptses[0]
    pts_bd_addr = pts.q_bd_addr
    iut_device_name = get_unique_name(pts)
    stack = get_stack()

    # TSPX_advertising_data the Lower Tester scans for in the GAP/BROB/BCST
    # (broadcast-mode) cases. PTS only PASSes when the on-air advertising data
    # contains these structures; the reference IUTs (zephyr/bluez) push this
    # PIXIT in pre_conditions, we never did -> PTS scanned 36s for a stale
    # default and returned INDCSV. Format mirrors zephyr gap.py: flags
    # (BR/EDR-not-supported, discoverable=0) + complete local name, which is
    # exactly what our GAP START_ADVERTISING emits (_apply_mode_to_adv injects
    # the same Flags byte). Value is the hex "len type data" AD-string.
    ad_str_flags = str(AdType.flags).zfill(2) + \
        str(AdFlags.br_edr_not_supp).zfill(2)
    ad_str_flags_len = str(len(ad_str_flags) // 2).zfill(2)
    # get_unique_name returns bytes upstream but a str in some test doubles.
    name_bytes = iut_device_name if isinstance(iut_device_name, bytes) \
        else str(iut_device_name).encode()
    ad_str_name = str(AdType.name_full).zfill(2) + \
        bytes.hex(name_bytes)
    ad_str_name_len = format((len(ad_str_name) // 2), 'x').zfill(2)
    ad_pixit = ad_str_flags_len + ad_str_flags + ad_str_name_len + ad_str_name

    # Full advertising-data field set for stack.gap_init, mirroring zephyr's
    # gap.py. The GAP/ADV/BV-xx "AD type" cases each have a WID handler that
    # pulls one of these (stack.gap.appearance / svc_data / svcs / uri /
    # manufacturer_data / flags) into stack.gap.ad before advertising; we used
    # to call gap_init(name) only, leaving them all None, so every AD-type case
    # advertised just flags+name and PTS never saw the target AD type -> FAIL/
    # INDCSV. periodic_data additionally feeds the GAP/PADV cases.
    iut_manufacturer_data = 'ABCD'
    iut_appearance = '1111'
    iut_svc_data = '1111'
    iut_flags = '11'
    iut_svcs = '1111'
    iut_uri = UriScheme.https + b'github.com/auto-pts'
    periodic_data = (0x08, "PADV_Tester")
    iut_le_supp_feat = 'FF'
    # TSPX_periodic_advertising_data: the periodic advertising data the Lower
    # Tester expects from the IUT in GAP/PADV/PAM and GAP/PADV/PASM. PTS
    # compares the periodic advertising it receives against this PIXIT, so it
    # must be the very AD structure WID 300 pushes to us (len, type, payload) —
    # the workspace default is the PTS sample device's own data and can never
    # match. Same value and formula as the zephyr reference IUT.
    periodic_adv_pixit = bytes.hex(
        bytes([len(periodic_data[1]) + 1, periodic_data[0]])
        + periodic_data[1].encode()
    )
    # TSPX_URI the Lower Tester compares the advertised URI against in
    # GAP/ADV/BV-17 (per its test purpose). Must equal iut_uri (scheme prefix
    # octet + UTF-8 string) as hex — same value zephyr pushes.
    tspx_uri = bytes.hex(iut_uri)

    # Security-gated vendor GATT db for the GAP/SEC (SEM/AUT/CSIGN) cases,
    # mirroring zephyr's gap.py init_gatt_db (which zephyr adds to EVERY GAP
    # case by default). Without it the IUT's GATT server has no characteristic
    # that demands encryption/authentication, so when PTS writes the CCCD /
    # reads a protected char to trigger a Security Mode 1 challenge the IUT
    # silently accepts and PTS waits out TSPX_time_guard (PTS TIMEOUT).
    # Our GATT BTP service (ADD_SERVICE/ADD_CHAR/SET_VALUE/START_SERVER) and the
    # GATTServer's per-permission security enforcement are already in place from
    # the GATT/SR work, so we only need to build the db.
    init_gatt_db = [
        TestFunc(btp.gatts_add_svc, 0, UUID.VND16_1),
        TestFunc(btp.gatts_add_char, 0, Prop.read,
                 Perm.read | Perm.read_authn, UUID.VND16_2),
        TestFunc(btp.gatts_set_val, 0, '01'),
        TestFunc(btp.gatts_add_char, 0, Prop.read,
                 Perm.read | Perm.read_enc, UUID.VND16_3),
        TestFunc(btp.gatts_set_val, 0, '02'),
        TestFunc(btp.gatts_add_char, 0, Prop.read | Prop.write,
                 Perm.read_authn | Perm.write_authn, UUID.VND16_5),
        TestFunc(btp.gatts_set_val, 0, '04'),
        # write_enc-gated char for the SEM write-encryption cases. hdl_wid_139
        # looks up the characteristic whose permission has the test's required
        # bit; BV-24/29/39/43 need Perm.write_enc, which the zephyr-reference 3
        # chars above don't provide, so those cases got handle 0 -> INDCSV.
        # Appended last so the existing handles (VND16_2=3, VND16_5=7) the
        # passing cases resolve are unchanged.
        TestFunc(btp.gatts_add_char, 0, Prop.read | Prop.write,
                 Perm.read | Perm.write_enc, UUID.VND16_4),
        TestFunc(btp.gatts_set_val, 0, '08'),
        TestFunc(btp.gatts_start_server),
    ]

    # Mirror the bluez reference: drop any bond left over from a previous case
    # against the same PTS address. A stale LTK makes the IUT resume encryption
    # with a key PTS no longer has, so bond-related cases (GAP/BOND/BON,
    # GAP/SEC/*) fail in ways that look like protocol errors.
    unpair_pts = TestFunc(btp.gap_unpair, pts_bd_addr, Addr.le_public)

    pre_conditions = [
        TestFunc(btp.core_reg_svc_gap),
        unpair_pts,
        TestFunc(btp.gap_reset),
        TestFunc(stack.gap_init, iut_device_name,
                 iut_manufacturer_data, iut_appearance, iut_svc_data, iut_flags,
                 iut_svcs, iut_uri, periodic_data, iut_le_supp_feat),
        TestFunc(btp.gap_read_controller_info),
        TestFunc(btp.gap_set_bondable_on),
        # display_only (matches bluez reference): MITM-capable io_cap so
        # authenticated pairing (GAP/SEC Mode 1 Level 3/4, GAP/BOND) can run —
        # with PTS=KeyboardDisplay the SC model becomes "IUT displays, PTS
        # inputs" passkey entry, riding the working _PtsSmpDelegate path. The
        # default NoInputNoOutput would force Just Works (unauthenticated) and
        # PTS rejects it with Pairing Failed 0x0A on security cases.
        TestFunc(btp.gap_set_io_capability, IOCap.display_only),
        # Initialise the autopts-side GATT model (stack.gatt / stack.gatt_cl).
        # GAP/SEC WID handlers issue GATT *client* ops toward PTS (e.g. WID 227
        # "Write Request to handle 0x0007"); without gatt_init, stack.gatt_cl is
        # None and auto-pts crashes with AttributeError (verify_values) — which
        # aborts the case before the real pairing step (WID 242 Security
        # Request) is ever reached.
        TestFunc(stack.gatt_init),
        # Register the GATT service then build the security-gated db (above) so
        # GAP/SEC cases have a protected characteristic to challenge on.
        TestFunc(btp.core_reg_svc_gatt),
    ] + init_gatt_db + [
        TestFunc(lambda: update_pixit(
            pts, "GAP", "TSPX_bd_addr_iut", stack.gap.iut_addr_get_str)),
        TestFunc(lambda: update_pixit(
            pts, "GAP", "TSPX_using_public_device_address",
            lambda: "FALSE" if stack.gap.iut_addr_is_random() else "TRUE")),
        TestFunc(lambda: update_pixit(
            pts, "GAP", "TSPX_using_random_device_address",
            lambda: "TRUE" if stack.gap.iut_addr_is_random() else "FALSE")),
        TestFunc(lambda: update_pixit(
            pts, "GAP", "TSPX_advertising_data", ad_pixit)),
        # The name the LT matches on when the IUT advertises from a rotating
        # private address (it cannot track the address itself). bluez pushes
        # it in pre_conditions; we never did, so in the RPA phases PTS looked
        # for a stale/empty name and discarded our advertising reports.
        TestFunc(lambda: update_pixit(
            pts, "GAP", "TSPX_iut_device_name_in_adv_packet_for_random_address",
            iut_device_name)),
        # TGAP(private_addr_int): how often the IUT must change a private
        # address. PTS's workspace default is the 15-minute TGAP value, which
        # makes GAP/BROB/BCST/BV-04 unwatchable — pin it to 5 s (bluez's value)
        # and rotate on the same cadence in PrivacyManager.
        TestFunc(lambda: pts.update_pixit_param(
            "GAP", "TSPX_iut_private_address_interval", "5000")),
        TestFunc(lambda: update_pixit(
            pts, "GAP", "TSPX_URI", tspx_uri)),
        TestFunc(lambda: update_pixit(
            pts, "GAP", "TSPX_periodic_advertising_data",
            periodic_adv_pixit)),
        TestFunc(btp.set_pts_addr, pts_bd_addr, Addr.le_public),
    ]

    # GAP/SEC/AUT/BV-13-C and BV-14-C are deliberately NOT special-cased, even
    # though GAP.TS gives them the Initial Condition "Previous bond exists
    # between the IUT and the Lower Tester with unauthenticated pairing". The
    # Lower Tester never establishes that bond: PTS deletes its own host LTK at
    # case start (`Log_sec - Delete Host LTK`) and offers none in the MMI script
    # (BV-13 has exactly one MMI, WID 78 "send an LE connect request"). So when
    # the IUT correctly encrypts with the pre-existing LTK, PTS's controller
    # asks its host for the key and gets
    # HCI_LONG_TERM_KEY_REQUESTED_NEGATIVE_REPLY, then aborts with
    # "Security Failed. result = 8". That reproduces on the bluez reference IUT
    # too, which registers these two with the plain pre-conditions — auto-pts
    # files them as errata ES-28650 (errata/common.yaml). Keeping the unpair
    # (bluez parity) is therefore the honest behaviour: the case is blocked in
    # the test case, not in the IUT.
    #
    # SC-only pre-condition appended for the "Secure Connections Only" SEM
    # cases (GAP/SEC/SEM/BV-28/29 + BV-41..44): PTS answers/requests pairing
    # WITHOUT the SC bit and expects the IUT to abort with Pairing Failed 0x03
    # — without SC-only mode we happily complete legacy pairing and FAIL.
    # The base pre-conditions (gatt db, pixits) still apply: WID 139 needs the
    # protected-characteristic handle from the same db.
    sc_only_extra = [
        TestFunc(btp.gap_enable_secure_connections_only),
    ]

    # The AUTHENTICATED SC-only cases (level 3 = BV-42/44, level 4 = BV-28/29)
    # additionally need the MITM bit in the initiator's Pairing Request. Their
    # level-2 twins (BV-41/43) must NOT set it — PTS answers 0x09 there and the
    # association models split — so MITM is per-case, never implied by SC-only.
    sc_only_auth_extra = sc_only_extra + [
        TestFunc(btp.gap_set_mitm_on),
    ]

    # "LE security mode 1 level 3/4" pre-condition: those levels require a
    # 16-octet key, so the IUT must answer every Maximum_Encryption_Key_Size in
    # [7,15] with Pairing Failed 0x06 (GAP.TS Figure 4.36). The Upper Tester
    # configures that level here — auto-pts exposes no other lever for it.
    key_size_16_extra = [
        TestFunc(btp.gap_set_min_enc_key_size, 16),
    ]

    # The AUT "Insufficient Authentication/Encryption, Central" cases
    # (BV-24/25/27) run their whole procedure on ONE connection when
    # TSPX_encryption_before_service_request is TRUE (mynewt parity — zephyr
    # doesn't register them; the workspace default is FALSE). With FALSE the
    # LT script disconnects after the preamble pairing and PTS drops its
    # per-connection key material at that disconnect, so the phase-2 Security
    # Request can never be answered from the bond — deterministic INDCSV for
    # any IUT (two radios, 2026-10-28). TRUE keeps the link up: pair in-case,
    # LT Security Request, resume with the fresh bond. WID 267 ("supports
    # user interaction to pair?") must be answered No (mynewt's
    # gap_set_pair_user_interaction(False) — a client-model flag, no BTP).
    # BV-27 additionally wants the fresh pairing AUTHENTICATED (mitm_on).
    aut_central_extra = [
        TestFunc(lambda: pts.update_pixit_param(
            "GAP", "TSPX_encryption_before_service_request", "TRUE")),
        TestFunc(lambda: stack.gap.gap_set_pair_user_interaction(False)),
    ]

    # GAP/CONN/ACEP BV-03/04: the LT advertises with — and expects the IUT to
    # initiate from — resolvable private addresses (Initial Condition: both
    # sides "are using a resolvable private address and have distributed
    # their IRK"). Privacy on before WID 400 makes the auto-connection flow
    # program the LT identity into the resolving list and initiate from an
    # RPA built from the IRK published as TSPX_iut_device_IRK. BV-01/02 use
    # public identities and are left on the plain flow.
    acep_rpa_extra = [
        TestFunc(btp.gap_set_privacy_on),
    ]

    # The RPA-observation cluster has the IUT watch the LT advertise with an
    # RPA and report the resolved identity. Privacy ON before the case makes
    # actions.scan() use Own_Address_Type=0x01, matching the "IUT is using a
    # private address while discovering" framing of these cases; the RPA itself
    # resolves in the controller via the post-bond resolving list (host-side
    # fallback: gap service _resolve_rpa_identity). BV-01-C PASSed this way on
    # 2026-10-29 — the earlier "controller never resolves" reading was the
    # extended-report parser bug (commit e7fa940), not resolution. The
    # public-address sibling OBSV/BV-05 stays plain.
    rpa_observe_extra = [
        TestFunc(btp.gap_set_privacy_on),
    ]

    # GAP/CONN/CPUP/BV-05-C: the Lower Tester builds its Connection Parameter
    # Update Request from these four IXITs and PASSes only if the IUT answers
    # result=0x0001 (request rejected) and keeps the default parameters. The
    # workspace defaults (0008/00AA/0000/0800) are Core-valid, so the responder
    # (mirroring zephyr bt_le_conn_params_valid) accepts them and the case
    # FAILs. Same PIXIT-push precedent as TSPX_advertising_data: publish values
    # that violate Core ranges — each field trips exactly one check in
    # L2CAPManager._le_cpu_params_valid, so rejection fires whichever way the
    # LT combines them (single request or one request per field).
    cpu_bv05_extra = [
        TestFunc(lambda: pts.update_pixit_param(
            "GAP", "TSPX_iut_invalid_connection_interval_min", "0004")),
        TestFunc(lambda: pts.update_pixit_param(
            "GAP", "TSPX_iut_invalid_connection_interval_max", "0005")),
        TestFunc(lambda: pts.update_pixit_param(
            "GAP", "TSPX_iut_invalid_connection_latency", "01F5")),
        TestFunc(lambda: pts.update_pixit_param(
            "GAP", "TSPX_iut_invalid_conn_update_supervision_timeout", "0005")),
    ]

    # Per-case pre-condition overrides.
    custom = {
        "GAP/CONN/CPUP/BV-05-C": list(pre_conditions) + cpu_bv05_extra,
        "GAP/CONN/ACEP/BV-03-C": list(pre_conditions) + acep_rpa_extra,
        "GAP/CONN/ACEP/BV-04-C": list(pre_conditions) + acep_rpa_extra,
        "GAP/DISC/RPA/BV-01-C": list(pre_conditions) + rpa_observe_extra,
        "GAP/BROB/OBSV/BV-06-C": list(pre_conditions) + rpa_observe_extra,
        "GAP/PRIV/CONN/BV-10-C": list(pre_conditions) + rpa_observe_extra,
        # BV-11 is the Central twin: the LT advertises from an RPA and requires
        # our CONNECT_IND's InitA to be an RPA too. Without SET_PRIVACY the
        # normal connect path used the default public identity and the LT
        # silently ignored every connection request (GAP.TS 4.7.5, BV-11).
        "GAP/PRIV/CONN/BV-11-C": list(pre_conditions) + rpa_observe_extra,
        # DCON/BV-04/05 Initial Condition: "The IUT is in Privacy mode" and
        # "The IUT is using a resolvable private address and has distributed
        # its IRK". The LT (also on an RPA) resolves our advertiser address
        # before connecting, so identity-address advertising makes it scan
        # forever. Privacy ON flips WID 20001's Own_Addr_Type to the
        # resolvable-private value and pins our distributed IRK to
        # PTS_IUT_IRK, which is what the LT resolves against. (zephyr bakes
        # this in at build time via CONFIG_BT_PRIVACY, see bot iut_config
        # "privacy.conf", so its per-case list looks empty.)
        "GAP/CONN/DCON/BV-04-C": list(pre_conditions) + rpa_observe_extra,
        "GAP/CONN/DCON/BV-05-C": list(pre_conditions) + rpa_observe_extra,
        "GAP/SEC/AUT/BV-24-C": list(pre_conditions) + aut_central_extra,
        "GAP/SEC/AUT/BV-25-C": list(pre_conditions) + aut_central_extra,
        "GAP/SEC/AUT/BV-27-C": list(pre_conditions) + aut_central_extra + [
            TestFunc(btp.gap_set_mitm_on),
        ],
        # BV-28 is Table 4.32's Peripheral twin: same authenticated-bond
        # preamble, LT-initiated pairing after the encryption failure. mynewt
        # leaves it unregistered, but the PIXIT=TRUE branch is what keeps the
        # link up for it too — without it the LT-initiated pairing lands on a
        # disconnected state and the WID-112 handler deadlocks.
        "GAP/SEC/AUT/BV-28-C": list(pre_conditions) + aut_central_extra + [
            TestFunc(btp.gap_set_mitm_on),
        ],
        # BV-23/24/25 are the Peripheral twins of BV-28/29 (Central). BV-24's
        # Lower Tester does not support LE Secure Connections and initiates
        # authenticated LE *Legacy* pairing, which the IUT must refuse while in
        # Secure Connections Only mode (GAP.TS 4.5.x, step 1). Without the mode
        # we completed legacy pairing and failed the case.
        "GAP/SEC/SEM/BV-24-C": list(pre_conditions) + sc_only_extra,
        # BV-64/67 are the "LE Secure Connections Only – Incoming GATT
        # indication/notification, Central" pair: step 1 puts the IUT into
        # Secure Connections Only mode. Only the failing two are mapped; the
        # Peripheral twins (BV-58 …) already pass and are left alone.
        "GAP/SEC/SEM/BV-64-C": list(pre_conditions) + sc_only_auth_extra,
        "GAP/SEC/SEM/BV-67-C": list(pre_conditions) + sc_only_auth_extra,
        "GAP/SEC/SEM/BV-28-C": list(pre_conditions) + sc_only_auth_extra,
        "GAP/SEC/SEM/BV-29-C": list(pre_conditions) + sc_only_auth_extra,
        "GAP/SEC/SEM/BV-41-C": list(pre_conditions) + sc_only_extra,
        "GAP/SEC/SEM/BV-42-C": list(pre_conditions) + sc_only_auth_extra,
        "GAP/SEC/SEM/BV-43-C": list(pre_conditions) + sc_only_extra,
        "GAP/SEC/SEM/BV-44-C": list(pre_conditions) + sc_only_auth_extra,
        # BV-45 ("re-pair or stop when encryption fails", Central): mynewt's
        # registration is pre_conditions + pair_user_interaction(False) — the
        # same WID-267 flag that unlocked AUT/BV-25. Without it the LT never
        # re-arms its advertising for the scripted post-disconnect reconnect:
        # the second WID 78 scans ~18s of dead air and the case FAILs.
        "GAP/SEC/SEM/BV-45-C": list(pre_conditions) + [
            TestFunc(lambda: stack.gap.gap_set_pair_user_interaction(False)),
        ],
        # Invalid-key-size negatives (mode 1 level 2/3/4). Table 4.19 lists
        # BI-10 (level 4), BI-22 (level 3) and BI-23 (level 2); BI-09/20/21 are
        # the Peripheral-role twins.
        "GAP/SEC/SEM/BI-09-C": list(pre_conditions) + key_size_16_extra,
        "GAP/SEC/SEM/BI-10-C": list(pre_conditions) + key_size_16_extra,
        "GAP/SEC/SEM/BI-20-C": list(pre_conditions) + key_size_16_extra,
        "GAP/SEC/SEM/BI-21-C": list(pre_conditions) + key_size_16_extra,
        "GAP/SEC/SEM/BI-22-C": list(pre_conditions) + key_size_16_extra,
        "GAP/SEC/SEM/BI-23-C": list(pre_conditions) + key_size_16_extra,
    }

    # `TSPX_iut_privacy_enabled` tells the Lower Tester whether the IUT uses
    # private addresses, and PTS branches on it when it sets up its own side
    # (bluez pushes it in pre_conditions for exactly this reason). It is
    # evaluated LAST — after any per-case SET_PRIVACY — so the value reflects
    # the mode the case actually runs with; placed in pre_conditions it would
    # read FALSE for every privacy case and the LT would never configure
    # address resolution, leaving its whitelist-only scan blind to our RPA
    # (GAP/PRIV/CONN/BV-10-C: 300 s with zero advertising reports).
    privacy_enabled_pixit = TestFunc(lambda: update_pixit(
        pts, "GAP", "TSPX_iut_privacy_enabled",
        lambda: "TRUE" if stack.gap.iut_has_privacy() else "FALSE"))

    tc_list = []
    for tc_name in pts.get_test_case_list('GAP'):
        cmds = custom.get(tc_name, list(pre_conditions)) + [privacy_enabled_pixit]
        tc_list.append(PyBlueHostTestCase(
            'GAP', tc_name, cmds=cmds,
            generic_wid_hdl=gap_wid_hdl))

    return tc_list
