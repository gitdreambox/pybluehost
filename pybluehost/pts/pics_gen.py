"""PICS draft generator — mine PyBlueHost capability dump for Phase 1 PICS hints.

Output is a per-group dict of `feature_name → {supported: bool, evidence: str}`.
Operators copy this draft into PTS UI manually; v1.2 does not write PTS-proprietary
project files.

See design spec §6.
"""
from __future__ import annotations

from typing import Any


# Phase 1 minimal PICS items per group. Each entry: feature_name → (description, predicate fn, evidence_template).
# The predicate inspects the capabilities dict; the evidence string explains the choice.
_GROUP_PICS_RULES = {
    "HCI": {
        "TSPC_HCI_3_1": (
            "any HCI Command supported",
            lambda caps: bool(caps.get("supported_commands")),
            "supported_commands present in capability dump",
        ),
        "TSPC_HCI_LE": (
            "LE supported",
            lambda caps: _bool(caps.get("capability_summary", {}).get("le_supported")),
            "capability_summary.le_supported = True",
        ),
        "TSPC_HCI_BREDR": (
            "BR/EDR supported",
            lambda caps: _bool(caps.get("capability_summary", {}).get("bredr_supported")),
            "capability_summary.bredr_supported = True",
        ),
    },
    "L2CAP": {
        "TSPC_L2CAP_LE": (
            "LE L2CAP",
            lambda caps: _bool(caps.get("capability_summary", {}).get("le_supported")),
            "implied by le_supported",
        ),
        "TSPC_L2CAP_CLASSIC": (
            "Classic L2CAP",
            lambda caps: _bool(caps.get("capability_summary", {}).get("bredr_supported")),
            "implied by bredr_supported",
        ),
    },
    "GAP": {
        "TSPC_GAP_LE_CENTRAL": (
            "LE central role",
            lambda caps: _bool(caps.get("capability_summary", {}).get("le_central")),
            "capability_summary.le_central",
        ),
        "TSPC_GAP_LE_PERIPHERAL": (
            "LE peripheral role",
            lambda caps: _bool(caps.get("capability_summary", {}).get("le_peripheral")),
            "capability_summary.le_peripheral",
        ),
        "TSPC_GAP_BREDR": (
            "BR/EDR GAP",
            lambda caps: _bool(caps.get("capability_summary", {}).get("bredr_supported")),
            "implied by bredr_supported",
        ),
    },
    "GATT": {
        "TSPC_GATT_CLIENT": (
            "GATT client",
            lambda caps: _bool(caps.get("capability_summary", {}).get("le_supported")),
            "GATT client always supported when LE supported in PyBlueHost",
        ),
        "TSPC_GATT_SERVER": (
            "GATT server",
            lambda caps: _bool(caps.get("capability_summary", {}).get("le_supported")),
            "GATT server always supported when LE supported in PyBlueHost",
        ),
    },
    "SMP": {
        "TSPC_SMP_LEGACY": (
            "Legacy pairing",
            lambda caps: _bool(caps.get("capability_summary", {}).get("le_supported")),
            "SMP legacy always supported in PyBlueHost when LE present",
        ),
        "TSPC_SMP_SC": (
            "Secure Connections",
            lambda caps: _bool(caps.get("capability_summary", {}).get("le_sc")),
            "capability_summary.le_sc",
        ),
    },
    "SDP": {
        "TSPC_SDP_BR_EDR": (
            "Classic SDP",
            lambda caps: _bool(caps.get("capability_summary", {}).get("bredr_supported")),
            "implied by bredr_supported (SDP impl exists in pybluehost/classic/sdp.py)",
        ),
    },
    "RFCOMM": {
        "TSPC_RFCOMM_BR_EDR": (
            "Classic RFCOMM",
            lambda caps: _bool(caps.get("capability_summary", {}).get("bredr_supported")),
            "implied by bredr_supported (RFCOMM impl exists in pybluehost/classic/rfcomm.py)",
        ),
    },
}


def _bool(v: Any) -> bool:
    """Convert value to bool safely."""
    return bool(v) if v is not None else False


def generate_pics_draft(capabilities: dict) -> dict[str, dict[str, dict]]:
    """Generate per-group PICS draft from a PyBlueHost capability dump.

    Each group → dict of `feature_name → {supported, evidence, description}`.
    See design spec §6.
    """
    result: dict[str, dict[str, dict]] = {}
    for group, rules in _GROUP_PICS_RULES.items():
        group_dict: dict[str, dict] = {}
        for feature_name, (description, predicate, evidence) in rules.items():
            try:
                supported = predicate(capabilities)
            except Exception:  # noqa: BLE001
                supported = False
            group_dict[feature_name] = {
                "supported": supported,
                "evidence": evidence,
                "description": description,
            }
        result[group] = group_dict
    return result
