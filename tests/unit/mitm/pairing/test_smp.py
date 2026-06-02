from pybluehost.cli.app.mitm.pairing.delegate import AutoConfirmDelegate


async def test_auto_confirm_yes():
    d = AutoConfirmDelegate()
    assert await d.confirm_numeric("phone", 123456) is True
    assert await d.confirm_numeric("target", 654321) is True
