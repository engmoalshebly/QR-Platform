"""Shared timeout and retry helpers for external dependencies."""
import asyncio
import functools
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)


async def with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    name: str,
    timeout: float = 10.0,
    attempts: int = 3,
    base_delay: float = 0.25,
) -> T:
    """Run an async operation with bounded timeout and exponential backoff."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await asyncio.wait_for(operation(), timeout=timeout)
        except Exception as exc:
            last_error = exc
            if attempt == attempts:
                break
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, base_delay)
            logger.warning("external operation failed name=%s attempt=%d/%d retry_in=%.2fs error=%s", name, attempt, attempts, delay, type(exc).__name__)
            await asyncio.sleep(delay)
    assert last_error is not None
    raise last_error


def sync_with_retry(operation: Callable[[], T], *, name: str, timeout: float = 10.0, attempts: int = 3, base_delay: float = 0.25) -> T:
    """Bounded retry for blocking SDK operations, intended for to_thread."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt == attempts:
                break
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, base_delay)
            logger.warning("external operation failed name=%s attempt=%d/%d retry_in=%.2fs error=%s", name, attempt, attempts, delay, type(exc).__name__)
            import time
            time.sleep(delay)
    assert last_error is not None
    raise last_error
