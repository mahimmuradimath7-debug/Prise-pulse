"""Real-time demand aggregation: 5-minute windows sliding every 1 minute + flash-sale detection.

This is a lightweight in-process stand-in for the Kafka/Flink job described in the project brief:
same logic (sliding-window counts, baseline comparison, complex-event style spike rule),
no external infrastructure needed to run the demo.
"""
from __future__ import annotations

import threading
import time
from collections import deque

import numpy as np

WINDOW = 300     # 5 minutes
SLIDE = 60       # 1 minute
BASE_SPAN = 3300 # baseline = previous 55 minutes
MIN_ORDERS = 10
RATIO_TRIGGER = 3.0


class DemandStream:
    def __init__(self):
        self.events: dict[str, deque] = {}
        self.lock = threading.Lock()

    def add(self, sku: str, qty: int = 1, ts: float | None = None):
        ts = ts or time.time()
        with self.lock:
            self.events.setdefault(sku, deque()).append((ts, qty))

    def backfill(self, sku: str, rate_per_5min: float, rng, minutes: int = 60):
        now = time.time()
        n = rng.poisson(rate_per_5min * minutes / 5)
        ts = np.sort(now - rng.uniform(0, minutes * 60, n))
        with self.lock:
            dq = self.events.setdefault(sku, deque())
            dq.extend((float(t), 1) for t in ts)

    def _prune(self, dq, now):
        while dq and dq[0][0] < now - (BASE_SPAN + WINDOW + 120):
            dq.popleft()

    def _count(self, dq, start, end):
        return sum(q for t, q in dq if start < t <= end)

    def status(self, sku: str, now: float | None = None) -> dict:
        now = now or time.time()
        with self.lock:
            dq = self.events.setdefault(sku, deque())
            self._prune(dq, now)
            cur = self._count(dq, now - WINDOW, now)
            base_total = self._count(dq, now - WINDOW - BASE_SPAN, now - WINDOW)
        baseline = base_total / (BASE_SPAN / WINDOW)
        ratio = cur / max(baseline, 1.0)
        flash = cur >= MIN_ORDERS and ratio >= RATIO_TRIGGER
        mult = float(min(1.25, 1 + 0.04 * ratio)) if flash else 1.0
        return dict(sku=sku, window_orders=int(cur), baseline=round(baseline, 2), ratio=round(ratio, 2),
                    flash=bool(flash), multiplier=round(mult, 3))

    def all_status(self, skus, now=None):
        return [self.status(s, now) for s in skus]

    def timeline(self, sku: str, minutes: int = 30, now: float | None = None):
        """Sliding-window series: for each 1-minute slide, orders in the trailing 5 minutes."""
        now = now or time.time()
        with self.lock:
            dq = list(self.events.get(sku, []))
        out = []
        for m in range(minutes, -1, -1):
            end = now - m * SLIDE
            c = sum(q for t, q in dq if end - WINDOW < t <= end)
            out.append(dict(minutes_ago=m, orders=int(c)))
        return out
