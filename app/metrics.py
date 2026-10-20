"""Small, bounded application metrics registry."""
import time
from collections import Counter

from app.config import get_settings

settings = get_settings()

REQUEST_COUNT = Counter()
REQUEST_DURATION_MS = Counter()
STATE_READ_BUCKETS = Counter()
STATE_READ_COUNT = 0
STATE_READ_SUM = 0.0


def _increment(counter: Counter, key: tuple, amount: int) -> None:
    """Keep metrics cardinality bounded even for malformed/unmatched paths."""
    if key in counter or len(counter) < settings.metrics_max_series:
        counter[key] += amount


def observe_request(method: str, route: str, status_code: int, started: float) -> None:
    """Record only route templates, never raw URL paths or secret tokens."""
    global STATE_READ_COUNT, STATE_READ_SUM
    if method == "GET" and route.endswith("/generation-operations/{operation_id}"):
        elapsed = max(0, time.perf_counter()-started)
        STATE_READ_COUNT += 1
        STATE_READ_SUM += elapsed
        for bound in (0.05, 0.1, 0.25, 0.5, 1, 2, 5, float("inf")):
            if elapsed <= bound:
                STATE_READ_BUCKETS[bound] += 1
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


def generation_latency_prometheus():
    name = 'qentry_generation_status_read_seconds'
    lines = [f'# TYPE {name} histogram']
    for bound in (0.05, 0.1, 0.25, 0.5, 1, 2, 5, float('inf')):
        label = '+Inf' if bound == float('inf') else str(bound)
        lines.append(f'{name}_bucket{{le="{label}"}} {STATE_READ_BUCKETS[bound]}')
    lines.extend([f'{name}_count {STATE_READ_COUNT}', f'{name}_sum {STATE_READ_SUM}'])
    return '\n'.join(lines)+'\n'
