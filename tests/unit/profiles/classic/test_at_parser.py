import pytest

from pybluehost.profiles.classic._at_parser import (
    ATCommand, ATResponse, ATUnsolicited,
    parse_at_line, format_at_command, format_at_response, format_unsolicited,
    ATLineBuffer,
)


def test_parse_command_action():
    msg = parse_at_line("AT+BRSF=1023")
    assert isinstance(msg, ATCommand)
    assert msg.name == "+BRSF"
    assert msg.kind == "set"
    assert msg.args == ["1023"]


def test_parse_command_test():
    msg = parse_at_line("AT+CIND=?")
    assert isinstance(msg, ATCommand)
    assert msg.kind == "test"
    assert msg.args == []


def test_parse_command_read():
    msg = parse_at_line("AT+CIND?")
    assert isinstance(msg, ATCommand)
    assert msg.kind == "read"


def test_parse_command_action_no_args():
    msg = parse_at_line("ATA")
    assert isinstance(msg, ATCommand)
    assert msg.name == "A"
    assert msg.kind == "action"
    assert msg.args == []


def test_parse_response_with_args():
    msg = parse_at_line("+BRSF: 871")
    assert isinstance(msg, ATResponse)
    assert msg.name == "+BRSF"
    assert msg.args == ["871"]


def test_parse_ok_response():
    msg = parse_at_line("OK")
    assert isinstance(msg, ATResponse)
    assert msg.name == "OK"
    assert msg.is_terminator is True


def test_parse_error_response():
    msg = parse_at_line("ERROR")
    assert isinstance(msg, ATResponse)
    assert msg.name == "ERROR"
    assert msg.is_terminator is True


def test_parse_ring_unsolicited():
    msg = parse_at_line("RING")
    assert isinstance(msg, ATUnsolicited)
    assert msg.name == "RING"


def test_parse_ciev_unsolicited():
    msg = parse_at_line("+CIEV: 1,1")
    assert isinstance(msg, ATUnsolicited)
    assert msg.name == "+CIEV"
    assert msg.args == ["1", "1"]


def test_parse_clip_with_quoted_string():
    msg = parse_at_line('+CLIP: "+8613800138000",129')
    assert isinstance(msg, ATUnsolicited)
    assert msg.name == "+CLIP"
    assert msg.args == ['"+8613800138000"', "129"]


def test_format_at_command_set():
    cmd = ATCommand(name="+BAC", kind="set", args=["1", "2"])
    assert format_at_command(cmd) == "AT+BAC=1,2\r"


def test_format_at_command_action():
    cmd = ATCommand(name="A", kind="action", args=[])
    assert format_at_command(cmd) == "ATA\r"


def test_format_at_response_with_args():
    resp = ATResponse(name="+BRSF", args=["871"])
    assert format_at_response(resp) == "\r\n+BRSF: 871\r\n"


def test_format_at_response_terminator():
    resp = ATResponse(name="OK", args=[], is_terminator=True)
    assert format_at_response(resp) == "\r\nOK\r\n"


def test_format_unsolicited():
    msg = ATUnsolicited(name="RING", args=[])
    assert format_unsolicited(msg) == "\r\nRING\r\n"


def test_line_buffer_emits_complete_lines():
    buf = ATLineBuffer()
    buf.feed(b"AT+BRSF=1023\rAT+B")
    lines = buf.drain()
    assert lines == ["AT+BRSF=1023"]
    buf.feed(b"AC=1,2\r")
    assert buf.drain() == ["AT+BAC=1,2"]


def test_line_buffer_handles_crlf_response_pairs():
    buf = ATLineBuffer()
    buf.feed(b"\r\n+BRSF: 871\r\n\r\nOK\r\n")
    assert buf.drain() == ["+BRSF: 871", "OK"]
