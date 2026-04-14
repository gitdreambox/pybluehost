from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import yaml


@dataclass(frozen=True)
class _UUIDEntry:
    uuid: int
    name: str
    identifier: str


class SIGDatabase:
    """Runtime SIG official YAML lookup — lazy-loaded, singleton."""

    _instance: ClassVar[SIGDatabase | None] = None
    _default_root: ClassVar[Path] = Path(__file__).resolve().parent.parent / "lib" / "sig"

    def __init__(self, sig_root: Path | None = None) -> None:
        self._sig_root = sig_root or self._default_root
        self._services: dict[int, _UUIDEntry] | None = None
        self._characteristics: dict[int, _UUIDEntry] | None = None
        self._descriptors: dict[int, _UUIDEntry] | None = None
        self._companies: dict[int, str] | None = None
        self._company_name_to_id: dict[str, int] | None = None
        self._ad_types: dict[int, str] | None = None
        self._appearances: dict[int, str] | None = None

    @classmethod
    def get(cls) -> SIGDatabase:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── UUID lookups ──

    def service_name(self, uuid: int) -> str | None:
        entry = self._ensure_services().get(uuid)
        return entry.name if entry else None

    def service_id(self, uuid: int) -> str | None:
        entry = self._ensure_services().get(uuid)
        return entry.identifier if entry else None

    def characteristic_name(self, uuid: int) -> str | None:
        entry = self._ensure_characteristics().get(uuid)
        return entry.name if entry else None

    def characteristic_id(self, uuid: int) -> str | None:
        entry = self._ensure_characteristics().get(uuid)
        return entry.identifier if entry else None

    def descriptor_name(self, uuid: int) -> str | None:
        entry = self._ensure_descriptors().get(uuid)
        return entry.name if entry else None

    def uuid_by_name(self, name: str) -> int | None:
        for table_fn in (self._ensure_services, self._ensure_characteristics, self._ensure_descriptors):
            for entry in table_fn().values():
                if entry.name == name:
                    return entry.uuid
        return None

    # ── Company ID ──

    def company_name(self, company_id: int) -> str | None:
        return self._ensure_companies().get(company_id)

    def company_id_by_name(self, name: str) -> int | None:
        self._ensure_companies()
        assert self._company_name_to_id is not None
        for stored_name, cid in self._company_name_to_id.items():
            if name.lower() in stored_name.lower():
                return cid
        return None

    # ── GAP constants ──

    def ad_type_name(self, type_code: int) -> str | None:
        return self._ensure_ad_types().get(type_code)

    def appearance_category(self, value: int) -> str | None:
        return self._ensure_appearances().get(value)

    # ── Internal loaders ──

    def _ensure_services(self) -> dict[int, _UUIDEntry]:
        if self._services is None:
            self._services = self._load_uuid_yaml("uuids/service_uuids.yaml")
        return self._services

    def _ensure_characteristics(self) -> dict[int, _UUIDEntry]:
        if self._characteristics is None:
            self._characteristics = self._load_uuid_yaml("uuids/characteristic_uuids.yaml")
        return self._characteristics

    def _ensure_descriptors(self) -> dict[int, _UUIDEntry]:
        if self._descriptors is None:
            self._descriptors = self._load_uuid_yaml("uuids/descriptors.yaml")
        return self._descriptors

    def _ensure_companies(self) -> dict[int, str]:
        if self._companies is None:
            path = self._sig_root / "assigned_numbers" / "company_identifiers" / "company_identifiers.yaml"
            with open(path) as f:
                data = yaml.safe_load(f)
            self._companies = {}
            self._company_name_to_id = {}
            for entry in data["company_identifiers"]:
                cid = entry["value"]
                name = entry["name"]
                self._companies[cid] = name
                self._company_name_to_id[name] = cid
        return self._companies

    def _ensure_ad_types(self) -> dict[int, str]:
        if self._ad_types is None:
            path = self._sig_root / "assigned_numbers" / "core" / "ad_types.yaml"
            with open(path) as f:
                data = yaml.safe_load(f)
            self._ad_types = {e["value"]: e["name"] for e in data["ad_types"]}
        return self._ad_types

    def _ensure_appearances(self) -> dict[int, str]:
        if self._appearances is None:
            path = self._sig_root / "assigned_numbers" / "core" / "appearance_values.yaml"
            with open(path) as f:
                data = yaml.safe_load(f)
            self._appearances = {e["category"]: e["name"] for e in data["appearance_values"]}
        return self._appearances

    def _load_uuid_yaml(self, relative_path: str) -> dict[int, _UUIDEntry]:
        path = self._sig_root / "assigned_numbers" / relative_path
        with open(path) as f:
            data = yaml.safe_load(f)
        return {
            entry["uuid"]: _UUIDEntry(
                uuid=entry["uuid"],
                name=entry["name"],
                identifier=entry.get("id", ""),
            )
            for entry in data["uuids"]
        }
