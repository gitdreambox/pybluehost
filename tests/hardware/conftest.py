"""Hardware test fixtures — skipped unless --hardware flag is passed."""
import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--hardware", action="store_true", default=False,
        help="Run hardware tests requiring a real USB Bluetooth adapter",
    )


@pytest.fixture(scope="session")
def hardware_required(request: pytest.FixtureRequest) -> None:
    if not request.config.getoption("--hardware"):
        pytest.skip("Pass --hardware to run hardware tests")
