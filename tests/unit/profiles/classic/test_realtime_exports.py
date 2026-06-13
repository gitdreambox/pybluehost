"""Real-time SCO workers are exported from pybluehost.profiles.classic."""


def test_mic_to_sco_sender_is_exported():
    from pybluehost.profiles.classic import MicToScoSender
    assert MicToScoSender is not None


def test_sco_to_speaker_receiver_is_exported():
    from pybluehost.profiles.classic import ScoToSpeakerReceiver
    assert ScoToSpeakerReceiver is not None
