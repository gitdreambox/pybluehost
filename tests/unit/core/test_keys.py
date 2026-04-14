import pytest
from pybluehost.core.keys import LinkKey, LTK, IRK, CSRK, LinkKeyType


class TestLinkKey:
    def test_create(self):
        key = LinkKey(value=bytes(16), key_type=LinkKeyType.AUTHENTICATED_P256)
        assert len(key.value) == 16
        assert key.key_type == LinkKeyType.AUTHENTICATED_P256

    def test_wrong_length(self):
        with pytest.raises(ValueError, match="16 bytes"):
            LinkKey(value=bytes(10), key_type=LinkKeyType.UNAUTHENTICATED_P192)


class TestLTK:
    def test_create(self):
        ltk = LTK(value=bytes(16), ediv=0x1234, rand=0xABCD)
        assert ltk.ediv == 0x1234
        assert ltk.rand == 0xABCD
        assert ltk.key_size == 16

    def test_custom_key_size(self):
        ltk = LTK(value=bytes(16), ediv=0, rand=0, key_size=7)
        assert ltk.key_size == 7

    def test_wrong_length(self):
        with pytest.raises(ValueError, match="16 bytes"):
            LTK(value=bytes(8), ediv=0, rand=0)


class TestIRK:
    def test_create(self):
        irk = IRK(value=bytes(16))
        assert len(irk.value) == 16

    def test_wrong_length(self):
        with pytest.raises(ValueError, match="16 bytes"):
            IRK(value=bytes(4))


class TestCSRK:
    def test_create(self):
        csrk = CSRK(value=bytes(16))
        assert len(csrk.value) == 16

    def test_wrong_length(self):
        with pytest.raises(ValueError, match="16 bytes"):
            CSRK(value=bytes(20))
