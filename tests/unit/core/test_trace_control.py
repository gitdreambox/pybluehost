"""Tests for trace spec parser (--trace / PYBLUEHOST_TRACE)."""
from __future__ import annotations

import pytest

from pybluehost.core.trace_control import (
    InvalidTraceSpec,
    TraceSpec,
    parse_trace_spec,
)


def test_empty_spec_disables_everything():
    spec = parse_trace_spec("")
    assert spec.layers == {}
    assert spec.full_acl is False
    assert spec.include == set()


def test_none_disables_everything():
    spec = parse_trace_spec(None)
    assert spec.layers == {}


def test_single_layer_default_info():
    spec = parse_trace_spec("hci")
    assert spec.layers == {"hci": "info"}


def test_layer_with_explicit_level():
    spec = parse_trace_spec("hci=debug")
    assert spec.layers == {"hci": "debug"}


def test_multiple_layers_independent_levels():
    spec = parse_trace_spec("hci,l2cap=debug,sm")
    assert spec.layers == {"hci": "info", "l2cap": "debug", "sm": "info"}


def test_wildcard_expands_to_all_layers_info():
    spec = parse_trace_spec("*")
    assert "hci" in spec.layers and spec.layers["hci"] == "info"
    assert "l2cap" in spec.layers
    assert "smp" in spec.layers


def test_wildcard_debug():
    spec = parse_trace_spec("*=debug")
    assert all(level == "debug" for level in spec.layers.values())


def test_full_acl_option():
    spec = parse_trace_spec("hci,full-acl")
    assert spec.layers == {"hci": "info"}
    assert spec.full_acl is True


def test_include_option():
    spec = parse_trace_spec("hci,include=Number_Of_Completed_Packets")
    assert spec.include == {"Number_Of_Completed_Packets"}


def test_invalid_layer_raises():
    with pytest.raises(InvalidTraceSpec, match="Unknown layer"):
        parse_trace_spec("invalid_layer")


def test_invalid_level_raises():
    with pytest.raises(InvalidTraceSpec, match="Invalid level"):
        parse_trace_spec("hci=loud")


def test_unknown_option_raises():
    with pytest.raises(InvalidTraceSpec, match="Unknown trace option"):
        parse_trace_spec("hci,extra=garbage")


def test_apply_logging_levels_sets_layer_logger_to_info():
    import logging

    from pybluehost.core.trace_control import apply_logging_levels, parse_trace_spec

    apply_logging_levels(parse_trace_spec("l2cap"))
    assert logging.getLogger("pybluehost.l2cap").level == logging.INFO


def test_apply_logging_levels_sets_layer_logger_to_debug():
    import logging

    from pybluehost.core.trace_control import apply_logging_levels, parse_trace_spec

    apply_logging_levels(parse_trace_spec("smp=debug"))
    assert logging.getLogger("pybluehost.ble.smp").level == logging.DEBUG


def test_apply_logging_levels_empty_spec_does_not_change_levels():
    import logging

    from pybluehost.core.trace_control import apply_logging_levels, parse_trace_spec

    logger = logging.getLogger("pybluehost.gatt")
    logger.setLevel(logging.WARNING)
    apply_logging_levels(parse_trace_spec(""))
    assert logger.level == logging.WARNING


@pytest.mark.asyncio
async def test_attach_console_sink_only_when_hci_layer_enabled():
    import io

    from pybluehost.core.trace import TraceSystem
    from pybluehost.core.trace_control import (
        attach_console_sink,
        parse_trace_spec,
    )

    trace_system = TraceSystem()
    sink = attach_console_sink(parse_trace_spec("hci"), trace_system, stream=io.StringIO())
    assert sink is not None
    assert sink in trace_system._sinks


@pytest.mark.asyncio
async def test_attach_console_sink_returns_none_when_hci_layer_absent():
    import io

    from pybluehost.core.trace import TraceSystem
    from pybluehost.core.trace_control import (
        attach_console_sink,
        parse_trace_spec,
    )

    trace_system = TraceSystem()
    sink = attach_console_sink(parse_trace_spec("l2cap"), trace_system, stream=io.StringIO())
    assert sink is None
    assert trace_system._sinks == []


@pytest.mark.asyncio
async def test_attach_console_sink_passes_full_acl_and_include():
    import io

    from pybluehost.core.trace import TraceSystem
    from pybluehost.core.trace_control import (
        attach_console_sink,
        parse_trace_spec,
    )

    trace_system = TraceSystem()
    sink = attach_console_sink(
        parse_trace_spec("hci,full-acl,include=Number_Of_Completed_Packets"),
        trace_system,
        stream=io.StringIO(),
    )
    assert sink._full_acl is True
    assert "Number_Of_Completed_Packets" in sink._include
