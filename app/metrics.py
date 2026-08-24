"""Small, bounded application metrics registry."""
import time
from collections import Counter

from app.config import get_settings

settings = get_settings()

REQUEST_COUNT = Counter()
REQUEST_DURATION_MS = Counter()


def _increment(counter: Counter, key: tuple, amount: int) -> None:
    """Keep metrics cardinality bounded even for malformed/unmatched paths."""
    if key in counter or len(counter) < settings.metrics_max_series:
        counter[key] += amount


def observe_request(method: str, route: str, status_code: int, started: float) -> None:
    """Record only route templates, never raw URL paths or secret tokens."""
    key = (method, route, str(status_code))
    _increment(REQUEST_COUNT, key, 1)
    _increment(
        REQUEST_DURATION_MS,
        (method, route),
        max(0, int((time.perf_counter() - started) * 1000)),
    )


def snapshot() -> dict:
    return {
        "requests": {"|".join(k): v for k, v in REQUEST_COUNT.items()},
        "duration_ms_total": {"|".join(k): v for k, v in REQUEST_DURATION_MS.items()},
    }
