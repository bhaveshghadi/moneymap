"""One request at a time for actions that must not run twice in parallel.

A double or triple click on "Import" sends the same request two or three times, a few
milliseconds apart. Each request first reads what's done, then writes — run side by side,
both would see "not imported yet" and both would create the transactions. With this lock the
second request waits for the first to finish, then reads its result (rows already imported,
the draft already open) and does nothing more.

The app runs one uvicorn process, so a lock in memory covers every request.
"""

import functools
import threading
from collections.abc import Callable
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")

_locks: dict[str, threading.RLock] = {}
_guard = threading.Lock()


def _lock(name: str) -> threading.RLock:
    with _guard:
        return _locks.setdefault(name, threading.RLock())  # re-entrant: one endpoint may call another


def one_at_a_time(name: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorate a (sync) endpoint, under its @router line: requests with the same name run in turn."""

    def deco(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with _lock(name):
                return fn(*args, **kwargs)

        return wrapper

    return deco
