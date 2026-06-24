"""PyBlueHost - Python Bluetooth Host Stack."""

# SINGLE SOURCE OF TRUTH for the package version.
# pyproject.toml's `[tool.hatch.version]` reads from this file at build time,
# so editing here updates both `pip show pybluehost` and
# `pybluehost.__version__`. After real-hardware verification is complete,
# bump to "1.0.0" (or whatever the release milestone uses).
__version__ = "0.99"

from pybluehost.stack import Stack, StackConfig, StackMode

__all__ = ["Stack", "StackConfig", "StackMode"]
