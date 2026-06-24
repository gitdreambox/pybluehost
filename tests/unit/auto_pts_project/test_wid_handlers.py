"""auto_pts_project.pybluehost_iut.wid.* — WID adapter shape + upstream-graceful fallback."""
import pytest


def test_wid_modules_load():
    """All four WID modules import cleanly even without autoptsclient on sys.path."""
    from auto_pts_project.pybluehost_iut.wid import gap, gatt, l2cap, sm
    assert hasattr(gap, "gap_wid_hdl")
    assert hasattr(gatt, "gatt_wid_hdl")
    assert hasattr(l2cap, "l2cap_wid_hdl")
    assert hasattr(sm, "sm_wid_hdl")


def test_wid_dispatch_dicts_are_dicts():
    from auto_pts_project.pybluehost_iut.wid import gap, gatt, l2cap, sm
    assert isinstance(gap.gap_wid_hdl, dict)
    assert isinstance(gatt.gatt_wid_hdl, dict)
    assert isinstance(l2cap.l2cap_wid_hdl, dict)
    assert isinstance(sm.sm_wid_hdl, dict)


def test_overrides_list_present_and_empty_in_v1():
    """Baseline P.9 v1: no PyBlueHost-specific WID overrides."""
    from auto_pts_project.pybluehost_iut.wid import gap, gatt, l2cap, sm
    assert gap.PYBLUEHOST_OVERRIDES == []
    assert gatt.PYBLUEHOST_OVERRIDES == []
    assert l2cap.PYBLUEHOST_OVERRIDES == []
    assert sm.PYBLUEHOST_OVERRIDES == []


def test_wid_dicts_inherit_upstream_when_available():
    """If autoptsclient's wid.gap is on sys.path, our dict includes upstream entries."""
    try:
        import wid.gap  # noqa: F401
    except ImportError:
        pytest.skip("autoptsclient not installed; upstream inheritance untestable here")
    from auto_pts_project.pybluehost_iut.wid import gap as pb_gap
    from wid.gap import gap_wid_hdl as upstream
    for k, v in upstream.items():
        # Our dict has every upstream entry (we may add overrides on top later).
        assert pb_gap.gap_wid_hdl[k] is v or pb_gap.gap_wid_hdl[k] is not None
