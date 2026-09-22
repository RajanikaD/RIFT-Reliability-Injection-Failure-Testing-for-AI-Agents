"""Injectable production timing primitives for fault execution."""

import asyncio
import time
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Wall and monotonic time used to create invocation evidence."""

    def now(self) -> datetime:
        """Return the current timezone-aware wall-clock time."""

    def monotonic(self) -> float:
        """Return monotonic time in seconds."""


class Sleeper(Protocol):
    """Delay execution without prescribing an event-loop implementation."""

    async def sleep(self, seconds: float) -> None:
        """Wait for the requested number of seconds."""


class SystemClock:
    """Production clock backed by the Python standard library."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


class AsyncioSleeper:
    """Production sleeper backed by ``asyncio.sleep``."""

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
