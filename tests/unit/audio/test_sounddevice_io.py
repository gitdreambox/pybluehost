import pytest

from pybluehost.audio._sounddevice_io import (
    SoundDeviceUnavailable, is_available,
)


def test_is_available_returns_bool():
    assert isinstance(is_available(), bool)


def test_unavailable_raises_on_input_construction(monkeypatch):
    """If sounddevice can't be imported, AudioInputDevice raises immediately."""
    import pybluehost.audio._sounddevice_io as sdio

    monkeypatch.setattr(sdio, "_sounddevice", None)
    monkeypatch.setattr(sdio, "_sounddevice_import_attempted", True)
    with pytest.raises(SoundDeviceUnavailable):
        sdio.AudioInputDevice(sample_rate=8000, channels=1)


def test_unavailable_raises_on_output_construction(monkeypatch):
    import pybluehost.audio._sounddevice_io as sdio

    monkeypatch.setattr(sdio, "_sounddevice", None)
    monkeypatch.setattr(sdio, "_sounddevice_import_attempted", True)
    with pytest.raises(SoundDeviceUnavailable):
        sdio.AudioOutputDevice(sample_rate=8000, channels=1)


def test_list_devices_returns_list():
    """Returns an empty list when sounddevice is unavailable."""
    from pybluehost.audio._sounddevice_io import list_devices, is_available
    result = list_devices()
    assert isinstance(result, list)
    if not is_available():
        assert result == []


def test_constants_exported():
    """AudioInputDevice, AudioOutputDevice, SoundDeviceUnavailable are all importable."""
    from pybluehost.audio._sounddevice_io import (
        AudioInputDevice, AudioOutputDevice, SoundDeviceUnavailable,
    )
    assert AudioInputDevice is not None
    assert AudioOutputDevice is not None
    assert issubclass(SoundDeviceUnavailable, RuntimeError)
