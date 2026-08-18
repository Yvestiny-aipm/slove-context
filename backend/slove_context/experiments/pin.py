"""Pin the 9.1 eval case set by ids, hashes, and snapshot refs.

Reads ``evals/`` only. Does not overwrite expected answers.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from slove_context.evals.loader import load_all_cases
from slove_context.evals.models import LoadedEvalCase
from slove_context.evals.paths import repo_root
from slove_context.experiments.constants import CASE_SET_VERSION
from slove_context.experiments.models import CaseSetPin


def pin_case_set(
    *,
    case_ids: list[str] | None = None,
    cases: list[LoadedEvalCase] | None = None,
) -> tuple[CaseSetPin, list[LoadedEvalCase]]:
    loaded = list(cases) if cases is not None else load_all_cases()
    if case_ids:
        wanted = list(case_ids)
        by_id = {item.manifest.id: item for item in loaded}
        missing = [case_id for case_id in wanted if case_id not in by_id]
        if missing:
            raise ValueError(f"unknown eval case ids: {missing}")
        selected = [by_id[case_id] for case_id in wanted]
    else:
        selected = sorted(loaded, key=lambda item: item.manifest.id)
        wanted = [item.manifest.id for item in selected]
    root = repo_root()
    fixture_hashes: dict[str, dict[str, str]] = {}
    expected_hashes: dict[str, dict[str, str]] = {}
    snapshot_ids: dict[str, str] = {}
    for item in selected:
        fixture_hashes[item.manifest.id] = {
            key: _file_hash(root / relative)
            for key, relative in item.manifest.fixture_paths.items()
        }
        expected_hashes[item.manifest.id] = {
            key: _file_hash(root / relative)
            for key, relative in item.manifest.expected_paths.items()
        }
        snapshot_ids[item.manifest.id] = str(item.canon_snapshot.get("id") or "")
    pin = CaseSetPin(
        version=CASE_SET_VERSION,
        case_ids=tuple(wanted),
        fixture_hashes=fixture_hashes,
        expected_hashes=expected_hashes,
        snapshot_ids=snapshot_ids,
    )
    return pin, selected


def input_versions(
    pin: CaseSetPin, *, prompt_version: str, random_seed: int
) -> dict[str, object]:
    return {
        "case_set_version": pin.version,
        "case_ids": list(pin.case_ids),
        "fixture_hashes": {
            case_id: dict(hashes) for case_id, hashes in pin.fixture_hashes.items()
        },
        "expected_hashes": {
            case_id: dict(hashes) for case_id, hashes in pin.expected_hashes.items()
        },
        "snapshot_ids": dict(pin.snapshot_ids),
        "prompt_version": prompt_version,
        "random_seed": random_seed,
    }


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest
