"""fsops.py -- replace and delete files, surviving Windows sharing violations.

On Windows, renaming over (or deleting) a file that ANY process has open fails with
PermissionError -- Python's own open() does not grant delete-sharing. The worker
rewrites state.json every couple of seconds and heartbeat.json every few, while the
UI reads both about once a second, so over a 10-hour batch the two WILL collide; so
do antivirus and the search indexer, which briefly open every new file. Without a
retry, one such collision inside a stage marks a good run as failed.

The fix is the standard one: retry a short while with backoff. On POSIX the first
attempt always succeeds, so this costs nothing there.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

ATTEMPTS = 40               # ~6 s in total with the backoff below
FIRST_DELAY_S = 0.01
MAX_DELAY_S = 0.25


def _retry(op, *args):
    delay = FIRST_DELAY_S
    for i in range(ATTEMPTS):
        try:
            return op(*args)
        except PermissionError:
            if i == ATTEMPTS - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, MAX_DELAY_S)


def replace(src, dst) -> None:
    """os.replace, retried while another process briefly holds `dst` (or `src`) open."""
    _retry(os.replace, os.fspath(src), os.fspath(dst))


def unlink(path, missing_ok: bool = True) -> None:
    def _unlink(p):
        try:
            os.unlink(p)
        except FileNotFoundError:
            if not missing_ok:
                raise
    _retry(_unlink, os.fspath(Path(path)))
