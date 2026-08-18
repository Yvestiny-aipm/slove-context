"""Export experiment runs and comparisons as JSON or CSV.

Output references only. No draft prose, prompts, or text_evidence.
"""

from __future__ import annotations

import csv
import io
import json

from slove_context.experiments.models import ExperimentComparison, ExperimentRun


def export_run_json(run: ExperimentRun) -> str:
    return json.dumps(run.to_public_dict(), ensure_ascii=False, indent=2) + "\n"


def export_run_csv(run: ExperimentRun) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["section", "key", "value"])
    writer.writerow(["run", "id", run.id])
    writer.writerow(["run", "experiment_id", run.experiment_id])
    writer.writerow(["run", "status", run.status])
    for key, value in run.config.to_public_dict().items():
        writer.writerow(["config", key, value])
    for key, value in run.metrics.to_public_dict().items():
        writer.writerow(["metrics", key, value])
    for key, value in run.cost.to_public_dict().items():
        writer.writerow(["cost", key, value])
    writer.writerow(["timing", "latency_ms", run.latency_ms])
    writer.writerow(["timing", "duration_ms", run.duration_ms])
    writer.writerow([])
    writer.writerow(
        [
            "case_id",
            "raw_response_reference",
            "request_id",
            "schema_ok",
            "first_pass",
            "canon_conflict_count",
            "blocker_error_count",
        ]
    )
    for item in run.output_refs:
        writer.writerow(
            [
                item.get("case_id"),
                item.get("raw_response_reference"),
                item.get("request_id"),
                item.get("schema_ok"),
                item.get("first_pass"),
                item.get("canon_conflict_count"),
                item.get("blocker_error_count"),
            ]
        )
    return buffer.getvalue()


def export_comparison_json(comparison: ExperimentComparison) -> str:
    return json.dumps(comparison.to_public_dict(), ensure_ascii=False, indent=2) + "\n"


def export_comparison_csv(comparison: ExperimentComparison) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["metric", "baseline", "candidate", "delta"])
    for item in comparison.metrics:
        writer.writerow([item.metric, item.baseline, item.candidate, item.delta])
    return buffer.getvalue()
