"""End-to-end LE lifecycle scenarios."""
from __future__ import annotations


def test_test_service_definition_round_trips():
    """build_test_service() returns a valid ServiceDefinition with 3 chars."""
    from tests.e2e._test_service import build_test_service
    svc = build_test_service()
    assert len(svc.characteristics) == 3
    uuids = [c.uuid for c in svc.characteristics]
    from tests.e2e._test_service import (
        TEST_READ_CHAR_UUID, TEST_WRITE_CHAR_UUID, TEST_NOTIFY_CHAR_UUID,
    )
    assert TEST_READ_CHAR_UUID in uuids
    assert TEST_WRITE_CHAR_UUID in uuids
    assert TEST_NOTIFY_CHAR_UUID in uuids
