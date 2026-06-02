from pybluehost.cli.app.mitm.pairing import smp_pdu as P


def test_opcodes():
    assert P.PAIRING_REQUEST == 0x01
    assert P.PAIRING_RESPONSE == 0x02
    assert P.PAIRING_CONFIRM == 0x03
    assert P.PAIRING_RANDOM == 0x04
    assert P.PAIRING_PUBLIC_KEY == 0x0C
    assert P.PAIRING_DHKEY_CHECK == 0x0D


def test_pairing_request_roundtrip():
    body = bytes([0x03, 0x00, 0x09, 0x10, 0x00, 0x00])
    pdu = P.encode(P.PAIRING_REQUEST, body)
    assert pdu == bytes([0x01]) + body
    op, payload = P.decode(pdu)
    assert op == P.PAIRING_REQUEST
    assert payload == body


def test_public_key_pdu_is_65_bytes():
    pk = bytes(range(64))
    pdu = P.encode(P.PAIRING_PUBLIC_KEY, pk)
    assert len(pdu) == 65
    assert pdu[0] == P.PAIRING_PUBLIC_KEY
