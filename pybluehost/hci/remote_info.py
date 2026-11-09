"""Typed HCI remote-information commands and completion-event decoders.

Commands in this module follow Core Spec Vol 4 Part E §7.1 (Link Control
commands). Completion events are decoded from raw ``HCIEvent.parameters``
(§7.7) so both real controllers and the virtual controller use the same wire
layout. In every parsed completion, the fields other than ``status`` are only
meaningful when ``status == 0``.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import (
    EventCode,
    HCI_READ_REMOTE_EXTENDED_FEATURES,
    HCI_READ_REMOTE_SUPPORTED_FEATURES,
    HCI_READ_REMOTE_VERSION_INFORMATION,
    HCI_REMOTE_NAME_REQUEST,
)
from pybluehost.hci.format_fields import lookup_company_name
from pybluehost.hci.packets import HCICommand, HCIEvent


class RemoteInformationError(ValueError):
    """A remote-information completion event does not match its request."""


@dataclass(frozen=True)
class RemoteName:
    status: int
    name: str


@dataclass(frozen=True)
class RemoteSupportedFeatures:
    status: int
    lmp_features: bytes


@dataclass(frozen=True)
class RemoteExtendedFeatures:
    status: int
    page_number: int
    max_page_number: int
    extended_lmp_features: bytes


@dataclass(frozen=True)
class RemoteVersionInformation:
    status: int
    lmp_version: int
    company_id: int
    lmp_subversion: int

    @property
    def company(self) -> str:
        return company_name(self.company_id)


@dataclass
class RemoteDeviceInformation:
    """Best-effort snapshot of the information read over HCI for one link.

    ``errors`` is keyed by query name — one of ``"remote_name"``,
    ``"supported_features"``, ``"extended_features"``, ``"version_information"``.
    A query that fails leaves its field unset (or absent from
    ``extended_features``) and records a human-readable reason under its key.
    """

    handle: int
    remote_name: RemoteName | None = None
    supported_features: RemoteSupportedFeatures | None = None
    extended_features: list[RemoteExtendedFeatures] = field(default_factory=list)
    version_information: RemoteVersionInformation | None = None
    errors: dict[str, str] = field(default_factory=dict)


def company_name(company_id: int) -> str:
    """Resolve a Bluetooth SIG Company Identifier to its assigned name.

    Falls back to ``"Unknown (0xNNNN)"`` when the identifier is unassigned or
    the SIG submodule (its YAML data) is not available. The lookup itself lives
    in :func:`pybluehost.hci.format_fields.lookup_company_name`, so there is a
    single implementation shared with ``format_company_id``.
    """
    fallback = f"Unknown (0x{company_id:04X})"
    try:
        name = lookup_company_name(company_id)
    except Exception:  # SIG data may be absent in a checkout without the submodule
        return fallback
    return name or fallback


def build_remote_name_request(peer: BDAddress) -> HCICommand:
    """Build HCI_Remote_Name_Request (Core Vol 4 Part E §7.1.19).

    Body: BD_ADDR(6) + Page_Scan_Repetition_Mode(1) + Reserved(1) +
    Clock_Offset(2) — 10 octets total.
    """
    return HCICommand(
        opcode=HCI_REMOTE_NAME_REQUEST,
        parameters=(
            peer.to_hci()
            + bytes([0x01])  # Page_Scan_Repetition_Mode
            + bytes([0x00])  # Reserved
            + bytes([0x00, 0x00])  # Clock_Offset
        ),
    )


def build_read_remote_supported_features(handle: int) -> HCICommand:
    return HCICommand(
        opcode=HCI_READ_REMOTE_SUPPORTED_FEATURES,
        parameters=struct.pack("<H", handle),
    )


def build_read_remote_extended_features(handle: int, *, page_number: int) -> HCICommand:
    return HCICommand(
        opcode=HCI_READ_REMOTE_EXTENDED_FEATURES,
        parameters=struct.pack("<HB", handle, page_number),
    )


def build_read_remote_version_information(handle: int) -> HCICommand:
    return HCICommand(
        opcode=HCI_READ_REMOTE_VERSION_INFORMATION,
        parameters=struct.pack("<H", handle),
    )


def _validate_completion(
    event: HCIEvent, expected_code: int, *, name: str, min_length: int,
) -> bytes:
    """Check event code and payload length, returning ``event.parameters``."""
    if event.event_code != expected_code:
        raise RemoteInformationError(
            f"wrong event code for {name}: got 0x{event.event_code:02X}, "
            f"expected 0x{expected_code:02X}"
        )
    params = event.parameters
    if len(params) < min_length:
        raise RemoteInformationError(
            f"{name} completion truncated: {len(params)} bytes (need >= {min_length})"
        )
    return params


def _validate_handle_completion(
    event: HCIEvent, expected_code: int, handle: int, *, name: str, min_length: int,
) -> bytes:
    """Check event code, length, and the connection handle echoed by the controller."""
    params = _validate_completion(
        event, expected_code, name=name, min_length=min_length,
    )
    peer_handle = struct.unpack_from("<H", params, 1)[0]
    if peer_handle != handle:
        raise RemoteInformationError(
            f"{name} completion handle mismatch: got 0x{peer_handle:04X}, "
            f"expected 0x{handle:04X}"
        )
    return params


def parse_remote_name_request_complete(event: HCIEvent, peer: BDAddress) -> RemoteName:
    # Status(1) + BD_ADDR(6) + Name(248).
    params = _validate_completion(
        event, int(EventCode.REMOTE_NAME_REQUEST_COMPLETE),
        name="remote name", min_length=255,
    )
    if params[1:7] != peer.to_hci():
        raise RemoteInformationError(
            f"remote name completion address mismatch: got {params[1:7].hex()}, "
            f"expected {peer.to_hci().hex()}"
        )
    return RemoteName(
        status=params[0],
        name=params[7:255].rstrip(b"\x00").decode("utf-8", errors="replace"),
    )


def parse_remote_supported_features_complete(event: HCIEvent, handle: int) -> RemoteSupportedFeatures:
    # Status(1) + Connection_Handle(2) + LMP_Features(8).
    params = _validate_handle_completion(
        event, int(EventCode.READ_REMOTE_SUPPORTED_FEATURES_COMPLETE), handle,
        name="remote supported features", min_length=11,
    )
    return RemoteSupportedFeatures(status=params[0], lmp_features=params[3:11])


def parse_remote_extended_features_complete(
    event: HCIEvent, handle: int, *, page_number: int,
) -> RemoteExtendedFeatures:
    # Status(1) + Connection_Handle(2) + Page_Number(1) + Maximum_Page_Number(1)
    # + Extended_LMP_Features(8).
    params = _validate_handle_completion(
        event, int(EventCode.READ_REMOTE_EXTENDED_FEATURES_COMPLETE), handle,
        name="remote extended features", min_length=13,
    )
    if params[3] != page_number:
        raise RemoteInformationError(
            f"remote extended features page mismatch: got {params[3]}, "
            f"expected {page_number}"
        )
    return RemoteExtendedFeatures(
        status=params[0],
        page_number=params[3],
        max_page_number=params[4],
        extended_lmp_features=params[5:13],
    )


def parse_remote_version_information_complete(
    event: HCIEvent, handle: int,
) -> RemoteVersionInformation:
    # Status(1) + Connection_Handle(2) + Version(1, LMP version) +
    # Manufacturer_Name(2, Company_ID) + Subversion(2).
    # There is no HCI_Revision field in the remote variant.
    params = _validate_handle_completion(
        event, int(EventCode.READ_REMOTE_VERSION_COMPLETE), handle,
        name="remote version", min_length=8,
    )
    lmp_version, company_id, lmp_subversion = struct.unpack_from("<BHH", params, 3)
    return RemoteVersionInformation(
        status=params[0],
        lmp_version=lmp_version,
        company_id=company_id,
        lmp_subversion=lmp_subversion,
    )
