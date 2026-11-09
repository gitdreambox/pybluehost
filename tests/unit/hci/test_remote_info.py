"""Tests for HCI remote-information commands and completion events."""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from pybluehost.core.address import BDAddress
from pybluehost.hci.constants import (
    EventCode,
    HCI_READ_REMOTE_EXTENDED_FEATURES,
    HCI_READ_REMOTE_SUPPORTED_FEATURES,
    HCI_READ_REMOTE_VERSION_INFORMATION,
    HCI_REMOTE_NAME_REQUEST,
    OGF,
    ogf_ocf,
)
from pybluehost.hci.format_fields import format_company_id
from pybluehost.hci.packets import HCIEvent
from pybluehost.hci.remote_info import (
    RemoteDeviceInformation,
    RemoteExtendedFeatures,
    RemoteInformationError,
    RemoteName,
    RemoteSupportedFeatures,
    RemoteVersionInformation,
    build_read_remote_extended_features,
    build_read_remote_supported_features,
    build_read_remote_version_information,
    build_remote_name_request,
    company_name,
    parse_remote_extended_features_complete,
    parse_remote_name_request_complete,
    parse_remote_supported_features_complete,
    parse_remote_version_information_complete,
)

PEER = BDAddress.from_string("1A:8D:8D:1B:F5:6B")

_HANDLE = 0x0042

# Short payloads (Status + Connection_Handle) that must be rejected by every
# parser because the type-specific fields are missing.
_TRUNCATED_COMMAND = b"\x00\x42\x00"


def _event(event_code: int, parameters: bytes) -> HCIEvent:
    return HCIEvent(event_code=int(event_code), parameters=parameters)


def test_remote_information_opcodes_match_core_spec():
    assert ogf_ocf(HCI_READ_REMOTE_SUPPORTED_FEATURES) == (OGF.LINK_CONTROL, 0x1B)
    assert ogf_ocf(HCI_READ_REMOTE_EXTENDED_FEATURES) == (OGF.LINK_CONTROL, 0x1C)
    assert ogf_ocf(HCI_READ_REMOTE_VERSION_INFORMATION) == (OGF.LINK_CONTROL, 0x1D)
    assert ogf_ocf(HCI_REMOTE_NAME_REQUEST) == (OGF.LINK_CONTROL, 0x19)


def test_remote_information_command_bodies_are_exact():
    name_command = build_remote_name_request(PEER)
    assert name_command.opcode == HCI_REMOTE_NAME_REQUEST
    # BD_ADDR(6) + Page_Scan_Repetition_Mode(1) + Reserved(1) + Clock_Offset(2).
    assert name_command.parameters == bytes.fromhex("6bf51b8d8d1a01000000")

    supported = build_read_remote_supported_features(_HANDLE)
    assert supported.opcode == HCI_READ_REMOTE_SUPPORTED_FEATURES
    assert supported.parameters == b"\x42\x00"

    extended = build_read_remote_extended_features(_HANDLE, page_number=1)
    assert extended.opcode == HCI_READ_REMOTE_EXTENDED_FEATURES
    assert extended.parameters == b"\x42\x00\x01"

    version = build_read_remote_version_information(_HANDLE)
    assert version.opcode == HCI_READ_REMOTE_VERSION_INFORMATION
    assert version.parameters == b"\x42\x00"


def test_parse_remote_name_request_complete_decodes_nul_padded_name():
    params = b"\x00" + PEER.to_hci() + b"Remote Device".ljust(248, b"\x00")
    event = _event(EventCode.REMOTE_NAME_REQUEST_COMPLETE, params)

    parsed = parse_remote_name_request_complete(event, PEER)

    assert isinstance(parsed, RemoteName)
    assert parsed.status == 0
    assert parsed.name == "Remote Device"


def test_parse_remote_name_request_complete_replaces_non_utf8_bytes():
    """Non-UTF-8 names must degrade to replacement chars, not raise."""
    params = b"\x00" + PEER.to_hci() + b"Caf\xe9".ljust(248, b"\x00")
    event = _event(EventCode.REMOTE_NAME_REQUEST_COMPLETE, params)

    assert parse_remote_name_request_complete(event, PEER).name == "Caf�"


def test_parse_remote_name_completion_without_name_field_is_truncated():
    """Status + BD_ADDR alone is not a valid completion: the Name field is required."""
    params = b"\x00" + PEER.to_hci()
    event = _event(EventCode.REMOTE_NAME_REQUEST_COMPLETE, params)

    with pytest.raises(RemoteInformationError, match="truncated"):
        parse_remote_name_request_complete(event, PEER)


def test_parse_remote_name_rejects_wrong_address():
    event = _event(
        EventCode.REMOTE_NAME_REQUEST_COMPLETE,
        b"\x00" + bytes(6) + b"Name".ljust(248, b"\x00"),
    )
    with pytest.raises(RemoteInformationError, match="address"):
        parse_remote_name_request_complete(event, PEER)


def test_parse_remote_supported_features_complete_decodes_handle_and_bitmap():
    params = b"\x00\x42\x00" + bytes.fromhex("ff59000800000000")
    event = _event(EventCode.READ_REMOTE_SUPPORTED_FEATURES_COMPLETE, params)
    parsed = parse_remote_supported_features_complete(event, _HANDLE)
    assert isinstance(parsed, RemoteSupportedFeatures)
    assert parsed.status == 0
    assert parsed.lmp_features.hex() == "ff59000800000000"


def test_parse_remote_extended_features_complete_decodes_page_fields():
    params = b"\x00\x42\x00\x01\x02" + bytes.fromhex("0000000000000000")
    event = _event(EventCode.READ_REMOTE_EXTENDED_FEATURES_COMPLETE, params)
    parsed = parse_remote_extended_features_complete(event, _HANDLE, page_number=1)
    assert isinstance(parsed, RemoteExtendedFeatures)
    assert parsed.status == 0
    assert parsed.page_number == 1
    assert parsed.max_page_number == 2
    assert parsed.extended_lmp_features == bytes(8)


def test_parse_remote_extended_features_rejects_a_different_echoed_page():
    params = b"\x00\x42\x00\x07\x09" + bytes.fromhex("0000000000000000")
    event = _event(EventCode.READ_REMOTE_EXTENDED_FEATURES_COMPLETE, params)

    with pytest.raises(RemoteInformationError, match="page"):
        parse_remote_extended_features_complete(event, _HANDLE, page_number=1)


def test_parse_remote_version_information_complete_decodes_company_id():
    payload = struct.pack("<BHH", 0x0C, 0x000F, 0x1234)
    event = _event(EventCode.READ_REMOTE_VERSION_COMPLETE, b"\x00\x42\x00" + payload)
    parsed = parse_remote_version_information_complete(event, _HANDLE)
    assert isinstance(parsed, RemoteVersionInformation)
    assert parsed.status == 0
    assert parsed.lmp_version == 0x0C
    assert parsed.company_id == 0x000F
    assert parsed.lmp_subversion == 0x1234


def test_company_name_resolves_sig_company_identifiers():
    sig_data = (
        Path(__file__).resolve().parents[3]
        / "pybluehost" / "lib" / "sig"
        / "assigned_numbers" / "company_identifiers" / "company_identifiers.yaml"
    )
    if not sig_data.exists():
        pytest.skip("SIG submodule not initialized")

    event = _event(
        EventCode.READ_REMOTE_VERSION_COMPLETE,
        b"\x00\x42\x00" + struct.pack("<BHH", 0x0C, 0x000F, 0x1234),
    )
    parsed = parse_remote_version_information_complete(event, _HANDLE)

    assert company_name(0x000F) == "Broadcom Corporation"
    assert parsed.company == "Broadcom Corporation"


def test_company_name_falls_back_for_unknown_identifiers():
    assert company_name(0xFFFE) == "Unknown (0xFFFE)"


def test_company_name_and_format_company_id_share_the_lookup():
    sig_data = (
        Path(__file__).resolve().parents[3]
        / "pybluehost" / "lib" / "sig"
        / "assigned_numbers" / "company_identifiers" / "company_identifiers.yaml"
    )
    if not sig_data.exists():
        pytest.skip("SIG submodule not initialized")

    # Known id: the formatted form wraps exactly the bare name this module exposes.
    assert format_company_id(0x000F) == f"0x{0x000F:04X} ({company_name(0x000F)})"
    # Unassigned id: no name suffix in the formatted form, fallback in the bare form.
    assert format_company_id(0xFFFE) == f"0x{0xFFFE:04X}"
    assert company_name(0xFFFE).startswith("Unknown (")


@pytest.mark.parametrize("event_code, parser", [
    (EventCode.REMOTE_NAME_REQUEST_COMPLETE,
     lambda event: parse_remote_name_request_complete(event, PEER)),
    (EventCode.READ_REMOTE_SUPPORTED_FEATURES_COMPLETE,
     lambda event: parse_remote_supported_features_complete(event, _HANDLE)),
    (EventCode.READ_REMOTE_EXTENDED_FEATURES_COMPLETE,
     lambda event: parse_remote_extended_features_complete(event, _HANDLE, page_number=1)),
    (EventCode.READ_REMOTE_VERSION_COMPLETE,
     lambda event: parse_remote_version_information_complete(event, _HANDLE)),
], ids=["name", "supported_features", "extended_features", "version"])
def test_remote_information_parsers_reject_truncated_payloads(event_code, parser):
    event = _event(event_code, _TRUNCATED_COMMAND)
    with pytest.raises(RemoteInformationError, match="truncated"):
        parser(event)


@pytest.mark.parametrize("event_code, handler", [
    (EventCode.READ_REMOTE_SUPPORTED_FEATURES_COMPLETE,
     parse_remote_supported_features_complete),
    (EventCode.READ_REMOTE_EXTENDED_FEATURES_COMPLETE,
     lambda event, handle: parse_remote_extended_features_complete(
         event, handle, page_number=1,
     )),
    (EventCode.READ_REMOTE_VERSION_COMPLETE,
     parse_remote_version_information_complete),
], ids=["supported_features", "extended_features", "version"])
def test_remote_information_parsers_reject_wrong_handle(event_code, handler):
    # Payload is long enough for every parser, only the echoed handle differs.
    params = b"\x00\x43\x00\x01\x02" + bytes(8)
    event = _event(event_code, params)
    with pytest.raises(RemoteInformationError, match="handle"):
        handler(event, _HANDLE)


def test_remote_information_parsers_reject_a_wrong_event_code():
    version_event = _event(
        EventCode.READ_REMOTE_VERSION_COMPLETE,
        b"\x00\x42\x00" + struct.pack("<BHH", 0x0C, 0x000F, 0x1234),
    )
    with pytest.raises(RemoteInformationError, match="event code"):
        parse_remote_supported_features_complete(version_event, _HANDLE)


def test_remote_device_snapshot_defaults_are_empty():
    snapshot = RemoteDeviceInformation(handle=_HANDLE)
    assert snapshot.remote_name is None
    assert snapshot.supported_features is None
    assert snapshot.extended_features == []
    assert snapshot.version_information is None
    assert snapshot.errors == {}


def test_remote_device_snapshot_defaults_are_per_instance():
    first = RemoteDeviceInformation(handle=_HANDLE)
    first.extended_features.append(RemoteExtendedFeatures(0, 1, 2, bytes(8)))
    first.errors["version_information"] = "timeout"

    second = RemoteDeviceInformation(handle=0x0043)
    assert second.extended_features == []
    assert second.errors == {}
