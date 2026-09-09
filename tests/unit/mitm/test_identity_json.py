"""Identity JSON: save/load, per-section merge, round-trip with ClonedIdentity."""
import json

from pybluehost.cli.app.mitm.cli import identity_load, identity_save
from pybluehost.cli.app.mitm.recon import ClonedIdentity

BR = ClonedIdentity(address="38:D5:18:CD:52:F7", address_type=0, adv_data=b"\x01\x02",
                    scan_response=b"", name="JBL", class_of_device=0x240404)
LE = ClonedIdentity(address="38:D5:18:CD:52:F8", address_type=1, adv_data=b"\x03",
                    scan_response=b"\x04", name="JBL LE", class_of_device=None)


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "t.json"
    identity_save(path, {"bredr": BR, "le": LE})
    loaded = identity_load(path)
    assert set(loaded) == {"bredr", "le"}
    assert loaded["bredr"].address == "38:D5:18:CD:52:F7"
    assert loaded["bredr"].class_of_device == 0x240404
    assert loaded["bredr"].adv_data == b"\x01\x02"
    assert loaded["le"].address_type == 1
    assert loaded["le"].scan_response == b"\x04"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == 1 and "saved_at" in raw


def test_save_merges_by_section(tmp_path):
    """A bredr-only save must not wipe the existing le section in the file."""
    path = tmp_path / "t.json"
    identity_save(path, {"bredr": BR})
    identity_save(path, {"le": LE})
    loaded = identity_load(path)
    assert set(loaded) == {"bredr", "le"}
    assert loaded["bredr"].name == "JBL"


def test_load_missing_file_returns_empty(tmp_path):
    assert identity_load(tmp_path / "nope.json") == {}


def test_load_valid_json_non_dict_returns_empty(tmp_path):
    path = tmp_path / "t.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert identity_load(path) == {}


def test_load_corrupt_file_returns_empty(tmp_path):
    path = tmp_path / "t.json"
    path.write_text("not json{", encoding="utf-8")
    assert identity_load(path) == {}
