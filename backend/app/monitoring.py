"""Bounded, process-local production metrics for the one-worker runtime."""

from __future__ import annotations

import re
import threading
import time
from math import isfinite
from collections import defaultdict


METRICS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
ALLOWED_STATUS_CLASSES = frozenset({"1xx", "2xx", "3xx", "4xx", "5xx", "other"})
_ROUTE_TEMPLATE = re.compile(r"^/[A-Za-z0-9_./{}-]{0,255}$")


def normalize_method(method: object) -> str:
    """Return a bounded method label without preserving arbitrary input."""
    normalized = method.upper() if isinstance(method, str) else ""
    return normalized if normalized in ALLOWED_METHODS else "OTHER"


def normalize_route(route: object) -> str:
    """Accept only a registered, template-shaped route label."""
    if isinstance(route, str) and _ROUTE_TEMPLATE.fullmatch(route):
        return route
    return "unmatched"


def normalize_status_class(status: object) -> str:
    """Reduce a status code to its fixed hundred-series label."""
    if isinstance(status, int) and 100 <= status <= 599:
        return f"{status // 100}xx"
    return "other"


def resolved_route_template(request: object) -> str:
    """Read a framework-resolved template only; never inspect the raw path."""
    scope = getattr(request, "scope", {})
    route = scope.get("route") if isinstance(scope, dict) else None
    return normalize_route(getattr(route, "path", None))


def _label_text(labels: tuple[str, str, str]) -> str:
    method, route, status_class = labels
    return f'method="{method}",route="{route}",status_class="{status_class}"'


class MetricsRegistry:
    """Small lock-protected registry with fixed names and bounded labels."""

    def __init__(self) -> None:
        self._started_at = time.time()
        self._started_monotonic = time.monotonic()
        self._http: dict[tuple[str, str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
        self._lock = threading.RLock()

    @property
    def process_start_time_seconds(self) -> float:
        return self._started_at

    def process_uptime_seconds(self) -> float:
        return max(0.0, time.monotonic() - self._started_monotonic)

    def record_http_request(self, method: object, route: object, status: object, duration_seconds: object) -> None:
        """Record one completed request under the fixed cardinality policy."""
        labels = (normalize_method(method), normalize_route(route), normalize_status_class(status))
        duration = float(duration_seconds) if isinstance(duration_seconds, (int, float)) else 0.0
        duration = duration if isfinite(duration) else 0.0
        duration = max(0.0, duration)
        with self._lock:
            values = self._http[labels]
            values[0] += 1.0
            values[1] += duration

    def render(self, *, retry_manager_running: object) -> str:
        """Render a Prometheus-compatible exposition without external I/O."""
        retry_value = 1 if retry_manager_running is True else 0
        with self._lock:
            buckets = [(labels, values[0], values[1]) for labels, values in sorted(self._http.items())]
        lines = [
            "# HELP etm_process_start_time_seconds Unix time when this process-local registry started.",
            "# TYPE etm_process_start_time_seconds gauge",
            f"etm_process_start_time_seconds {self.process_start_time_seconds:.6f}",
            "# HELP etm_process_uptime_seconds Monotonic process-local uptime.",
            "# TYPE etm_process_uptime_seconds gauge",
            f"etm_process_uptime_seconds {self.process_uptime_seconds():.6f}",
            "# HELP etm_retry_manager_running Whether the process-local retry manager is running.",
            "# TYPE etm_retry_manager_running gauge",
            f"etm_retry_manager_running {retry_value}",
            "# HELP etm_http_requests_total Completed HTTP requests excluding metrics scrapes.",
            "# TYPE etm_http_requests_total counter",
            "# HELP etm_http_request_duration_seconds_count Completed request duration observations.",
            "# TYPE etm_http_request_duration_seconds_count counter",
            "# HELP etm_http_request_duration_seconds_sum Cumulative completed request duration seconds.",
            "# TYPE etm_http_request_duration_seconds_sum counter",
        ]
        for labels, count, duration_sum in buckets:
            label_text = _label_text(labels)
            lines.extend((
                f"etm_http_requests_total{{{label_text}}} {count:.0f}",
                f"etm_http_request_duration_seconds_count{{{label_text}}} {count:.0f}",
                f"etm_http_request_duration_seconds_sum{{{label_text}}} {duration_sum:.9f}",
            ))
        return "\n".join(lines) + "\n"


metrics_registry = MetricsRegistry()
