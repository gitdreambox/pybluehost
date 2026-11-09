"""Feature-bitmap decoding helpers.

The tables in :mod:`pybluehost.hci.features_decode` map ``(octet, bit)`` to the
name the spec gives that feature. ``supported_feature_names`` turns a raw
bitmap into the names whose bits are set, in table (spec) order, and
``unnamed_feature_bit_count`` reports how many set bits the table does not name
(reserved / previously-used positions) so a caller never implies the decoded
list is exhaustive. Positions come from Core Spec 5.4 Vol 2 Part C §3.3
Table 3.2 (BR/EDR page 0) and Table 3.3 (page 1).
"""
from __future__ import annotations

from pybluehost.hci.features_decode import (
    BREDR_FEATURE_BIT_NAMES,
    BREDR_FEATURE_BIT_NAMES_P1,
    supported_feature_names,
    unnamed_feature_bit_count,
)

# Octet 0 = 0xff (all eight named), octet 1 = 0b01011001, octet 3 bit 3.
LMP_FEATURES = bytes.fromhex("ff59000800000000")


def test_supported_feature_names_lists_every_named_bit_that_is_set():
    assert supported_feature_names(LMP_FEATURES, BREDR_FEATURE_BIT_NAMES) == [
        "3-slot packets",
        "5-slot packets",
        "Encryption",
        "Slot offset",
        "Timing accuracy",
        "Role switch",
        "Hold mode",
        "Sniff mode",
        "Previously used (was Park state)",
        "SCO link",
        "HV2 packets",
        "u-law log synchronous data",
        "Enhanced inquiry scan",
    ]


def test_supported_feature_names_uses_the_page_specific_table():
    page1 = b"\x09" + bytes(7)
    assert supported_feature_names(page1, BREDR_FEATURE_BIT_NAMES_P1) == [
        "Secure Simple Pairing (Host Support)",
        "Secure Connections (Host Support)",
    ]


def test_unnamed_feature_bit_count_reports_only_set_bits_the_table_cannot_name():
    assert unnamed_feature_bit_count(LMP_FEATURES, BREDR_FEATURE_BIT_NAMES) == 0
    assert unnamed_feature_bit_count(bytes(8), BREDR_FEATURE_BIT_NAMES) == 0
    # Octet 3 bit 0 is not in Table 3.2, so that lone set bit stays unnamed.
    assert unnamed_feature_bit_count(
        b"\x00\x00\x00\x01" + bytes(4), BREDR_FEATURE_BIT_NAMES
    ) == 1


def test_supported_feature_names_tolerates_a_bitmap_shorter_than_the_table():
    assert supported_feature_names(b"\xff", BREDR_FEATURE_BIT_NAMES) == [
        "3-slot packets",
        "5-slot packets",
        "Encryption",
        "Slot offset",
        "Timing accuracy",
        "Role switch",
        "Hold mode",
        "Sniff mode",
    ]
