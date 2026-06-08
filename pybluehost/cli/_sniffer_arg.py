"""Parse the --virtual-sniffer CLI argument into a SnifferSpec."""
from __future__ import annotations

from dataclasses import dataclass, field


_KNOWN_BACKENDS = frozenset({"ellisys", "wps"})


@dataclass(frozen=True)
class SnifferSpec:
    """Parsed --virtual-sniffer flag (see design spec §5.4)."""
    backend: str
    options: dict[str, str] = field(default_factory=dict)


def parse_sniffer_arg(arg: str) -> SnifferSpec:
    """Parse 'ellisys' | 'wps' | 'ellisys:k=v,k=v' | 'wps:k=v'.

    Raises ValueError for unknown backend, empty input, or malformed option.
    """
    if not arg:
        raise ValueError("--virtual-sniffer: empty value")
    if ":" in arg:
        backend, _, opts_str = arg.partition(":")
    else:
        backend, opts_str = arg, ""
    if backend not in _KNOWN_BACKENDS:
        raise ValueError(
            f"unknown sniffer backend '{backend}'; choose one of "
            f"{sorted(_KNOWN_BACKENDS)}"
        )
    options: dict[str, str] = {}
    if opts_str:
        for kv in opts_str.split(","):
            if "=" not in kv:
                raise ValueError(
                    f"--virtual-sniffer: malformed option '{kv}' (expected key=value)"
                )
            k, _, v = kv.partition("=")
            options[k.strip()] = v.strip()
    return SnifferSpec(backend=backend, options=options)
