"""Narrative consistency eval dataset + deterministic runner (node 9.1).

Loads cases from ``evals/``, runs existing 5.x hard rules in memory, and
adds eval-only checks only when a category cannot be expressed with
those rules. Not experiment comparison (9.2). Not a release gate (9.3).
Does not write Canon, approve candidates, or call a real model.
"""

from slove_context.evals.runner import run_all, run_case, write_report

__all__ = ["run_all", "run_case", "write_report"]
