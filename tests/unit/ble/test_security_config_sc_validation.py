"""SecurityConfig.enable_secure_connections + _validate_sc_dependencies."""
from __future__ import annotations

import pytest

from pybluehost.ble.security import SecurityConfig, _validate_sc_dependencies
from pybluehost.core.errors import ConfigurationError


def test_enable_secure_connections_defaults_false():
    cfg = SecurityConfig()
    assert cfg.enable_secure_connections is False


def test_enable_secure_connections_overrideable():
    cfg = SecurityConfig(enable_secure_connections=True)
    assert cfg.enable_secure_connections is True


def test_validation_passes_with_sc_off_and_no_dependents():
    cfg = SecurityConfig(enable_secure_connections=False, ctkd_enable=False)
    _validate_sc_dependencies(cfg)


def test_validation_passes_with_sc_on_and_ctkd():
    cfg = SecurityConfig(enable_secure_connections=True, ctkd_enable=True)
    _validate_sc_dependencies(cfg)


def test_validation_blocks_ctkd_without_sc():
    cfg = SecurityConfig(enable_secure_connections=False, ctkd_enable=True)
    with pytest.raises(ConfigurationError, match="CTKD"):
        _validate_sc_dependencies(cfg)
