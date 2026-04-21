"""BLE profile decorators for service and characteristic binding."""
from __future__ import annotations


def ble_service(yaml_path: str):
    """Class decorator: associate a YAML service definition with a Profile class."""
    def decorator(cls: type) -> type:
        cls._service_yaml = yaml_path
        return cls
    return decorator


def on_read(uuid):
    """Mark an async method as the read handler for a characteristic UUID."""
    def decorator(fn):
        fn._ble_callback_type = "read"
        fn._ble_uuid = uuid
        fn._att_read = uuid
        return fn
    return decorator


def on_write(uuid):
    """Mark an async method as the write handler for a characteristic UUID."""
    def decorator(fn):
        fn._ble_callback_type = "write"
        fn._ble_uuid = uuid
        fn._att_write = uuid
        return fn
    return decorator


def on_notify(uuid):
    """Mark an async method as the notify data source for a characteristic UUID."""
    def decorator(fn):
        fn._ble_callback_type = "notify"
        fn._ble_uuid = uuid
        fn._att_notify = uuid
        return fn
    return decorator


def on_indicate(uuid):
    """Mark an async method as the indicate data source for a characteristic UUID."""
    def decorator(fn):
        fn._ble_callback_type = "indicate"
        fn._ble_uuid = uuid
        fn._att_indicate = uuid
        return fn
    return decorator
