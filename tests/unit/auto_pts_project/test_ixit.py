"""auto_pts_project.pybluehost_iut.ixit — IXIT parameter dicts for autoptsclient."""
import re


def test_ixit_has_required_fields():
    from auto_pts_project.pybluehost_iut import ixit
    assert "TSPX_bd_addr_iut" in ixit.IXIT_GAP
    assert "TSPX_iut_role_initiator" in ixit.IXIT_GAP
    assert "TSPX_iut_role_acceptor" in ixit.IXIT_GAP


def test_ixit_values_are_strings():
    """auto-pts treats IXIT values as strings (consistent with PTS XML)."""
    from auto_pts_project.pybluehost_iut import ixit
    for group_attr in ("IXIT_GAP", "IXIT_GATT", "IXIT_L2CAP", "IXIT_SMP"):
        d = getattr(ixit, group_attr)
        for k, v in d.items():
            assert isinstance(v, str), \
                f"{group_attr}[{k!r}] is {type(v).__name__}, expected str"


def test_ixit_bd_addr_is_12_hex_chars():
    from auto_pts_project.pybluehost_iut import ixit
    assert re.fullmatch(r"[0-9A-Fa-f]{12}", ixit.IXIT_GAP["TSPX_bd_addr_iut"])
    assert re.fullmatch(r"[0-9A-Fa-f]{12}", ixit.IXIT_GATT["TSPX_bd_addr_iut"])


def test_ixit_l2cap_psm_is_hex():
    from auto_pts_project.pybluehost_iut import ixit
    assert re.fullmatch(r"[0-9A-Fa-f]{4}", ixit.IXIT_L2CAP["TSPX_psm"])
    assert re.fullmatch(r"[0-9A-Fa-f]{4}", ixit.IXIT_L2CAP["TSPX_le_psm"])


def test_ixit_smp_oob_data_is_16_bytes():
    """OOB data (TK) is 16 bytes — 32 hex chars."""
    from auto_pts_project.pybluehost_iut import ixit
    assert re.fullmatch(r"[0-9A-Fa-f]{32}", ixit.IXIT_SMP["TSPX_oob_data"])
