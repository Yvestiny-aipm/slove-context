"""CLI: ``python -m slove_context.evals --out /tmp/narrative-eval.json``."""

from __future__ import annotations

import argparse
from pathlib import Path

from slove_context.evals.runner import run_all, write_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic narrative consistency eval runner (node 9.1)."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("/tmp/narrative-eval.json"),
        help="JSON report path (default: /tmp/narrative-eval.json)",
    )
    args = parser.parse_args(argv)
    results, summary = run_all()
    write_report(results, summary, args.out)
    print(f"wrote {args.out}")
    print(
        "cases_run={cases_run} passed={passed} hits={hits} "
        "misses={misses} extras={extras} precision={precision} "
        "recall={recall}".format(**summary.to_public_dict())
    )
    return 0 if summary.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
