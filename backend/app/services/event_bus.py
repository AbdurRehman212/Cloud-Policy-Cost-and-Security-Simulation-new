"""Module 4 Part H — Lightweight event-driven simulation core.

A minimal, timestamp-ordered event queue that coexists with the real-time
simulation loop. The simulator publishes `workload_update` and `metric_update`
events each tick; the control-plane publishes `scaling_decision` events when
it acts. Consumers drain the queue in-order to build deterministic replays
or feed downstream analytics without changing the existing realtime path.

Design constraints
------------------
* Non-blocking: the loop must never await the event bus.
* Bounded: each org has a capped ring-buffer of the most recent events.
* Thread-safe: a single lock guards enqueue/drain.
* Efficient: heap push/pop are O(log n); drain is O(k log n) for k events.
"""

from __future__ import annotations

import heapq
import itertools
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

# Event types emitted across the platform (string literals kept for stability).
EVENT_WORKLOAD_UPDATE = "workload_update"
EVENT_METRIC_UPDATE = "metric_update"
EVENT_SCALING_DECISION = "scaling_decision"

_VALID_EVENTS = {EVENT_WORKLOAD_UPDATE, EVENT_METRIC_UPDATE, EVENT_SCALING_DECISION}


@dataclass(order=True)
class _HeapItem:
    """Internal heap entry. Ordered by (timestamp, seq) for stable ordering."""
    timestamp: float
    seq: int
    event: dict = field(compare=False)


class EventBus:
    """Timestamp-ordered event queue with per-org bounded history."""

    def __init__(self, history_limit: int = 500):
        self._heap: list[_HeapItem] = []
        self._seq = itertools.count()
        self._lock = Lock()
        self._history_limit = history_limit
        # Per-org ring-buffer of recent events for introspection/dashboards.
        self._history: dict[int, deque] = defaultdict(
            lambda: deque(maxlen=self._history_limit)
        )

    def publish(
        self,
        event_type: str,
        org_id: int,
        payload: dict[str, Any] | None = None,
        *,
        timestamp: float | None = None,
    ) -> None:
        """Schedule an event. `timestamp` defaults to now, enabling simulation time."""
        if event_type not in _VALID_EVENTS:
            # Soft-validate so we fail fast on typos but keep API stable.
            raise ValueError(f"Unknown event_type: {event_type!r}")
        ts = timestamp if timestamp is not None else time.time()
        event = {
            "type": event_type,
            "org_id": org_id,
            "timestamp": ts,
            "payload": payload or {},
        }
        item = _HeapItem(timestamp=ts, seq=next(self._seq), event=event)
        with self._lock:
            heapq.heappush(self._heap, item)
            self._history[org_id].append(event)

    def drain_due(self, until_timestamp: float | None = None) -> list[dict]:
        """Pop and return all events with `timestamp <= until_timestamp`.

        Defaults to draining every event that has accumulated so far.
        """
        cutoff = until_timestamp if until_timestamp is not None else time.time()
        drained: list[dict] = []
        with self._lock:
            while self._heap and self._heap[0].timestamp <= cutoff:
                drained.append(heapq.heappop(self._heap).event)
        return drained

    def recent(self, org_id: int, limit: int = 50) -> list[dict]:
        """Return the most recent `limit` events for the org (non-destructive)."""
        with self._lock:
            items = list(self._history.get(org_id, ()))
        return items[-limit:]

    def reset(self) -> None:
        with self._lock:
            self._heap.clear()
            self._history.clear()


# Module-level singleton so simulator and control-plane share one bus.
event_bus = EventBus()
