"""Node P.1: local book snapshot for Demo / service process restart.

Dumps and loads the in-memory book repositories to one default file
(``data/book.json``, overridable by ``SLOVE_BOOK_PATH``). Not Postgres.
Does not write Canon, approve, or store API keys.
"""

from slove_context.persist.paths import (
    ENV_BOOK_PATH,
    default_book_path,
    normalize_book_path,
    persist_file_has_book,
    resolve_persist_path,
)
from slove_context.persist.snapshot import BookBundle, apply_snapshot, dump_book
from slove_context.persist.store import FileBookStore, PersistError, flushing_proxy

__all__ = [
    "ENV_BOOK_PATH",
    "BookBundle",
    "FileBookStore",
    "PersistError",
    "apply_snapshot",
    "default_book_path",
    "dump_book",
    "flushing_proxy",
    "normalize_book_path",
    "persist_file_has_book",
    "resolve_persist_path",
]
