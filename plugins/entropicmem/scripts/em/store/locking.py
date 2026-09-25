"""Portable advisory file locking for EntropicMem (EM-202).

The v2 engine used ``fcntl.flock`` directly, which made
``import memory_engine`` fail on Windows. This module is the single place
that knows how to take an exclusive advisory lock on a file on both
platforms:

* POSIX: ``fcntl.flock(fd, LOCK_EX | LOCK_NB)`` — same mechanism the v2
  engine always used, so locks taken by v2 code, by this module, or by the
  export/import tests interoperate.
* Windows: ``msvcrt.locking(fd, LK_NBLCK, 1)`` on byte 0 — the documented
  portable advisory-lock counterpart; separate handles in one process
  exclude each other, exactly like flock.

Semantics (identical on both platforms, pinned by tests):

* exclusive and advisory (nothing stops a process that ignores the lock);
* cross-process AND cross-handle within a process;
* released by :meth:`FileLock.release`, :meth:`FileLock.close`, or process
  exit (both OSes drop the lock when the handle closes);
* :meth:`FileLock.probe` answers "is somebody holding this lock?" without
  disturbing the holder and without creating the file.

No fcntl/msvcrt import may appear anywhere else in the codebase (a drift
guard test enforces this).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

__all__ = ["FileLock"]

_IS_WINDOWS = os.name == "nt"

if _IS_WINDOWS:  # pragma: no cover - exercised on the Windows CI job
    import msvcrt
else:
    import fcntl

# Byte-range length locked on Windows. msvcrt.locking locks a byte range;
# one byte at offset 0 is enough for a whole-file advisory lock. The range
# may lie beyond EOF, which both LockFile and the CRT allow.
_WIN_LOCK_BYTES = 1


def _try_lock(fd: int) -> bool:
    """Non-blocking exclusive lock attempt. True on success."""
    if _IS_WINDOWS:  # pragma: no cover - exercised on the Windows CI job
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, _WIN_LOCK_BYTES)
        except OSError:
            return False
        return True
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(fd: int) -> None:
    if _IS_WINDOWS:  # pragma: no cover - exercised on the Windows CI job
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, _WIN_LOCK_BYTES)
        except OSError:
            pass  # already released (e.g. by close)
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


class FileLock:
    """Exclusive advisory lock backed by a lock file.

    Constructing opens (and creates, without truncating) the lock file, so
    the path exists from then on — parity with the v2 engine, whose
    ``<db>.lock`` file appeared at construction time. The lock itself is
    only taken by :meth:`acquire`.

    Not thread-safe by itself: callers that share one FileLock across
    threads must serialise (the v2 engine keeps its reentrancy counter
    around it, unchanged).
    """

    def __init__(self, path: "os.PathLike[str] | str") -> None:
        self.path = Path(path)
        # O_RDWR|O_CREAT, no truncate: never destroy another holder's file.
        self._fd: Optional[int] = os.open(
            str(self.path), os.O_RDWR | os.O_CREAT, 0o600
        )
        self._held = False

    @property
    def held(self) -> bool:
        return self._held

    def acquire(
        self,
        blocking: bool = True,
        poll: float = 0.05,
        timeout: Optional[float] = None,
    ) -> bool:
        """Take the lock. Returns True on success, False if unavailable.

        Non-blocking mode tries once. Blocking mode retries every ``poll``
        seconds until ``timeout`` (None = forever). Polling (instead of the
        OS blocking call) keeps the semantics identical on both platforms
        and makes ``timeout`` portable — Windows' LK_LOCK has a fixed
        10-second retry window that cannot be shortened.
        """
        if self._held:
            return True
        if _try_lock(self._fd):  # type: ignore[arg-type]
            self._held = True
            return True
        if not blocking:
            return False
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            time.sleep(poll)
            if _try_lock(self._fd):  # type: ignore[arg-type]
                self._held = True
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False

    def release(self) -> None:
        if not self._held:
            return
        _unlock(self._fd)  # type: ignore[arg-type]
        self._held = False

    def close(self) -> None:
        """Release and close the handle. Safe to call twice."""
        self.release()
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def __enter__(self) -> "FileLock":
        if not self.acquire():
            raise TimeoutError(f"could not acquire lock {self.path}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @staticmethod
    def probe(path: "os.PathLike[str] | str") -> bool:
        """True while *somebody* holds the lock on ``path``.

        Best-effort liveness check (the CLI uses it to refuse capsule
        imports while a provider is running). Never creates the file and
        never disturbs a holder: a missing file means "no lock".
        """
        path = Path(path)
        if not path.exists():
            return False
        fd = os.open(str(path), os.O_RDWR)
        try:
            if _try_lock(fd):
                _unlock(fd)
                return False
            return True
        finally:
            os.close(fd)
