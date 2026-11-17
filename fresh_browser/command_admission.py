"""Bound only the wait BEFORE a foreground browser operation starts.

No request replay, action cancellation, new permissions, background network work,
profile switching, or provider rate-limit changes. Maintenance keeps its lock.
"""
from __future__ import annotations

import asyncio
import contextvars
import functools
import math
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from fastapi import HTTPException

DEFAULT_WAIT_SECONDS = 5.0


@dataclass
class _Attempt:
    owner: asyncio.Task
    wait_seconds: float
    entered: bool = False


_ATTEMPT: contextvars.ContextVar[_Attempt | None] = contextvars.ContextVar(
    "aib_foreground_lock_attempt", default=None)


class CommandLock:
    """An asyncio.Lock adapter; only explicitly scoped first entry is bounded."""

    def __init__(self, lock: asyncio.Lock | None = None):
        self._lock = lock if lock is not None else asyncio.Lock()
        self.waiting_commands = 0

    def locked(self) -> bool:
        return self._lock.locked()

    async def acquire(self) -> bool:
        attempt = _ATTEMPT.get()
        if (attempt is None or attempt.owner is not asyncio.current_task()
                or attempt.entered):
            # Autosave/shutdown and later critical sections are not cancelled.
            return await self._lock.acquire()
        self.waiting_commands += 1
        try:
            await asyncio.wait_for(self._lock.acquire(), attempt.wait_seconds)
        except TimeoutError:
            raise HTTPException(409, {
                "code": "browser_busy_before_start",
                "outcome": "not_started",
                "queued": False,
                "automatic_retry_safe": False,
                "retry_after_seconds": math.ceil(attempt.wait_seconds),
                "message": "Przeglądarka wykonuje inne polecenie. To polecenie nie rozpoczęło się i nie pozostaje w kolejce. Sprawdź runtime_status przed dalszym działaniem.",
            }) from None
        finally:
            self.waiting_commands -= 1
        attempt.entered = True
        return True

    def release(self) -> None:
        self._lock.release()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.release()
        return False


def bounded_entry(function: Callable[..., Awaitable[Any]],
                  wait_seconds: float = DEFAULT_WAIT_SECONDS):
    """Scope a command; it must not perform writes before its first lock entry."""
    if not isinstance(wait_seconds, (int, float)) or not math.isfinite(wait_seconds) or wait_seconds <= 0:
        raise ValueError("wait_seconds must be finite and positive")

    @functools.wraps(function)
    async def wrapped(*args, **kwargs):
        current = _ATTEMPT.get()
        task = asyncio.current_task()
        if current is not None and current.owner is task:
            return await function(*args, **kwargs)
        token = _ATTEMPT.set(_Attempt(task, float(wait_seconds)))
        try:
            return await function(*args, **kwargs)
        finally:
            _ATTEMPT.reset(token)
    return wrapped


def install_workspace(workspace, wait_seconds: float = DEFAULT_WAIT_SECONDS):
    """Install once at process startup, never on a running/occupied lock."""
    if isinstance(workspace.lock, CommandLock):
        raise RuntimeError("Command admission already installed")
    if workspace.lock.locked():
        raise RuntimeError("Do not replace a live workspace lock")
    methods = {name: getattr(workspace, name) for name in ("action", "screenshot", "tabs")}
    if not all(callable(method) for method in methods.values()):
        raise TypeError("Missing workspace method")
    wrappers = {name: bounded_entry(method, wait_seconds) for name, method in methods.items()}
    lock = CommandLock(workspace.lock)
    workspace.lock = lock
    for name, wrapped in wrappers.items():
        setattr(workspace, name, wrapped)
    return lock
