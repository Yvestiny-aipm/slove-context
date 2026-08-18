"""Node 1.1 skeleton placeholder. No novel-writing business logic.

The Makefile `test` target also collects `contracts/` (node 0.4) tests.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_skeleton_placeholder() -> None:
    assert (ROOT / "AGENTS.md").is_file()
    assert (ROOT / "docs" / "architecture.md").is_file()
    assert (ROOT / "backend" / "slove_context" / "__init__.py").is_file()
    assert (ROOT / "contracts" / "tests" / "test_schemas.py").is_file()
