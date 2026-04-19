import struct
from pybluehost.l2cap.sar import Reassembler, Segmenter
from pybluehost.l2cap.constants import CID_ATT, CID_LE_SIGNALING, CID_SMP
from pybluehost.hci.constants import ACL_PB_FIRST_AUTO_FLUSH, ACL_PB_CONTINUING

def test_constants():
    assert CID_ATT == 0x0004
    assert CID_LE_SIGNALING == 0x0005
    assert CID_SMP == 0x0006

def test_single_fragment_reassembly():
    r = Reassembler()
    # L2CAP header: length=5, CID=0x0004 (ATT), then 5 bytes payload
    data = struct.pack("<HH", 5, CID_ATT) + b"\x01\x02\x03\x04\x05"
    result = r.feed(handle=0x0040, pb_flag=ACL_PB_FIRST_AUTO_FLUSH, data=data)
    assert result == (CID_ATT, b"\x01\x02\x03\x04\x05")

def test_multi_fragment_reassembly():
    r = Reassembler()
    # First fragment: L2CAP header says total payload = 6, but only 3 bytes of payload here
    first = struct.pack("<HH", 6, CID_ATT) + b"\x01\x02\x03"
    result = r.feed(handle=0x0001, pb_flag=ACL_PB_FIRST_AUTO_FLUSH, data=first)
    assert result is None  # incomplete

    cont = b"\x04\x05\x06"
    result = r.feed(handle=0x0001, pb_flag=ACL_PB_CONTINUING, data=cont)
    assert result == (CID_ATT, b"\x01\x02\x03\x04\x05\x06")

def test_reassembler_reset_on_new_start():
    r = Reassembler()
    partial = struct.pack("<HH", 6, CID_ATT) + b"\x01\x02"
    r.feed(handle=0x0001, pb_flag=ACL_PB_FIRST_AUTO_FLUSH, data=partial)
    # New start packet resets state
    complete = struct.pack("<HH", 3, CID_ATT) + b"\xAA\xBB\xCC"
    result = r.feed(handle=0x0001, pb_flag=ACL_PB_FIRST_AUTO_FLUSH, data=complete)
    assert result == (CID_ATT, b"\xAA\xBB\xCC")

def test_multi_handle_isolation():
    """Two handles reassemble independently."""
    r = Reassembler()
    # Handle A: first fragment (incomplete)
    a_first = struct.pack("<HH", 4, CID_ATT) + b"\x01\x02"
    assert r.feed(handle=0x0001, pb_flag=ACL_PB_FIRST_AUTO_FLUSH, data=a_first) is None

    # Handle B: complete in one fragment
    b_data = struct.pack("<HH", 2, CID_SMP) + b"\xAA\xBB"
    result_b = r.feed(handle=0x0002, pb_flag=ACL_PB_FIRST_AUTO_FLUSH, data=b_data)
    assert result_b == (CID_SMP, b"\xAA\xBB")

    # Handle A: continuation
    result_a = r.feed(handle=0x0001, pb_flag=ACL_PB_CONTINUING, data=b"\x03\x04")
    assert result_a == (CID_ATT, b"\x01\x02\x03\x04")

def test_segmenter_single():
    s = Segmenter(max_size=251)
    pdu = struct.pack("<HH", 10, CID_ATT) + b"A" * 10
    segments = s.segment(pdu)
    assert len(segments) == 1
    pb, payload = segments[0]
    assert pb == ACL_PB_FIRST_AUTO_FLUSH
    assert payload == pdu

def test_segmenter_multi():
    s = Segmenter(max_size=8)
    pdu = b"X" * 20
    segments = s.segment(pdu)
    assert len(segments) == 3  # ceil(20/8)
    assert segments[0][0] == ACL_PB_FIRST_AUTO_FLUSH
    for pb, payload in segments[1:]:
        assert pb == ACL_PB_CONTINUING
    # Concatenating payloads should give original
    reconstructed = b"".join(p for _, p in segments)
    assert reconstructed == pdu

def test_segmenter_exact_multiple():
    s = Segmenter(max_size=5)
    pdu = b"Y" * 10
    segments = s.segment(pdu)
    assert len(segments) == 2
    assert all(len(p) == 5 for _, p in segments)
