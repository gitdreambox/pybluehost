from pybluehost.cli.app.mitm.pairing.delegate import InteractiveNumericDelegate


async def test_interactive_accepts_yes():
    prompts = []
    async def fake_ask(prompt: str) -> str:
        prompts.append(prompt)
        return "y"
    d = InteractiveNumericDelegate(ask=fake_ask)
    assert await d.confirm_numeric("phone", 123456) is True
    assert "123456" in prompts[0]
    assert "phone" in prompts[0]


async def test_interactive_rejects_no():
    async def fake_ask(prompt: str) -> str:
        return "n"
    d = InteractiveNumericDelegate(ask=fake_ask)
    assert await d.confirm_numeric("target", 654321) is False


async def test_interactive_rejects_empty_default():
    async def fake_ask(prompt: str) -> str:
        return ""
    d = InteractiveNumericDelegate(ask=fake_ask)
    assert await d.confirm_numeric("phone", 1) is False
