"""Review Queue repository. Tests use in-memory. No Postgres."""

from __future__ import annotations

from typing import Protocol

from slove_context.review_queue.models import ReviewDecision, ReviewQueueItem


class ReviewQueueRepository(Protocol):
    def add_item(self, item: ReviewQueueItem) -> None: ...

    def get_item(self, item_id: str) -> ReviewQueueItem | None: ...

    def save_item(self, item: ReviewQueueItem) -> None: ...

    def list_items(self, project_id: str) -> list[ReviewQueueItem]: ...

    def find_open_item(
        self, project_id: str, subject_type: str, subject_id: str
    ) -> ReviewQueueItem | None: ...

    def add_decision(self, decision: ReviewDecision) -> None: ...

    def get_decision(self, decision_id: str) -> ReviewDecision | None: ...

    def list_decisions(self, item_id: str) -> list[ReviewDecision]: ...


class InMemoryReviewQueueRepository:
    """Fake repository for API tests. Does not open Postgres."""

    def __init__(self) -> None:
        self.items: dict[str, ReviewQueueItem] = {}
        self.decisions: dict[str, ReviewDecision] = {}

    def add_item(self, item: ReviewQueueItem) -> None:
        self.items[item.id] = item

    def get_item(self, item_id: str) -> ReviewQueueItem | None:
        return self.items.get(item_id)

    def save_item(self, item: ReviewQueueItem) -> None:
        self.items[item.id] = item

    def list_items(self, project_id: str) -> list[ReviewQueueItem]:
        items = [item for item in self.items.values() if item.project_id == project_id]
        items.sort(key=lambda item: (item.created_at, item.id))
        return items

    def find_open_item(
        self, project_id: str, subject_type: str, subject_id: str
    ) -> ReviewQueueItem | None:
        matches = [
            item
            for item in self.items.values()
            if item.project_id == project_id
            and item.subject_type == subject_type
            and item.subject_id == subject_id
            and item.status in {"Opened", "Escalated"}
        ]
        if not matches:
            return None
        matches.sort(key=lambda item: item.created_at)
        return matches[-1]

    def add_decision(self, decision: ReviewDecision) -> None:
        self.decisions[decision.id] = decision

    def get_decision(self, decision_id: str) -> ReviewDecision | None:
        return self.decisions.get(decision_id)

    def list_decisions(self, item_id: str) -> list[ReviewDecision]:
        items = [item for item in self.decisions.values() if item.item_id == item_id]
        items.sort(key=lambda item: (item.created_at, item.id))
        return items
