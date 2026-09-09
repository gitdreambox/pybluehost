from pybluehost.cli.app.mitm.cli import default_btsnoop_name, _select_delegate
from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate


def test_default_btsnoop_name():
    n = default_btsnoop_name()
    assert n.endswith(".btsnoop") and "mitm" in n


def test_pairing_just_works_delegate():
    assert isinstance(_select_delegate("just-works"), AutoConfirmDelegate)


def test_pairing_numeric_delegate():
    # numeric only declares DisplayYesNo+MITM capability; the delegate still auto-confirms — authorized automation
    # (both ends of the gate are our own devices; InteractiveNumericDelegate reading stdin would block the background relay).
    assert isinstance(_select_delegate("numeric"), AutoConfirmDelegate)


def test_key_log_default_is_stable_name():
    from pybluehost.cli.app.mitm.cli import KEY_LOG_DEFAULT
    assert KEY_LOG_DEFAULT == "mitm-keys.jsonl"  # fix timestamp-default bug: keys reusable across restarts
