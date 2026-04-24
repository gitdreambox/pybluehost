# Test Fixture Data

Binary btsnoop capture files used by replay tests.

## Files

- `hci_reset.btsnoop` — Minimal 4-packet capture: HCI Reset + Read_BD_ADDR with their Command Complete responses.

## Generating fixtures

```bash
uv run python pybluehost/tools/gen_btsnoop_fixture.py
```
