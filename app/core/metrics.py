"""请求指标收集"""

import time
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict

logger = logging.getLogger(__name__)


@dataclass
class EndpointMetrics:
    count: int = 0
    total_time: float = 0.0
    errors: int = 0

    @property
    def avg_time(self) -> float:
        return self.total_time / self.count if self.count else 0


class MetricsCollector:
    """简单的请求指标收集器"""

    def __init__(self):
        self._endpoints: Dict[str, EndpointMetrics] = defaultdict(EndpointMetrics)
        self._start_time = time.time()

    def record(self, path: str, duration: float, status_code: int):
        m = self._endpoints[path]
        m.count += 1
        m.total_time += duration
        if status_code >= 400:
            m.errors += 1

    def get_summary(self) -> dict:
        uptime = time.time() - self._start_time
        total_requests = sum(m.count for m in self._endpoints.values())
        total_errors = sum(m.errors for m in self._endpoints.values())

        top_endpoints = sorted(
            self._endpoints.items(), key=lambda x: x[1].count, reverse=True
        )[:10]

        return {
            "uptime_seconds": round(uptime, 1),
            "total_requests": total_requests,
            "total_errors": total_errors,
            "error_rate": (
                round(total_errors / total_requests, 4) if total_requests else 0
            ),
            "top_endpoints": [
                {
                    "path": path,
                    "count": m.count,
                    "avg_ms": round(m.avg_time * 1000, 1),
                    "errors": m.errors,
                }
                for path, m in top_endpoints
            ],
        }


# 全局实例
metrics = MetricsCollector()
