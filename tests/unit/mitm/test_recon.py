from pybluehost.cli.app.mitm.recon import ClonedIdentity, parse_adv_name


def test_parse_complete_local_name():
    adv = bytes([0x02, 0x01, 0x06,
                 0x06, 0x09, ord("W"), ord("a"), ord("t"), ord("c"), ord("h")])
    assert parse_adv_name(adv) == "Watch"


def test_parse_adv_name_absent():
    adv = bytes([0x02, 0x01, 0x06])
    assert parse_adv_name(adv) is None


def test_parse_short_name():
    adv = bytes([0x04, 0x08, ord("A"), ord("B"), ord("C")])  # 0x08 = shortened name
    assert parse_adv_name(adv) == "ABC"


def test_cloned_identity_holds_fields():
    cid = ClonedIdentity(address="AA:BB:CC:DD:EE:FF", address_type=0,
                         adv_data=b"\x02\x01\x06", scan_response=b"", name="Watch")
    assert cid.name == "Watch"
    assert cid.adv_data == b"\x02\x01\x06"
