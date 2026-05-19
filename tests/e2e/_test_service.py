"""Canonical GATT service used by tests/e2e/ scenarios.

Three characteristics:
  * read   - fixed initial value (TEST_READ).
  * write  - Write Without Response + Write; tests append observed writes.
  * notify - Notify; tests subscribe and observe value updates.
"""
from __future__ import annotations

from pybluehost.ble.gatt import (
    CharacteristicDefinition,
    CharProperties,
    DescriptorDefinition,
    Permissions,
    ServiceDefinition,
)
from pybluehost.core.uuid import UUID16, UUID128


TEST_SERVICE_UUID = UUID128(bytes.fromhex("0000feed0000100080000000746573e2"))
TEST_READ_CHAR_UUID = UUID128(bytes.fromhex("0000feed0000100080000000feed0001"))
TEST_WRITE_CHAR_UUID = UUID128(bytes.fromhex("0000feed0000100080000000feed0002"))
TEST_NOTIFY_CHAR_UUID = UUID128(bytes.fromhex("0000feed0000100080000000feed0003"))

INITIAL_READ_VALUE = b"PyBlueHost E2E v1"
INITIAL_NOTIFY_VALUE = b"\x00"

CCCD_UUID = UUID16(0x2902)


def build_test_service() -> ServiceDefinition:
    """Return the canonical E2E test service definition."""
    return ServiceDefinition(
        uuid=TEST_SERVICE_UUID,
        is_primary=True,
        characteristics=[
            CharacteristicDefinition(
                uuid=TEST_READ_CHAR_UUID,
                properties=CharProperties.READ,
                permissions=Permissions.READABLE,
                value=INITIAL_READ_VALUE,
            ),
            CharacteristicDefinition(
                uuid=TEST_WRITE_CHAR_UUID,
                properties=CharProperties.WRITE | CharProperties.WRITE_WITHOUT_RESPONSE,
                permissions=Permissions.WRITABLE,
                value=b"",
            ),
            CharacteristicDefinition(
                uuid=TEST_NOTIFY_CHAR_UUID,
                properties=CharProperties.NOTIFY | CharProperties.READ,
                permissions=Permissions.READABLE,
                value=INITIAL_NOTIFY_VALUE,
                descriptors=[
                    DescriptorDefinition(
                        uuid=CCCD_UUID,
                        permissions=Permissions.READABLE | Permissions.WRITABLE,
                        value=b"\x00\x00",
                    ),
                ],
            ),
        ],
    )
