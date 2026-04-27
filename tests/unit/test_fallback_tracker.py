from tests._fallback_tracker import FallbackTracker


def test_fallback_tracker_initial_state():
    t = FallbackTracker()
    assert not t.is_fallback()
    assert t.count == 0


def test_fallback_tracker_mark_and_increment():
    t = FallbackTracker()
    t.mark_fallback()
    assert t.is_fallback()
    t.increment()
    t.increment()
    assert t.count == 2
