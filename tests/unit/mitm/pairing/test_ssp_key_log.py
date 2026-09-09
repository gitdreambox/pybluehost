"""T4: unit tests for SSP link key JSONL persistence."""
from __future__ import annotations

import json

from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate
from pybluehost.cli.app.mitm.pairing.ssp import SspTermination
from pybluehost.core.address import BDAddress


class _NullController:
    def on_io_capability_request(self, cb): pass
    def on_user_confirmation_request(self, cb): pass
    def on_link_key_notification(self, cb): pass
    def on_link_key_request(self, cb): pass


def _addr():
    return BDAddress.from_string("98:1D:F9:90:11:1E")


def test_link_key_written_as_jsonl(tmp_path):
    log = tmp_path / "keys.jsonl"
    ssp = SspTermination(_NullController(), delegate=AutoConfirmDelegate(),
                         side_name="target", key_log_path=log)
    key = bytes(range(16))
    ssp._on_lkn(_addr(), key, 0x04)
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["side"] == "target"
    assert rec["addr"] == "98:1D:F9:90:11:1E"
    assert rec["link_key"] == key.hex()
    assert rec["key_type"] == 0x04
    assert "ts" in rec


def test_no_log_path_no_file_io(tmp_path):
    ssp = SspTermination(_NullController(), delegate=AutoConfirmDelegate(), side_name="phone")
    ssp._on_lkn(_addr(), bytes(16), 0x04)  # just must not raise
    assert list(tmp_path.iterdir()) == []


def test_both_sides_append_same_file(tmp_path):
    log = tmp_path / "keys.jsonl"
    a = SspTermination(_NullController(), delegate=AutoConfirmDelegate(),
                       side_name="phone", key_log_path=log)
    b = SspTermination(_NullController(), delegate=AutoConfirmDelegate(),
                       side_name="target", key_log_path=log)
    a._on_lkn(_addr(), b"\x01" * 16, 0x04)
    b._on_lkn(_addr(), b"\x02" * 16, 0x04)
    sides = [json.loads(l)["side"] for l in log.read_text().strip().splitlines()]
    assert sides == ["phone", "target"]


def test_lkn_survives_missing_log_dir(tmp_path):
    log = tmp_path / "nonexistent" / "keys.jsonl"
    ssp = SspTermination(_NullController(), delegate=AutoConfirmDelegate(),
                         side_name="phone", key_log_path=log)
    key = bytes(16)
    ssp._on_lkn(_addr(), key, 0x04)
    # write failure must not propagate; the in-memory record must still be written
    assert ssp._link_keys[str(_addr())] == key
    assert not log.exists()


def test_load_keys_skips_non_dict_json_lines(tmp_path):
    log = tmp_path / "keys.jsonl"
    key = bytes(range(16))
    log.write_text('42\n[1, 2]\n' + json.dumps({
        "ts": "t", "side": "phone", "addr": "98:1D:F9:90:11:1E",
        "link_key": key.hex(), "key_type": 0x04}) + "\n", encoding="utf-8")
    ssp = SspTermination(_NullController(), delegate=AutoConfirmDelegate(),
                         side_name="phone", key_log_path=log)
    assert ssp._link_keys == {"98:1D:F9:90:11:1E": key}


# ============================================================ forget_key group
# Self-healing after authentication failure (earbud-side bond expired, key
# mismatch 0x05): the local key is invalidated as well, so the next round
# re-runs SSP as unpaired; SSP records for the same address are deleted from
# the JSONL while other records are kept as-is.
def test_forget_key_removes_record_and_rewrites_file(tmp_path):
    log = tmp_path / "keys.jsonl"
    addr_a = "98:1D:F9:90:11:1E"
    addr_b = "11:22:33:44:55:66"
    ssp_a = json.dumps({"ts": "t1", "side": "target", "addr": addr_a,
                        "link_key": bytes(16).hex(), "key_type": 0x04})
    ssp_b = json.dumps({"ts": "t2", "side": "phone", "addr": addr_b,
                        "link_key": (b"\x01" * 16).hex(), "key_type": 0x03})
    # LTK record for the same address: must be kept as-is even when addr matches (type=="ltk" untouched)
    ltk_a = json.dumps({"ts": "t3", "type": "ltk", "side": "target",
                        "addr": addr_a, "ltk": (b"\x02" * 16).hex()})
    log.write_text("\n".join([ssp_a, ssp_b, ltk_a]) + "\n", encoding="utf-8")
    ssp = SspTermination(_NullController(), delegate=AutoConfirmDelegate(),
                         side_name="target", key_log_path=log)
    assert addr_a in ssp._link_keys and addr_b in ssp._link_keys

    ssp.forget_key(addr_a.lower())  # case-insensitive

    # in memory: A removed, B kept
    assert addr_a not in ssp._link_keys
    assert ssp._link_keys[addr_b] == b"\x01" * 16
    # file: after rewrite no A SSP record; B's SSP record and A's ltk record kept in original order
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    recs = [json.loads(l) for l in lines]
    assert len(recs) == 2
    assert recs[0]["addr"] == addr_b and recs[0]["link_key"] == (b"\x01" * 16).hex()
    assert recs[1]["type"] == "ltk" and recs[1]["addr"] == addr_a


def test_forget_key_no_matching_record_leaves_file_untouched(tmp_path):
    log = tmp_path / "keys.jsonl"
    addr_b = "11:22:33:44:55:66"
    content = json.dumps({"ts": "t", "side": "phone", "addr": addr_b,
                          "link_key": bytes(16).hex(), "key_type": 0x03}) + "\n"
    log.write_text(content, encoding="utf-8")
    ssp = SspTermination(_NullController(), delegate=AutoConfirmDelegate(),
                         side_name="target", key_log_path=log)
    ssp.forget_key("98:1D:F9:90:11:1E")  # this address is not in the file
    assert log.read_text(encoding="utf-8") == content  # file not rewritten


def test_forget_key_without_log_path_memory_only():
    ssp = SspTermination(_NullController(), delegate=AutoConfirmDelegate(),
                         side_name="target")  # no key_log_path
    ssp._link_keys["98:1D:F9:90:11:1E"] = bytes(16)
    ssp.forget_key("98:1d:f9:90:11:1e")
    assert ssp._link_keys == {}
