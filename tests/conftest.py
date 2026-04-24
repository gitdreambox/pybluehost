"""Shared pytest fixtures for PyBlueHost test suite."""
import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers so --strict-markers doesn't complain."""
    # Markers are already declared in pyproject.toml; this hook is for
    # programmatic registration if pyproject.toml is not loaded.
    pass
