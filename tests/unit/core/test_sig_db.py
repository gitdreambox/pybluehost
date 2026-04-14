from pathlib import Path

import pytest

from pybluehost.core.sig_db import SIGDatabase


@pytest.fixture
def sig_db() -> SIGDatabase:
    """Create a fresh SIGDatabase instance pointing at the real submodule data."""
    sig_root = Path(__file__).resolve().parents[3] / "pybluehost" / "lib" / "sig"
    if not sig_root.exists():
        pytest.skip("SIG submodule not initialized")
    return SIGDatabase(sig_root)


class TestServiceUUIDs:
    def test_service_name(self, sig_db: SIGDatabase):
        assert sig_db.service_name(0x1800) == "GAP"
        assert sig_db.service_name(0x180D) == "Heart Rate"

    def test_service_name_unknown(self, sig_db: SIGDatabase):
        assert sig_db.service_name(0xFFFF) is None

    def test_service_id(self, sig_db: SIGDatabase):
        result = sig_db.service_id(0x1800)
        assert result is not None
        assert "gap" in result.lower()


class TestCharacteristicUUIDs:
    def test_characteristic_name(self, sig_db: SIGDatabase):
        assert sig_db.characteristic_name(0x2A00) == "Device Name"
        assert sig_db.characteristic_name(0x2A37) == "Heart Rate Measurement"

    def test_characteristic_name_unknown(self, sig_db: SIGDatabase):
        assert sig_db.characteristic_name(0xFFFF) is None

    def test_characteristic_id(self, sig_db: SIGDatabase):
        result = sig_db.characteristic_id(0x2A00)
        assert result is not None
        assert "device_name" in result


class TestDescriptorUUIDs:
    def test_descriptor_name(self, sig_db: SIGDatabase):
        name = sig_db.descriptor_name(0x2900)
        assert name is not None
        assert "Extended Properties" in name

    def test_descriptor_name_unknown(self, sig_db: SIGDatabase):
        assert sig_db.descriptor_name(0xFFFF) is None


class TestUUIDByName:
    def test_find_service(self, sig_db: SIGDatabase):
        assert sig_db.uuid_by_name("Heart Rate") == 0x180D

    def test_find_characteristic(self, sig_db: SIGDatabase):
        assert sig_db.uuid_by_name("Device Name") == 0x2A00

    def test_not_found(self, sig_db: SIGDatabase):
        assert sig_db.uuid_by_name("Nonexistent Thing XYZ") is None


class TestCompanyID:
    def test_company_name(self, sig_db: SIGDatabase):
        name = sig_db.company_name(0x004C)
        assert name is not None
        assert "Apple" in name

    def test_company_name_unknown(self, sig_db: SIGDatabase):
        assert sig_db.company_name(0xFFFF) is None

    def test_company_id_by_name(self, sig_db: SIGDatabase):
        cid = sig_db.company_id_by_name("Apple")
        assert cid is not None
        assert cid == 0x004C


class TestADTypes:
    def test_ad_type_name(self, sig_db: SIGDatabase):
        assert sig_db.ad_type_name(0x01) == "Flags"

    def test_ad_type_name_unknown(self, sig_db: SIGDatabase):
        # 0xFE is not assigned in the SIG ad_types YAML
        assert sig_db.ad_type_name(0xFE) is None


class TestAppearance:
    def test_appearance_category(self, sig_db: SIGDatabase):
        name = sig_db.appearance_category(0x001)
        assert name is not None
        assert "Phone" in name

    def test_appearance_category_unknown(self, sig_db: SIGDatabase):
        assert sig_db.appearance_category(0xFFF) is None


class TestLazyLoading:
    def test_data_loaded_on_first_access(self, sig_db: SIGDatabase):
        assert sig_db._services is None
        sig_db.service_name(0x1800)
        assert sig_db._services is not None

    def test_second_access_uses_cache(self, sig_db: SIGDatabase):
        sig_db.service_name(0x1800)
        cached = sig_db._services
        sig_db.service_name(0x180D)
        assert sig_db._services is cached


class TestSingleton:
    def test_get_returns_singleton(self):
        SIGDatabase._instance = None
        a = SIGDatabase.get()
        b = SIGDatabase.get()
        assert a is b
        SIGDatabase._instance = None  # cleanup
