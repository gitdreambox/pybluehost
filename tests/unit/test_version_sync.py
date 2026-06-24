"""Lock pybluehost.__version__ to what's installed (which Hatch reads from
the same __init__.py at build time). Catches the case where someone manually
adds a hardcoded ``version = "..."`` line back into ``pyproject.toml``."""
from __future__ import annotations

import pathlib
import re

import pybluehost


def test_init_version_matches_installed_metadata():
    """Whatever `pip` sees must equal pybluehost.__version__."""
    try:
        from importlib import metadata
    except ImportError:  # pragma: no cover
        import importlib_metadata as metadata  # type: ignore[no-redef]

    installed = metadata.version("pybluehost")
    assert installed == pybluehost.__version__, (
        f"version drift: pip says {installed!r}, "
        f"pybluehost.__version__ = {pybluehost.__version__!r}. "
        "Both should be edited via pybluehost/__init__.py (single source)."
    )


def test_pyproject_does_not_hardcode_version():
    """pyproject.toml must keep `dynamic = ["version"]` — no hardcoded value."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    pp = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    # Capture only the [project] table so we don't false-match on tool-table
    # `version = ...` lines later in the file.
    # Capture the [project] table up to the next TOML table header (`\n[`).
    # Plain `[^\[]` breaks on inline arrays like `["version"]`.
    project_block = re.search(
        r"^\[project\]\n(.*?)(?=\n\[)", pp, flags=re.MULTILINE | re.DOTALL,
    )
    assert project_block is not None, "no [project] table found in pyproject.toml"
    block = project_block.group(0)
    assert "dynamic" in block and "version" in block, (
        "pyproject.toml [project] should list version as dynamic; "
        "edit pybluehost/__init__.py to bump"
    )
    # If someone reintroduced a hardcoded `version = "..."` line, fail loud.
    hardcoded = re.search(r"^version\s*=\s*\"", block, flags=re.MULTILINE)
    assert hardcoded is None, (
        f"pyproject.toml [project] has a hardcoded version line: {hardcoded.group(0)!r}. "
        "Remove it — version is dynamic, read from pybluehost/__init__.py."
    )
