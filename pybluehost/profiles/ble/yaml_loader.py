"""YAML service definition loader for BLE profiles."""
from __future__ import annotations

from pathlib import Path

from pybluehost.ble.gatt import (
    CharProperties,
    CharacteristicDefinition,
    Permissions,
    ServiceDefinition,
)
from pybluehost.core.uuid import UUID16


class ServiceYAMLLoader:
    """Load YAML service definitions and convert to ServiceDefinition."""

    @staticmethod
    def load(path: str | Path) -> ServiceDefinition:
        """Load a service definition from a YAML file."""
        import yaml

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return ServiceYAMLLoader._parse(data)

    @staticmethod
    def loads(yaml_string: str) -> ServiceDefinition:
        """Load a service definition from a YAML string."""
        import yaml

        data = yaml.safe_load(yaml_string)
        return ServiceYAMLLoader._parse(data)

    @staticmethod
    def load_builtin(name: str) -> ServiceDefinition:
        """Load a built-in service by name (e.g. 'hrs', 'bas', 'dis').

        Accepts either a bare name ('hrs') or a filename ('hrs.yaml').
        """
        services_dir = Path(__file__).parent / "services"
        stem = Path(name).stem
        path = services_dir / f"{stem}.yaml"
        return ServiceYAMLLoader.load(path)

    @staticmethod
    def validate(path: str | Path) -> list[str]:
        """Validate a YAML service definition file. Returns errors (empty = valid)."""
        errors: list[str] = []
        try:
            import yaml

            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data is None:
                errors.append("Empty YAML file")
            elif "uuid" not in data and "service" not in data:
                errors.append("Missing required key: 'uuid' or 'service'")
        except FileNotFoundError:
            errors.append(f"File not found: {path}")
        except Exception as e:
            errors.append(str(e))
        return errors

    @staticmethod
    def _parse(data: dict) -> ServiceDefinition:
        if "service" in data:
            svc_data = data["service"]
        else:
            svc_data = data

        uuid = UUID16(int(svc_data["uuid"], 16))
        chars: list[CharacteristicDefinition] = []
        for c in svc_data.get("characteristics", []):
            char_uuid = UUID16(int(c["uuid"], 16))
            props_data = c.get("properties", {})
            props = CharProperties(0)
            if isinstance(props_data, dict):
                if props_data.get("read"):
                    props |= CharProperties.READ
                if props_data.get("write"):
                    props |= CharProperties.WRITE
                if props_data.get("notify"):
                    props |= CharProperties.NOTIFY
                if props_data.get("indicate"):
                    props |= CharProperties.INDICATE
            elif isinstance(props_data, list):
                if "read" in props_data:
                    props |= CharProperties.READ
                if "write" in props_data:
                    props |= CharProperties.WRITE
                if "notify" in props_data:
                    props |= CharProperties.NOTIFY
                if "indicate" in props_data:
                    props |= CharProperties.INDICATE
            chars.append(
                CharacteristicDefinition(
                    uuid=char_uuid,
                    properties=props,
                    permissions=Permissions.READABLE | Permissions.WRITABLE,
                )
            )
        return ServiceDefinition(uuid=uuid, characteristics=chars)
