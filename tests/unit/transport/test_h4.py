import pytest

from pybluehost.transport.h4 import H4Framer


class TestH4FramerComplete:
    def test_hci_reset_command(self):
        # HCI_Reset: indicator 01, opcode 0C03, length 00
        packet = bytes.fromhex("01030c00")
        framer = H4Framer()
        out = list(framer.feed(packet))
        assert out == [packet]

    def test_command_complete_event(self):
        # Event 0x0E (Command Complete), length 04, payload 01 03 0C 00
        packet = bytes.fromhex("040e0401030c00")
        framer = H4Framer()
        out = list(framer.feed(packet))
        assert out == [packet]

    def test_acl_data_two_byte_length(self):
        # ACL: indicator 02, handle+flags 0x0001 LE, length 0x0004 LE, payload 4 bytes
        packet = bytes.fromhex("02010004000102030405")[:9]  # 1+4+4=9 bytes total
        # Build precisely:
        packet = bytes([0x02, 0x01, 0x00, 0x04, 0x00]) + bytes(range(4))
        framer = H4Framer()
        out = list(framer.feed(packet))
        assert out == [packet]


class TestH4FramerPartial:
    def test_bytes_split_across_feeds(self):
        packet = bytes.fromhex("01030c00")
        framer = H4Framer()
        assert list(framer.feed(packet[:1])) == []
        assert list(framer.feed(packet[1:3])) == []
        assert list(framer.feed(packet[3:])) == [packet]

    def test_one_byte_at_a_time(self):
        packet = bytes.fromhex("040e0401030c00")
        framer = H4Framer()
        emitted: list[bytes] = []
        for b in packet:
            emitted.extend(framer.feed(bytes([b])))
        assert emitted == [packet]


class TestH4FramerMulti:
    def test_two_packets_in_one_feed(self):
        p1 = bytes.fromhex("01030c00")
        p2 = bytes.fromhex("040e0401030c00")
        framer = H4Framer()
        out = list(framer.feed(p1 + p2))
        assert out == [p1, p2]

    def test_packet_plus_partial_next(self):
        p1 = bytes.fromhex("01030c00")
        p2 = bytes.fromhex("040e0401030c00")
        framer = H4Framer()
        out = list(framer.feed(p1 + p2[:3]))
        assert out == [p1]
        out2 = list(framer.feed(p2[3:]))
        assert out2 == [p2]


class TestH4FramerISO:
    def test_iso_data_masks_length_to_14_bits(self):
        # ISO: indicator 05, handle+flags 0x0001 LE, length 0xC008 LE (top 2 bits flags, low 14 = 0x0008)
        packet = bytes([0x05, 0x01, 0x00, 0x08, 0xC0]) + bytes(8)
        framer = H4Framer()
        out = list(framer.feed(packet))
        assert out == [packet]


class TestH4FramerErrors:
    def test_unknown_indicator_raises(self):
        framer = H4Framer()
        with pytest.raises(ValueError, match="Unknown H4 indicator"):
            list(framer.feed(b"\xFF\x00\x00"))
