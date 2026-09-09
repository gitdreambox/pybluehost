"""LE LTK JSONL persistence; shares the same file format as SspTermination's link-key JSONL."""
import json

from pybluehost.cli.app.mitm.pairing.ltk_store import append_ltk, load_ltks


def test_append_then_load_roundtrip(tmp_path):
    path = tmp_path / "k.jsonl"
    append_ltk(path, side="phone", addr="AA:BB:CC:DD:EE:FF", ltk=b"\x11" * 16)
    append_ltk(path, side="target", addr="38:D5:18:CD:52:F7", ltk=b"\x22" * 16)
    ltks = load_ltks(path)
    assert ltks[("phone", "AA:BB:CC:DD:EE:FF")] == b"\x11" * 16
    assert ltks[("target", "38:D5:18:CD:52:F7")] == b"\x22" * 16


def test_load_mixed_file_ignores_ssp_link_key_records(tmp_path):
    """link_key records written by SspTermination in the same file must not make load raise or mix in."""
    path = tmp_path / "k.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "t", "side": "phone", "addr": "AA:BB",
                            "link_key": "00" * 16, "key_type": 0x05}) + "\n")
        f.write(json.dumps({"type": "ltk", "side": "phone",
                            "addr": "AA:BB", "ltk": "11" * 16}) + "\n")
    ltks = load_ltks(path)
    assert ltks == {("phone", "AA:BB"): b"\x11" * 16}


def test_load_skips_non_dict_json_lines(tmp_path):
    path = tmp_path / "k.jsonl"
    path.write_text('42\n[1, 2]\n' + json.dumps({"type": "ltk", "side": "phone",
                                                 "addr": "AA:BB", "ltk": "11" * 16}) + "\n",
                    encoding="utf-8")
    assert load_ltks(path) == {("phone", "AA:BB"): b"\x11" * 16}


def test_load_missing_and_corrupt(tmp_path):
    assert load_ltks(tmp_path / "nope.jsonl") == {}
    p = tmp_path / "bad.jsonl"
    p.write_text("garbage line\n", encoding="utf-8")
    assert load_ltks(p) == {}
