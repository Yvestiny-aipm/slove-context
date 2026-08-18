"""Local workflow Demo seeder (node UI.1).

CLI only. Not a production seed-status HTTP route. Fake Provider only.
Does not approve or submit Canon for extracted candidates.
"""

from slove_context.demo.seed import DemoSeedError, seed_demo, seed_via_http

__all__ = ["DemoSeedError", "seed_demo", "seed_via_http"]
