# Repository Guidelines

## Project Overview

PyBlueHost is a Python Bluetooth Host stack library for testing, simulation, and protocol education. It is currently in early planning/development (v0.0.1 placeholder). The library targets Python 3.10+.

## Build, Test, and Development Commands
Use `uv` for environment and task execution:

- `uv sync` installs the project into the local `.venv`.
- `uv pip install -e .` installs the package in editable mode for development.
- `uv run pytest` runs the full test suite once tests are added.
- `uv run pytest tests/test_hci.py::test_packet_parse` runs a single test.
- `uv build` creates source and wheel distributions via `hatchling`.

## Coding Style & Naming Conventions
Target Python 3.10+ and use 4-space indentation. Follow standard Python naming: modules and functions in `snake_case`, classes in `PascalCase`, constants in `UPPER_SNAKE_CASE`. Keep each Bluetooth layer isolated and testable; for example, prefer `pybluehost/hci.py` or `pybluehost/l2cap.py` over putting multiple protocol layers in one file. Public module exports should stay explicit in `__init__.py`.

## Testing Guidelines — TDD Mandatory

**All development MUST follow strict TDD (Test-Driven Development).** This is non-negotiable.

### TDD Workflow (Red → Green → Refactor)
1. **Red**: Write a failing test FIRST that describes the expected behavior. Run it and confirm it fails.
2. **Green**: Write the minimum production code to make the test pass. No more.
3. **Refactor**: Clean up the code while keeping all tests green.

### Rules
- **Never write production code without a failing test.** If there is no test demanding the code, do not write it.
- **One test at a time.** Write one failing test, make it pass, then write the next.
- **Tests must fail for the right reason.** A new test should fail because the feature is missing, not because of a syntax error or import issue.
- **Run tests after every change.** Use `uv run pytest` to verify red/green status.

### Test Organization
- Use `pytest`. Place tests in `tests/` with filenames matching `test_*.py`.
- Mirror the source structure: `pybluehost/hci/packets.py` → `tests/unit/hci/test_packets.py`.
- Prefer small, protocol-focused unit tests that do not require Bluetooth hardware.
- Simulation and parsing behavior should be covered first, especially for HCI and L2CAP boundaries.

### Coverage Requirements
- Overall: ≥ 85%
- HCI packet encode/decode: 100%
- State machine transitions: 100%
- New protocol code must ship with tests — no exceptions.

## Commit & Pull Request Guidelines
The current history uses Conventional Commit style (`feat:init`), so continue with prefixes such as `feat:`, `fix:`, `test:`, and `docs:`. Keep commits scoped to one change. Pull requests should include a short description, test notes (`uv run pytest` output or explanation if no tests exist), and links to related issues. Include protocol traces or sample packets when they clarify behavior.

## Architecture Notes
This package is intended to grow as a layered Bluetooth host stack: HCI -> L2CAP -> ATT/GATT, SMP, and higher-level profiles. Preserve that layering in code and tests so each layer can be exercised independently.

