from __future__ import annotations


class PyBlueHostError(Exception):
    """Base exception for all PyBlueHost errors."""


class TransportError(PyBlueHostError):
    """Transport layer error (USB disconnect, serial timeout, etc.)."""


class HCIError(PyBlueHostError):
    """HCI layer error with optional status code."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class L2CAPError(PyBlueHostError):
    """L2CAP layer error."""


class GATTError(PyBlueHostError):
    """GATT layer error with optional ATT error code."""

    def __init__(self, message: str, att_error: int = 0) -> None:
        super().__init__(message)
        self.att_error = att_error


class SMPError(PyBlueHostError):
    """SMP layer error with optional reason code."""

    def __init__(self, message: str, reason: int = 0) -> None:
        super().__init__(message)
        self.reason = reason


class InvalidTransitionError(PyBlueHostError):
    """Raised when a state machine receives an event with no defined transition."""

    def __init__(self, sm_name: str, from_state: str, event: str) -> None:
        self.sm_name = sm_name
        self.from_state = from_state
        self.event = event
        super().__init__(
            f"{sm_name}: no transition from {from_state} via {event}"
        )


class TimeoutError(PyBlueHostError):
    """Operation timed out."""

    def __init__(self, message: str, timeout: float = 0.0) -> None:
        super().__init__(message)
        self.timeout = timeout
