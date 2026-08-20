"""Atomic file snapshot + write-through flush (node P.1)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from slove_context.persist.snapshot import (
    SNAPSHOT_VERSION,
    BookBundle,
    apply_snapshot,
    dump_book,
)

_FORBIDDEN_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "private_key",
    "password",
    "secret_key",
)
_FORBIDDEN_VALUE_MARKERS = (
    "DEEPSEEK_API_KEY=",
    "MODEL_API_KEY=",
)


class PersistError(ValueError):
    """Invalid or secret-bearing book snapshot."""


class FlushingProxy:
    """Forward reads; flush the book file after add/save writes."""

    def __init__(self, inner: Any, flush: Callable[[], None]) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_flush", flush)

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if callable(attr) and _is_write_method(name):

            def wrapped(*args: Any, **kwargs: Any) -> Any:
                result = attr(*args, **kwargs)
                self._flush()
                return result

            return wrapped
        return attr

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_inner", "_flush"}:
            object.__setattr__(self, name, value)
            return
        setattr(self._inner, name, value)


def _is_write_method(name: str) -> bool:
    return name in {"add", "save"} or name.startswith("add_") or name.startswith(
        "save_"
    )


def flushing_proxy(inner: Any, flush: Callable[[], None]) -> Any:
    return FlushingProxy(inner, flush)


def assert_no_secrets(value: Any, *, path: str = "snapshot") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower().replace("-", "_")
            if any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
                raise PersistError(f"refusing to persist secret field {path}.{key}")
            assert_no_secrets(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            assert_no_secrets(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        for marker in _FORBIDDEN_VALUE_MARKERS:
            if marker in value:
                raise PersistError(f"refusing to persist secret marker at {path}")


class FileBookStore:
    def __init__(self, path: Path, bundle: BookBundle) -> None:
        self.path = path
        self.bundle = bundle

    def exists(self) -> bool:
        return self.path.is_file() and bool(self.path.stat().st_size)

    def load(self) -> bool:
        if not self.path.is_file():
            return False
        text = self.path.read_text(encoding="utf-8").strip()
        if not text:
            return False
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PersistError(f"book snapshot is not valid JSON: {self.path}") from exc
        if not isinstance(payload, dict):
            raise PersistError(f"book snapshot must be an object: {self.path}")
        version = payload.get("version")
        if version not in {SNAPSHOT_VERSION, None}:
            raise PersistError(f"unsupported book snapshot version: {version}")
        assert_no_secrets(payload)
        apply_snapshot(payload, self.bundle)
        return True

    def save(self) -> None:
        payload = dump_book(self.bundle)
        assert_no_secrets(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, ensure_ascii=False, indent=2)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(encoded + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def wrap_bundle(self) -> BookBundle:
        flush = self.save
        return BookBundle(
            story=flushing_proxy(self.bundle.story, flush),
            canon=flushing_proxy(self.bundle.canon, flush),
            scene=flushing_proxy(self.bundle.scene, flush),
            scene_plan=flushing_proxy(self.bundle.scene_plan, flush),
            scene_draft=flushing_proxy(self.bundle.scene_draft, flush),
            candidate_change=flushing_proxy(self.bundle.candidate_change, flush),
            context_pack=flushing_proxy(self.bundle.context_pack, flush),
        )
