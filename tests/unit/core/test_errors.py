from pybluehost.core.errors import (
    PyBlueHostError,
    TransportError,
    HCIError,
    L2CAPError,
    GATTError,
    SMPError,
    InvalidTransitionError,
    TimeoutError as BTTimeoutError,
)


def test_base_error_is_exception():
    assert issubclass(PyBlueHostError, Exception)


def test_transport_error_inherits_base():
    err = TransportError("USB disconnected")
    assert isinstance(err, PyBlueHostError)
    assert str(err) == "USB disconnected"


def test_hci_error_with_status_code():
    err = HCIError("Command failed", status=0x02)
    assert isinstance(err, PyBlueHostError)
    assert err.status == 0x02
    assert "Command failed" in str(err)


def test_l2cap_error_inherits_base():
    err = L2CAPError("Channel refused")
    assert isinstance(err, PyBlueHostError)


def test_gatt_error_with_att_error_code():
    err = GATTError("Read not permitted", att_error=0x02)
    assert isinstance(err, PyBlueHostError)
    assert err.att_error == 0x02


def test_smp_error_with_reason():
    err = SMPError("Pairing failed", reason=0x04)
    assert isinstance(err, PyBlueHostError)
    assert err.reason == 0x04


def test_invalid_transition_error():
    err = InvalidTransitionError(
        sm_name="hci_conn",
        from_state="CONNECTED",
        event="CONNECT_COMPLETE",
    )
    assert isinstance(err, PyBlueHostError)
    assert "hci_conn" in str(err)
    assert "CONNECTED" in str(err)
    assert "CONNECT_COMPLETE" in str(err)


def test_timeout_error_inherits_base():
    err = BTTimeoutError("HCI command timeout", timeout=5.0)
    assert isinstance(err, PyBlueHostError)
    assert err.timeout == 5.0
