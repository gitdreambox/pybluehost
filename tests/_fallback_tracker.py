"""Session-scoped counter for tests that ran on virtual after autodetect fallback.

Read by pytest_terminal_summary.
"""
from __future__ import annotations


class FallbackTracker:
    """Tracks whether autodetect fell back to virtual and how many tests ran."""

    def __init__(self) -> None:
        self._fallback = False
        self._count = 0

    def mark_fallback(self) -> None:
        self._fallback = True

    def is_fallback(self) -> bool:
        return self._fallback

    def increment(self) -> None:
        self._count += 1

    @property
    def count(self) -> int:
        return self._count
