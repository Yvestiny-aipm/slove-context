"""Development-only CORS helpers for the local workflow Demo (node UI.1).

Never opens ``*`` when SLOVE_ENV=production. Production defaults to no
browser origins. Development defaults to the Vite origin only.
"""

from __future__ import annotations

import os

DEFAULT_DEV_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def cors_origins_for_env(
    *,
    env: str | None = None,
    configured: str | None = None,
) -> list[str]:
    """Return allowed browser origins. Empty means do not enable CORS."""
    resolved_env = (
        (env if env is not None else os.environ.get("SLOVE_ENV", "development"))
        .strip()
        .lower()
    )
    raw = configured if configured is not None else os.environ.get("SLOVE_CORS_ORIGINS")
    if resolved_env == "production":
        if raw is None or not raw.strip() or raw.strip() == "*":
            return []
        return [
            item.strip()
            for item in raw.split(",")
            if item.strip() and item.strip() != "*"
        ]
    if raw is None or not raw.strip() or raw.strip() == "*":
        return list(DEFAULT_DEV_ORIGINS)
    origins = [
        item.strip() for item in raw.split(",") if item.strip() and item.strip() != "*"
    ]
    return origins or list(DEFAULT_DEV_ORIGINS)
