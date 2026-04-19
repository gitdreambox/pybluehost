"""Tests for Intel and Realtek vendor HCI constants and response parsers."""

from pybluehost.hci.vendor.intel import (
    HCI_VS_INTEL_READ_VERSION,
    HCI_VS_INTEL_WRITE_FIRMWARE,
    INTEL_TLV_TYPE_CNV,
    INTEL_TLV_TYPE_TIMESTAMP,
    IntelReadVersionResponse,
)
from pybluehost.hci.vendor.realtek import (
    HCI_VS_REALTEK_READ_ROM_VERSION,
    HCI_VS_REALTEK_WRITE_FIRMWARE,
    RealtekROMVersion,
)
from pybluehost.hci.constants import OGF


# --- Intel ---

def test_intel_read_version_opcode():
    assert HCI_VS_INTEL_READ_VERSION == 0xFC05


def test_intel_write_firmware_opcode():
    assert HCI_VS_INTEL_WRITE_FIRMWARE == 0xFC20


def test_intel_opcodes_use_vendor_ogf():
    assert (HCI_VS_INTEL_READ_VERSION >> 10) & 0x3F == int(OGF.VENDOR)
    assert (HCI_VS_INTEL_WRITE_FIRMWARE >> 10) & 0x3F == int(OGF.VENDOR)


def test_intel_tlv_constants():
    assert INTEL_TLV_TYPE_CNV == 0x10
    assert INTEL_TLV_TYPE_TIMESTAMP == 0x18


def test_intel_read_version_response_fields():
    resp = IntelReadVersionResponse(
        status=0x00, hw_platform=0x37, hw_variant=0x17, hw_revision=0x00,
        fw_variant=0x23, fw_revision=0x10, fw_build_num=0x00,
        fw_build_week=0x27, fw_build_year=0x19, fw_patch_num=0x00,
    )
    assert resp.hw_platform == 0x37
    assert resp.hw_variant == 0x17
    assert resp.fw_variant == 0x23
    assert resp.fw_build_week == 0x27


def test_intel_read_version_response_from_bytes():
    raw = bytes([0x00, 0x37, 0x17, 0x00, 0x23, 0x10, 0x00, 0x27, 0x19, 0x00])
    resp = IntelReadVersionResponse.from_bytes(raw)
    assert resp.status == 0x00
    assert resp.hw_platform == 0x37
    assert resp.fw_build_year == 0x19


def test_intel_read_version_response_roundtrip():
    original = IntelReadVersionResponse(
        status=0x00, hw_platform=0x37, hw_variant=0x17, hw_revision=0x01,
        fw_variant=0x06, fw_revision=0x20, fw_build_num=0x05,
        fw_build_week=0x30, fw_build_year=0x22, fw_patch_num=0x03,
    )
    raw = original.to_bytes()
    decoded = IntelReadVersionResponse.from_bytes(raw)
    assert decoded == original


# --- Realtek ---

def test_realtek_read_rom_version_opcode():
    assert HCI_VS_REALTEK_READ_ROM_VERSION == 0xFC6D


def test_realtek_write_firmware_opcode():
    assert HCI_VS_REALTEK_WRITE_FIRMWARE == 0xFC20


def test_realtek_opcodes_use_vendor_ogf():
    assert (HCI_VS_REALTEK_READ_ROM_VERSION >> 10) & 0x3F == int(OGF.VENDOR)


def test_realtek_rom_version_fields():
    rv = RealtekROMVersion(status=0x00, rom_version=0x000E)
    assert rv.status == 0x00
    assert rv.rom_version == 0x000E


def test_realtek_rom_version_from_bytes():
    raw = bytes([0x00, 0x0E, 0x00])
    rv = RealtekROMVersion.from_bytes(raw)
    assert rv.status == 0x00
    assert rv.rom_version == 0x000E


def test_realtek_rom_version_from_bytes_nonzero_status():
    raw = bytes([0x01, 0x00, 0x00])
    rv = RealtekROMVersion.from_bytes(raw)
    assert rv.status == 0x01
    assert rv.rom_version == 0x0000


def test_realtek_rom_version_roundtrip():
    original = RealtekROMVersion(status=0x00, rom_version=0x1234)
    raw = original.to_bytes()
    decoded = RealtekROMVersion.from_bytes(raw)
    assert decoded == original
