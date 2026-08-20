"""CLI: ``python -m slove_context.demo``.

Default: create the in-process app (node P.1 loads a saved book when
present), seed only if the book is empty, and serve it.
``--seed-only`` prints the seed JSON and exits.
``--http URL`` seeds a running backend (still CLI-only; no seed-status route).
``--with-frontend`` also starts the Vite Demo UI.
Does not overwrite an already-saved imported book.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from slove_context.app import create_app
from slove_context.demo.seed import DemoSeedError, seed_demo, seed_via_http
from slove_context.persist import persist_file_has_book


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _print_result(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("Demo / Fake Provider / 非真实模型", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Local workflow Demo seeder (Fake Provider only)."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--seed-only",
        action="store_true",
        help="Seed in-process and print JSON. Do not serve.",
    )
    parser.add_argument(
        "--http",
        default="",
        help="Seed a running backend via HTTP. CLI only; no seed-status route.",
    )
    parser.add_argument(
        "--with-frontend",
        action="store_true",
        help="Also start the Vite frontend on port 5173.",
    )
    args = parser.parse_args(argv)

    if args.http:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("httpx is required for --http") from exc
        with httpx.Client(base_url=args.http.rstrip("/"), timeout=30.0) as client:
            try:
                result = seed_via_http(client)
            except DemoSeedError as exc:
                print(str(exc), file=sys.stderr)
                return 1
        _print_result(result)
        return 0

    os.environ.setdefault("SLOVE_ENV", "development")
    application = create_app()
    persist_path = getattr(application.state, "persist_path", None)
    try:
        # seed_demo is a no-op when a project already exists (loaded book).
        result = seed_demo(application)
    except DemoSeedError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    result = {
        **result,
        "persist_path": str(persist_path) if persist_path is not None else None,
        "persist_loaded": bool(
            persist_path is not None and persist_file_has_book(persist_path)
        ),
    }
    _print_result(result)
    if args.seed_only:
        return 0

    frontend_proc: subprocess.Popen[bytes] | None = None
    if args.with_frontend:
        frontend_dir = _repo_root() / "frontend"
        if not (frontend_dir / "node_modules").is_dir():
            install = subprocess.run(
                ["npm", "install"],
                cwd=frontend_dir,
                check=False,
            )
            if install.returncode != 0:
                print("npm install failed", file=sys.stderr)
                return install.returncode
        env = os.environ.copy()
        env.setdefault("VITE_API_BASE", f"http://{args.host}:{args.port}")
        frontend_proc = subprocess.Popen(
            ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"],
            cwd=frontend_dir,
            env=env,
        )
        print("打开前端：http://127.0.0.1:5173", flush=True)
        print(f"后端 API：http://{args.host}:{args.port}", flush=True)

    import uvicorn

    try:
        uvicorn.run(application, host=args.host, port=args.port)
    finally:
        if frontend_proc is not None:
            frontend_proc.terminate()
            frontend_proc.wait(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
