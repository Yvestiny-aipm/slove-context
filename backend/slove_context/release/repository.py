"""Release repository. Tests use in-memory. No Postgres."""

from __future__ import annotations

from typing import Protocol

from slove_context.release.models import (
    DueItem,
    HumanWaiver,
    ReleaseCheck,
    ReleaseExport,
    ReleaseManifest,
    SafetyCheck,
)


class ReleaseRepository(Protocol):
    def add_check(self, check: ReleaseCheck) -> None: ...

    def get_check(self, check_id: str) -> ReleaseCheck | None: ...

    def save_check(self, check: ReleaseCheck) -> None: ...

    def list_checks(self, project_id: str) -> list[ReleaseCheck]: ...

    def add_manifest(self, manifest: ReleaseManifest) -> None: ...

    def get_manifest(self, manifest_id: str) -> ReleaseManifest | None: ...

    def add_export(self, export: ReleaseExport) -> None: ...

    def get_export(self, export_id: str) -> ReleaseExport | None: ...

    def list_exports(self, check_id: str) -> list[ReleaseExport]: ...

    def add_due_item(self, item: DueItem) -> None: ...

    def get_due_item(self, item_id: str) -> DueItem | None: ...

    def save_due_item(self, item: DueItem) -> None: ...

    def list_due_items(self, project_id: str) -> list[DueItem]: ...

    def add_waiver(self, waiver: HumanWaiver) -> None: ...

    def get_waiver(self, waiver_id: str) -> HumanWaiver | None: ...

    def list_waivers(self, project_id: str) -> list[HumanWaiver]: ...

    def add_safety_check(self, check: SafetyCheck) -> None: ...

    def get_safety_check(self, check_id: str) -> SafetyCheck | None: ...

    def save_safety_check(self, check: SafetyCheck) -> None: ...

    def list_safety_checks(self, project_id: str) -> list[SafetyCheck]: ...


class InMemoryReleaseRepository:
    """Fake repository for API tests. Does not open Postgres."""

    def __init__(self) -> None:
        self.checks: dict[str, ReleaseCheck] = {}
        self.manifests: dict[str, ReleaseManifest] = {}
        self.exports: dict[str, ReleaseExport] = {}
        self.due_items: dict[str, DueItem] = {}
        self.waivers: dict[str, HumanWaiver] = {}
        self.safety_checks: dict[str, SafetyCheck] = {}

    def add_check(self, check: ReleaseCheck) -> None:
        self.checks[check.id] = check

    def get_check(self, check_id: str) -> ReleaseCheck | None:
        return self.checks.get(check_id)

    def save_check(self, check: ReleaseCheck) -> None:
        self.checks[check.id] = check

    def list_checks(self, project_id: str) -> list[ReleaseCheck]:
        items = [item for item in self.checks.values() if item.project_id == project_id]
        items.sort(key=lambda item: (item.created_at, item.id))
        return items

    def add_manifest(self, manifest: ReleaseManifest) -> None:
        self.manifests[manifest.id] = manifest

    def get_manifest(self, manifest_id: str) -> ReleaseManifest | None:
        return self.manifests.get(manifest_id)

    def add_export(self, export: ReleaseExport) -> None:
        self.exports[export.id] = export

    def get_export(self, export_id: str) -> ReleaseExport | None:
        return self.exports.get(export_id)

    def list_exports(self, check_id: str) -> list[ReleaseExport]:
        items = [item for item in self.exports.values() if item.check_id == check_id]
        items.sort(key=lambda item: (item.created_at, item.id))
        return items

    def add_due_item(self, item: DueItem) -> None:
        self.due_items[item.id] = item

    def get_due_item(self, item_id: str) -> DueItem | None:
        return self.due_items.get(item_id)

    def save_due_item(self, item: DueItem) -> None:
        self.due_items[item.id] = item

    def list_due_items(self, project_id: str) -> list[DueItem]:
        items = [
            item for item in self.due_items.values() if item.project_id == project_id
        ]
        items.sort(key=lambda item: (item.created_at, item.id))
        return items

    def add_waiver(self, waiver: HumanWaiver) -> None:
        self.waivers[waiver.id] = waiver

    def get_waiver(self, waiver_id: str) -> HumanWaiver | None:
        return self.waivers.get(waiver_id)

    def list_waivers(self, project_id: str) -> list[HumanWaiver]:
        items = [
            item for item in self.waivers.values() if item.project_id == project_id
        ]
        items.sort(key=lambda item: (item.created_at, item.id))
        return items

    def add_safety_check(self, check: SafetyCheck) -> None:
        self.safety_checks[check.id] = check

    def get_safety_check(self, check_id: str) -> SafetyCheck | None:
        return self.safety_checks.get(check_id)

    def save_safety_check(self, check: SafetyCheck) -> None:
        self.safety_checks[check.id] = check

    def list_safety_checks(self, project_id: str) -> list[SafetyCheck]:
        items = [
            item
            for item in self.safety_checks.values()
            if item.project_id == project_id
        ]
        items.sort(key=lambda item: (item.created_at, item.id))
        return items
