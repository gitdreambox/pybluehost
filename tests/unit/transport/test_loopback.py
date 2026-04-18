import pytest

from pybluehost.transport.loopback import LoopbackTransport


class _Collect:
    def __init__(self) -> None:
        self.received: list[bytes] = []

    async def on_transport_data(self, data: bytes) -> None:
        self.received.append(data)


class TestLoopbackPair:
    @pytest.mark.asyncio
    async def test_pair_delivers_bytes_to_peer(self):
        a, b = LoopbackTransport.pair()
        sink_b = _Collect()
        b.set_sink(sink_b)
        await a.open()
        await b.open()
        await a.send(b"\x01\x03\x0c\x00")
        assert sink_b.received == [b"\x01\x03\x0c\x00"]

    @pytest.mark.asyncio
    async def test_pair_is_bidirectional(self):
        a, b = LoopbackTransport.pair()
        sink_a, sink_b = _Collect(), _Collect()
        a.set_sink(sink_a)
        b.set_sink(sink_b)
        await a.open()
        await b.open()
        await a.send(b"A")
        await b.send(b"B")
        assert sink_a.received == [b"B"]
        assert sink_b.received == [b"A"]

    @pytest.mark.asyncio
    async def test_send_when_closed_raises(self):
        a, b = LoopbackTransport.pair()
        await b.open()
        # a not opened
        with pytest.raises(RuntimeError, match="not open"):
            await a.send(b"X")

    @pytest.mark.asyncio
    async def test_send_when_peer_closed_is_dropped(self):
        a, b = LoopbackTransport.pair()
        sink_b = _Collect()
        b.set_sink(sink_b)
        await a.open()
        # b not opened → send from a is dropped silently
        await a.send(b"X")
        assert sink_b.received == []

    @pytest.mark.asyncio
    async def test_info(self):
        a, _ = LoopbackTransport.pair()
        assert a.info.type == "loopback"
        assert a.info.platform == "any"

    @pytest.mark.asyncio
    async def test_solo_instance_has_no_peer(self):
        solo = LoopbackTransport()
        await solo.open()
        with pytest.raises(RuntimeError, match="peer"):
            await solo.send(b"X")
