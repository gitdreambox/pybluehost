"""PICS — Protocol Implementation Conformance Statement for autoptsclient.

Each ``PICS_<GROUP>`` attribute is a flat ``dict[FEATURE_ID, bool]`` queried
by autoptsclient at session start to decide which test cases apply.

Source of truth: ``docs/pts/pics/<group>.draft.yaml``. Operators regenerate
per their own adapter with::

    pybluehost tools pics-gen -c docs/hardware/<adapter>.json

The committed defaults are the intel-BE200 reference.
"""
from __future__ import annotations

from pathlib import Path

from pybluehost.pts.pics_gen import yaml_draft_to_autopts_dict


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PICS_DIR = _REPO_ROOT / "docs" / "pts" / "pics"


def _load(group_name: str) -> dict[str, bool]:
    """Best-effort load of a group's PICS dict; empty dict when missing."""
    path = _PICS_DIR / f"{group_name.lower()}.draft.yaml"
    if not path.exists():
        return {}
    return yaml_draft_to_autopts_dict(path)


PICS_GAP = _load("GAP")
PICS_GATT = _load("GATT")
PICS_L2CAP = _load("L2CAP")
PICS_SMP = _load("SMP")
PICS_HCI = _load("HCI")
PICS_SDP = _load("SDP")        # not exercised by Phase 2 BTP; kept for completeness
PICS_RFCOMM = _load("RFCOMM")  # same
