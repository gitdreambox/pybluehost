"""Parse the --virtual-sniffer CLI argument into a SnifferSpec.

The dataclass and pure-parsing logic now live in pybluehost.sniffer.spec.
This module re-exports them for backwards compatibility and keeps the CLI
layer as the owner of anything that touches argparse.
"""
from pybluehost.sniffer.spec import SnifferSpec, parse_sniffer_arg  # re-export for back-compat

__all__ = ["SnifferSpec", "parse_sniffer_arg"]
