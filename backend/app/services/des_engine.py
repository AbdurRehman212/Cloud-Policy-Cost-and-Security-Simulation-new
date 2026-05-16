"""Discrete Event Simulation (DES) core engine.

Architecture overview
---------------------
                        ┌──────────────────────────────────────┐
  Workload (demand)     │  VMDESSimulator  (one per running VM) │
  ─────────────────►    │  ┌────────────────────────────────┐  │
  rps, pattern,         │  │  SimEvent heap (time-ordered)  │  │
  service_time          │  │                                │  │
                        │  │  t0: REQUEST_ARRIVAL           │  │
                        │  │    queue += incoming_work_ms   │  │
                        │  │    latency = st + q/rate ← emergent
                        │  │                                │  │
                        │  │  t1: SERVICE_COMPLETE          │  │
                        │  │    queue -= drain_capacity_ms  │  │
                        │  └────────────────────────────────┘  │
  Control plane         │  ← queue_ms, latency, p95, dropped   │
  ─────────────────◄    └──────────────────────────────────────┘
  backlog_per_instance

Key causal invariants
---------------------
1. Queue evolves ONLY via arrival and completion events — never via periodic
   subtraction.  (Task 3)
2. Latency is measured at the REQUEST_ARRIVAL event from the queue state at
   that instant — it is emergent, not precomputed.  (Task 4)
3. Tail latency arises from the natural growth of queue_ms when arrivals
   exceed completions — no manual penalty injection.  (Task 4)
4. Processing rate = vcpu × (1 000 ms/s ÷ avg_service_time_ms), so doubling
   vcpu doubles throughput exactly.  (Task 5)
5. The event loop runs forward in simulated time; the wall-clock tick merely
   calls step() to advance by dt_seconds.  (Task 6)

Efficiency guarantee
--------------------
Exactly 2 heap events per VM per tick (1 arrival + 1 completion).
O(1) per VM per tick regardless of RPS. No per-request loops.
"""

from __future__ import annotations

import heapq
import itertools
import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

# ── Event type tokens ─────────────────────────────────────────────────────────
EV_REQUEST_ARRIVAL = "REQUEST_ARRIVAL"
EV_SERVICE_COMPLETE = "SERVICE_COMPLETE"
EV_CONTROL_EVAL = "CONTROL_EVAL"


@dataclass(order=True)
class SimEvent:
    """Heap-orderable simulation event.

    Ordered by (sim_time, seq) so identical-timestamp events process in
    arrival order — arrival always precedes completion within the same tick
    because arrival is scheduled at t_start < t_end == completion.
    """

    sim_time: float
    seq: int
    event_type: str = field(compare=False)
    payload: dict = field(compare=False, default_factory=dict)


@dataclass
class VMQueueState:
    """Single-source-of-truth causal state for one VM's work queue.

    No external dict should shadow these values while the DES is active.
    """

    queue_ms: float = 0.0
    sim_time: float = 0.0
    # Drops counters — cumulative for accounting, last_tick for ALARM logic.
    # Bug #4 fix: control plane must use last_tick (rate-style), not cumulative,
    # otherwise drops_state stays ALARM forever and scale-in is blocked.
    cumulative_dropped: int = 0
    dropped_in_last_tick: int = 0
    latency_history: deque = field(default_factory=lambda: deque(maxlen=200))
    # Bug #5 fix: store the DETERMINISTIC mean (used by control plane to set
    # target_bpi). The stochastic sample lives in last_sample_service_time_ms
    # for observability only — never feeds the control loop's target.
    last_mean_service_time_ms: float = 5.0
    last_sample_service_time_ms: float = 5.0


class VMDESSimulator:
    """Per-VM Discrete Event Simulator implementing M/M/c batch semantics.

    One call to step() per tick per VM.  Internally schedules exactly two
    events — a batch REQUEST_ARRIVAL and a SERVICE_COMPLETE — and then runs
    the event loop forward until the end of the tick window.

    The wall-clock tick loop in resource_simulator.py calls step(); the DES
    returns causal metrics that replace the old manual queue arithmetic.
    """

    MAX_QUEUE_MS = 5_000.0   # 5 s of pending work → drop overflow

    def __init__(self, vm_instance_id: str) -> None:
        self.instance_id = vm_instance_id
        self.state = VMQueueState()
        self._heap: list[SimEvent] = []
        self._seq = itertools.count()

    # ── Internal heap helper ──────────────────────────────────────────────────

    def _push(
        self,
        sim_time: float,
        event_type: str,
        payload: dict | None = None,
    ) -> None:
        ev = SimEvent(
            sim_time=sim_time,
            seq=next(self._seq),
            event_type=event_type,
            payload=payload or {},
        )
        heapq.heappush(self._heap, ev)

    # ── Public API ────────────────────────────────────────────────────────────

    def step(
        self,
        dt_seconds: float,
        rps: float,
        mean_service_time_ms: float,
        sample_service_time_ms: float,
        vcpu: int,
    ) -> dict:
        """Advance simulation by dt_seconds and return causal metrics.

        Bug #3+#5 fix: mean and sample are now distinct parameters.
          - `mean_service_time_ms`   → deterministic; drives processing_rate
                                       (server speed shouldn't oscillate with
                                       the per-tick stochastic batch draw).
          - `sample_service_time_ms` → lognormal sample; drives incoming_work
                                       (batch volume reflects request mix).

        Bug #1 fix: SERVICE_COMPLETE is scheduled BEFORE REQUEST_ARRIVAL at
        the same t_start so the queue drains FIRST, then arrivals measure
        latency against the post-drain queue. Spec Task 2 ordering:
          1. SERVICE_COMPLETE  (drain prior backlog)
          2. REQUEST_ARRIVAL   (admit new work, measure latency emergent)
          3. CONTROL_EVAL      (out of band; control plane runs separately)

        Processing capacity (Task 5):
            processing_rate = vcpu × (1000 / mean_service_time_ms) [ms/s]
            → vcpu=2 vs vcpu=8 yields exact 4× capacity ratio.

        Returns:
            dict with queue_ms, latency_ms, p95_latency_ms, queue_delay_ms,
            dropped, mean_service_time_ms, sample_service_time_ms,
            processing_rate_ms_per_s.
        """
        t_start = self.state.sim_time
        t_end = t_start + dt_seconds

        # Task 5 / Bug #3: processing_rate uses the DETERMINISTIC mean.
        # The server's drain capacity does not change because one batch
        # happened to draw a smaller/larger lognormal sample.
        processing_rate = float(vcpu) * (1_000.0 / max(0.1, mean_service_time_ms))
        drain_capacity_ms = processing_rate * dt_seconds

        # Batch arrival uses the STOCHASTIC sample so demand has variance.
        incoming_work_ms = rps * dt_seconds * sample_service_time_ms

        # Bug #1 fix: ORDER MATTERS. Same timestamp t_start; (sim_time, seq)
        # ordering means the event pushed FIRST pops first. SERVICE_COMPLETE
        # must drain before the new batch lands.
        self._push(t_start, EV_SERVICE_COMPLETE, {"drain_capacity_ms": drain_capacity_ms})
        self._push(t_start, EV_REQUEST_ARRIVAL, {"incoming_work_ms": incoming_work_ms})

        latency_ms = sample_service_time_ms   # default: empty queue
        dropped_this_tick = 0

        # Task 6: event loop — advance until t_end
        while self._heap and self._heap[0].sim_time <= t_end:
            ev = heapq.heappop(self._heap)
            self.state.sim_time = ev.sim_time

            if ev.event_type == EV_SERVICE_COMPLETE:
                # Task 3: queue drains via completion event only.
                # This now runs FIRST in the tick (Bug #1 fix).
                self.state.queue_ms = max(
                    0.0, self.state.queue_ms - ev.payload["drain_capacity_ms"]
                )

            elif ev.event_type == EV_REQUEST_ARRIVAL:
                # Task 4: latency emergent from POST-drain queue depth.
                # waiting_time = queue / processing_rate, latency = service + wait.
                queue_delay_ms = self.state.queue_ms / max(1.0, processing_rate)
                latency_ms = sample_service_time_ms + queue_delay_ms

                # Task 3: queue grows via arrival event only.
                new_queue = self.state.queue_ms + ev.payload["incoming_work_ms"]

                # Task E: overflow → drop (convert ms-overflow back to req count)
                if new_queue > self.MAX_QUEUE_MS:
                    overflow_ms = new_queue - self.MAX_QUEUE_MS
                    dropped_this_tick = int(
                        overflow_ms / max(0.1, sample_service_time_ms)
                    )
                    new_queue = self.MAX_QUEUE_MS

                self.state.queue_ms = new_queue

        self.state.sim_time = t_end

        # Bug #4 fix: track per-tick drops (consumed by drops_state ALARM)
        # and cumulative drops separately (consumed by accounting).
        self.state.dropped_in_last_tick = dropped_this_tick
        self.state.cumulative_dropped += dropped_this_tick

        # Bug #5 fix: cache the MEAN (target-stable) and the SAMPLE separately.
        self.state.last_mean_service_time_ms = mean_service_time_ms
        self.state.last_sample_service_time_ms = sample_service_time_ms

        # Task F: p95 from rolling history (actual samples, not a formula)
        self.state.latency_history.append(latency_ms)
        if len(self.state.latency_history) >= 5:
            p95_latency_ms = float(np.percentile(list(self.state.latency_history), 95))
        else:
            # Cold-start: pessimistic over-estimate until history fills
            p95_latency_ms = latency_ms * 1.5

        # queue_delay at end-of-tick (exported for dashboard)
        final_queue_delay_ms = self.state.queue_ms / max(1.0, processing_rate)

        return {
            "queue_ms": round(self.state.queue_ms, 2),
            "latency_ms": round(latency_ms, 2),
            "p95_latency_ms": round(p95_latency_ms, 2),
            "queue_delay_ms": round(final_queue_delay_ms, 2),
            "dropped": dropped_this_tick,
            # New name made explicit; old key kept as alias for compat.
            "mean_service_time_ms": round(mean_service_time_ms, 3),
            "sample_service_time_ms": round(sample_service_time_ms, 3),
            "avg_service_time_ms": round(mean_service_time_ms, 3),  # legacy alias
            "processing_rate_ms_per_s": round(processing_rate, 2),
        }

    def reset(self) -> None:
        """Clear all state when a VM stops or is terminated."""
        self.state = VMQueueState()
        self._heap.clear()


# ── AWS-aligned scaling metric helpers (Task 1) ───────────────────────────────

def compute_backlog_per_instance(
    queue_total_ms: float,
    avg_service_time_ms: float,
    num_instances: int,
) -> float:
    """Compute backlog-per-instance (BPI) — the AWS target-tracking signal.

    Formula (AWS SQS Target Tracking):
        backlog_per_instance = (queue_total_ms / avg_service_time_ms) / num_instances

    Properties that make this correct for autoscaling:
    - Units: requests per instance (dimensionless ratio).
    - Capacity-proportional: adding instances reduces BPI linearly.
    - Raw queue_total_ms alone is NOT proportional (violates AWS rule #1).

    Example:
        queue = 2 000 ms, service_time = 10 ms, instances = 2
        BPI = (2000/10) / 2 = 100 requests/instance
    """
    backlog_requests = queue_total_ms / max(0.1, avg_service_time_ms)
    return backlog_requests / max(1, num_instances)


def compute_target_bpi(latency_slo_ms: float, avg_service_time_ms: float) -> float:
    """Compute the target BPI that just satisfies the latency SLO.

    Derivation (Little's Law + M/M/c):
        target_bpi = latency_SLO_ms / avg_service_time_ms

    If BPI == target_bpi, then each instance is holding exactly
    (latency_SLO / service_time) requests of backlog — the queue clears in
    exactly one SLO window at steady-state throughput.

    Example:
        SLO = 500 ms, service_time = 10 ms → target_bpi = 50 req/instance
    """
    return latency_slo_ms / max(0.1, avg_service_time_ms)


def compute_desired_capacity(
    queue_total_ms: float,
    avg_service_time_ms: float,
    target_bpi: float,
) -> int:
    """Proportional desired-capacity from queue backlog (target-tracking step).

    desired = ceil(backlog_requests / target_bpi)

    This mirrors AWS Application Auto Scaling target-tracking policy where
    the desired count is directly proportional to the metric value and
    inversely proportional to the target.
    """
    backlog_requests = queue_total_ms / max(0.1, avg_service_time_ms)
    return max(1, math.ceil(backlog_requests / max(0.001, target_bpi)))
