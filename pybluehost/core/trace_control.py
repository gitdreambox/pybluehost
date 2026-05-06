"""Parse and apply trace control specs from --trace / PYBLUEHOST_TRACE.

Spec syntax (comma-separated tokens):
  layer                -> layer at info level
  layer=info|debug     -> layer at explicit level
  *                    -> all layers info
  *=debug              -> all layers debug
  full-acl             -> include full ACL payload (no truncation)
  include=<EventName>  -> opt event(s) back into the suppress list
"""
from __future__ import annotations

from dataclasses import dataclass, field

_KNOWN_LAYERS = {
    "hci", "sm", "transport",
    "l2cap", "att", "gatt", "smp",
    "sdp", "rfcomm", "gap",
}
_VALID_LEVELS = {"info", "debug"}
_OPTION_PREFIXES = ("full-acl", "include=")


class InvalidTraceSpec(ValueError):
    """Raised when --trace / PYBLUEHOST_TRACE syntax is malformed."""


@dataclass
class TraceSpec:
    layers: dict[str, str] = field(default_factory=dict)
    full_acl: bool = False
    include: set[str] = field(default_factory=set)

    def is_empty(self) -> bool:
        return not self.layers and not self.full_acl and not self.include


def parse_trace_spec(s: str | None) -> TraceSpec:
    """Parse a trace spec string. Empty / None means disabled (returns empty TraceSpec)."""
    spec = TraceSpec()
    if not s or not s.strip():
        return spec

    for raw in s.split(","):
        token = raw.strip()
        if not token:
            continue
        if _is_option_token(token):
            _apply_option(spec, token)
        else:
            _apply_layer(spec, token)
    return spec


def _is_option_token(token: str) -> bool:
    return any(token == p or token.startswith(p) for p in _OPTION_PREFIXES)


def _apply_option(spec: TraceSpec, token: str) -> None:
    if token == "full-acl":
        spec.full_acl = True
        return
    if token.startswith("include="):
        value = token.split("=", 1)[1].strip()
        if not value:
            raise InvalidTraceSpec(f"Empty include= value in {token!r}")
        spec.include.add(value)
        return
    raise InvalidTraceSpec(f"Unknown trace option: {token!r}")


def _apply_layer(spec: TraceSpec, token: str) -> None:
    if "=" in token:
        layer, level = token.split("=", 1)
        layer = layer.strip()
        level = level.strip()
        # Tokens of the form "<key>=<value>" whose key is neither a wildcard
        # nor a known layer are treated as unknown trace options, not as
        # malformed layer specs.
        if layer != "*" and layer not in _KNOWN_LAYERS:
            raise InvalidTraceSpec(f"Unknown trace option: {token!r}")
    else:
        layer, level = token, "info"

    if level not in _VALID_LEVELS:
        raise InvalidTraceSpec(f"Invalid level: {level!r} (must be info or debug)")

    if layer == "*":
        for name in _KNOWN_LAYERS:
            spec.layers[name] = level
        return
    if layer not in _KNOWN_LAYERS:
        raise InvalidTraceSpec(f"Unknown layer: {layer!r}")
    spec.layers[layer] = level


import logging

# Maps trace-spec layer names to their stdlib logger names.
_LAYER_LOGGER: dict[str, str] = {
    "hci": "pybluehost.hci",
    "sm": "pybluehost.core.statemachine",
    "transport": "pybluehost.transport",
    "l2cap": "pybluehost.l2cap",
    "att": "pybluehost.ble.att",
    "gatt": "pybluehost.ble.gatt",
    "smp": "pybluehost.ble.smp",
    "sdp": "pybluehost.classic.sdp",
    "rfcomm": "pybluehost.classic.rfcomm",
    "gap": "pybluehost.classic.gap",
}

_LEVEL_TO_LOGGING: dict[str, int] = {
    "info": logging.INFO,
    "debug": logging.DEBUG,
}


def apply_logging_levels(spec: TraceSpec) -> None:
    """Adjust stdlib logger levels per the spec.

    Idempotent: calling with the same spec twice has the same effect.
    Layers not mentioned in the spec are left untouched.
    """
    for layer, level in spec.layers.items():
        logger_name = _LAYER_LOGGER.get(layer)
        if logger_name is None:
            continue  # parse_trace_spec already validated; defensive only
        logging.getLogger(logger_name).setLevel(_LEVEL_TO_LOGGING[level])


def attach_console_sink(
    spec: TraceSpec,
    trace_system,
    *,
    stream=None,
):
    """Attach a ConsoleSink to trace_system if the spec enables the hci layer.

    Returns the new sink (so caller can keep a reference) or None when no
    sink was attached (hci layer absent or stream unavailable).
    """
    from pybluehost.core.trace_console import ConsoleSink

    hci_level = spec.layers.get("hci")
    if hci_level is None:
        return None
    sink = ConsoleSink(
        stream=stream,
        level=hci_level,
        full_acl=spec.full_acl,
        include=set(spec.include),
    )
    trace_system.add_sink(sink)
    return sink


def trace_install(spec: TraceSpec, trace_system, *, stream=None):
    """One-shot install: apply logging levels + attach ConsoleSink."""
    apply_logging_levels(spec)
    return attach_console_sink(spec, trace_system, stream=stream)
