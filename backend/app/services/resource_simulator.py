"""Dataset-backed resource simulator for the cloud digital twin."""

from __future__ import annotations

import math
import random
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from threading import Event, Lock, Thread

import numpy as np
from flask import has_app_context, current_app
from sqlalchemy import func

from app import db, socketio
from app.ai_models.data_generator import SyntheticDataGenerator
from app.services.des_engine import VMDESSimulator
from app.ai_models.remediation_agent import remediation_agent
from app.ai_models.threat_detector import threat_detector
from app.models.cost import CostRecord
from app.models.governance import AuditLog
from app.models.resources import Database, ResourceStatus, VirtualMachine
from app.models.security import (
    RemediationAction,
    SecurityLog,
    ThreatDetection,
    ThreatSeverity,
    ThreatType,
)


class ResourceSimulator:
    """Simulate cloud resources using real dataset patterns and synthetic telemetry."""

    # Instance specs: vcpu, ram (GB), baseline_cpu
    INSTANCE_PROFILES = {
        't2.micro':    {'vcpu': 1, 'ram': 1, 'baseline_cpu': 12.0},
        't2.small':    {'vcpu': 1, 'ram': 2, 'baseline_cpu': 18.0},
        't2.medium':   {'vcpu': 2, 'ram': 4, 'baseline_cpu': 22.0},
        't3.micro':    {'vcpu': 2, 'ram': 1, 'baseline_cpu': 14.0},
        't3.small':    {'vcpu': 2, 'ram': 2, 'baseline_cpu': 20.0},
        't3.medium':   {'vcpu': 2, 'ram': 4, 'baseline_cpu': 25.0},
        'm5.large':    {'vcpu': 2, 'ram': 8, 'baseline_cpu': 35.0},
        'm5.xlarge':   {'vcpu': 4, 'ram': 16, 'baseline_cpu': 42.0},
        'm5.2xlarge':  {'vcpu': 8, 'ram': 32, 'baseline_cpu': 50.0},
        'c5.large':    {'vcpu': 2, 'ram': 4, 'baseline_cpu': 55.0},
        'c5.xlarge':   {'vcpu': 4, 'ram': 8, 'baseline_cpu': 65.0},
        'c5.2xlarge':  {'vcpu': 8, 'ram': 16, 'baseline_cpu': 72.0},
        'r5.large':    {'vcpu': 2, 'ram': 16, 'baseline_cpu': 28.0},
        'r5.xlarge':   {'vcpu': 4, 'ram': 32, 'baseline_cpu': 32.0},
        'r5.2xlarge':  {'vcpu': 8, 'ram': 64, 'baseline_cpu': 38.0},
        'p3.2xlarge':  {'vcpu': 8, 'ram': 61, 'baseline_cpu': 78.0},
        'g4dn.xlarge': {'vcpu': 4, 'ram': 16, 'baseline_cpu': 70.0},
    }

    # Hard cap: max VMs processed per tick. Prevents the sim thread from
    # monopolizing the GIL when the DB has thousands of autoscaled rows.
    MAX_SIM_VMS: int = 12
    # Hard global cap on autoscaled VMs
    MAX_VMS: int = 20
    # Security analysis (ML model call) is expensive — run every N ticks only.
    _SECURITY_ANALYSIS_EVERY_N_TICKS: int = 24

    def __init__(self, tick_interval: int = 5, history_limit: int = 120, seed: int = 1337):
        self.tick_interval = tick_interval
        # Module 4 Part G: explicit simulation time-step in seconds.
        # Kept as an alias of tick_interval so downstream code can reference
        # a self-documenting name; existing callers using tick_interval keep working.
        self.dt_seconds = tick_interval
        self.history_limit = history_limit
        self.seed = seed
        # Runtime-owned RNGs make repeated simulator runs reproducible without
        # mutating process-global random state used by Flask/tests.
        self._rng = random.Random(seed)
        self._np_rng = np.random.default_rng(seed + 1)
        self.running = False
        self.thread = None
        self.stop_event = Event()
        self._lock = Lock()
        self._app = None
        self._generator = None
        self._history_by_org = defaultdict(lambda: deque(maxlen=self.history_limit))
        self._activity_by_org = defaultdict(lambda: deque(maxlen=20))
        # Per-VM metric history: vm_id → deque of {timestamp, cpu, memory}
        self.vm_metric_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=self.history_limit))
        # Per-org aggregated metric history (separate from _history_by_org which includes cost)
        self.org_metric_history: dict[int, deque] = defaultdict(lambda: deque(maxlen=self.history_limit))
        self._tick_count = 0
        self.last_scaled_at: dict[str, datetime] = {}
        self.waste_candidates: set[int] = set()
        # Per-VM spike tracking: vm_id -> remaining spike cycles
        self._spike_cycles: dict[str, int] = {}
        # Per-VM previous CPU (kept for control_plane smoothing, not used in sim)
        self._prev_cpu: dict[str, float] = {}
        # Per-VM RPS history
        self.vm_rps_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=self.history_limit))
        # Per-VM queue state: vm_instance_id -> pending work (ms)
        # Kept for backward-compat with get_org_workload_snapshot; authoritative
        # value is now VMDESSimulator.state.queue_ms — synced after each step().
        self._vm_queue: dict[str, float] = {}
        # Per-VM cumulative dropped requests counter
        self._vm_dropped: dict[str, int] = {}
        # Per-VM rolling latency samples — synced from DES after each step().
        self.vm_latency_samples: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        # DES engine per VM — Tasks 2-6: causal queue + emergent latency.
        self._vm_des: dict[str, VMDESSimulator] = {}

    def _get_generator(self) -> SyntheticDataGenerator:
        if self._generator is None:
            self._generator = SyntheticDataGenerator(seed=self.seed + 2)
        return self._generator

    def start(self, app=None):
        """Start the simulation loop."""
        with self._lock:
            if self.running:
                return

            if app is None and has_app_context():
                app = current_app._get_current_object()

            self._app = app
            if self._app is None:
                print('Resource simulator not started: Flask app context unavailable')
                return

            self.running = True
            self.stop_event.clear()
            self.thread = Thread(target=self._simulation_loop, daemon=True)
            self.thread.start()
            print('Resource simulator started')

    def stop(self):
        """Stop the simulation loop."""
        with self._lock:
            self.running = False
            self.stop_event.set()
            if self.thread:
                self.thread.join(timeout=5)
            print('Resource simulator stopped')

    def _simulation_loop(self):
        """Main simulation loop — daemon thread, never runs inside a Flask request."""
        if self._app is None:
            return

        with self._app.app_context():
            while self.running and not self.stop_event.is_set():
                tick_started = time.monotonic()
                try:
                    self._update_resources()
                except Exception as exc:  # pragma: no cover
                    db.session.rollback()
                    print(f'Simulation error: {exc}')

                _tick_ms = round((time.monotonic() - tick_started) * 1000, 1)
                if _tick_ms > 100:
                    print(f'[PERF] Simulation tick took {_tick_ms} ms')

                # Throttle to a controlled cadence so the GIL is released and
                # Flask request threads stay responsive.
                elapsed = time.monotonic() - tick_started
                target_cadence = max(0.75, min(1.25, self.tick_interval * 0.2))
                sleep_for = max(0.05, target_cadence - elapsed)
                self.stop_event.wait(sleep_for)

    def _update_resources(self):
        """Update a capped subset of running resources with dataset-backed telemetry."""
        # Release any pending transaction before starting so we don't hold a
        # write lock across the entire tick while Flask request threads wait.
        db.session.commit()
        generator = self._get_generator()
        moment = datetime.utcnow()
        tick_started = time.monotonic()

        # ── PERFORMANCE CAP ───────────────────────────────────────────────────
        # Only simulate up to MAX_SIM_VMS VMs per tick. Extra VMs in the DB
        # (old autoscale rows, test data) are skipped to keep ticks < 500 ms.
        # We sort by id so we round-robin through all VMs across ticks.
        _offset = (self._tick_count * self.MAX_SIM_VMS) % max(
            1, VirtualMachine.query.filter_by(status=ResourceStatus.RUNNING).count()
        )
        vms = (
            VirtualMachine.query
            .filter_by(status=ResourceStatus.RUNNING)
            .order_by(VirtualMachine.id)
            .offset(_offset)
            .limit(self.MAX_SIM_VMS)
            .all()
        )
        dbs = Database.query.filter_by(status=ResourceStatus.RUNNING).all()

        vm_count = 0
        for vm in vms:
            metrics = generator.generate_vm_metrics(vm, moment)

            # ── Workload-driven CPU + memory + stochastic queueing ─────────────
            (
                rps, cpu, memory, overload,
                queue_length, latency_ms, dropped,
                avg_service_time, p95_latency, queue_delay,
                service_time_sample,
            ) = self._compute_workload_metrics(vm, moment)

            metrics['cpu_utilization'] = round(cpu, 2)
            metrics['memory_utilization'] = round(memory, 2)
            metrics['overload'] = overload
            metrics['requests_per_second'] = rps
            metrics['queue_length'] = queue_length          # now in work-ms
            metrics['latency_ms'] = latency_ms
            metrics['dropped_requests'] = dropped
            metrics['avg_service_time'] = avg_service_time
            metrics['p95_latency'] = p95_latency
            metrics['queue_delay'] = queue_delay
            # Task 6: new extended metrics
            metrics['service_time_sample'] = service_time_sample
            metrics['latency_samples'] = list(self.vm_latency_samples[vm.instance_id])[-30:]

            # Store per-VM RPS + queue history (extended)
            self.vm_rps_history[vm.instance_id].append({
                'timestamp': moment.isoformat(),
                'rps': rps,
                'overload': overload,
                'queue_length': queue_length,
                'latency_ms': latency_ms,
                'dropped_requests': dropped,
                'avg_service_time': avg_service_time,
                'p95_latency': p95_latency,
                'queue_delay': queue_delay,
                'service_time_sample': service_time_sample,
            })

            # Module 4 Part H: publish event-driven updates for this VM.
            # Uses a lazy import to avoid a module-load cycle with control_plane.
            try:
                from app.services.event_bus import (
                    event_bus,
                    EVENT_WORKLOAD_UPDATE,
                    EVENT_METRIC_UPDATE,
                )
                event_bus.publish(
                    EVENT_WORKLOAD_UPDATE,
                    org_id=vm.organization_id,
                    payload={
                        'vm_id': vm.id,
                        'instance_id': vm.instance_id,
                        'rps': rps,
                        'pattern': (vm.workload_pattern or 'steady'),
                    },
                )
                event_bus.publish(
                    EVENT_METRIC_UPDATE,
                    org_id=vm.organization_id,
                    payload={
                        'vm_id': vm.id,
                        'cpu': cpu,
                        'memory': memory,
                        'queue_length': queue_length,
                        'latency_ms': latency_ms,
                        'p95_latency': p95_latency,
                        'dropped_requests': dropped,
                        'overload': overload,
                    },
                )
            except Exception:  # pragma: no cover - event bus must never break sim
                pass

            vm.cpu_utilization = metrics['cpu_utilization']
            vm.memory_utilization = metrics['memory_utilization']
            vm.disk_read_iops = metrics['disk_read_iops']
            vm.disk_write_iops = metrics['disk_write_iops']
            vm.network_in_mbps = metrics['network_in_mbps']
            vm.network_out_mbps = metrics['network_out_mbps']
            vm.total_runtime_hours += self.tick_interval / 3600
            self._upsert_cost_record(vm, 'vm', moment, metrics)
            # Security analysis is ML-heavy; run only every N ticks to stay fast.
            if (
                self._tick_count % self._SECURITY_ANALYSIS_EVERY_N_TICKS == 0
                and (time.monotonic() - tick_started) < 0.08
            ):
                self._analyze_vm_security(vm, moment)

            # Store per-VM metric history point (extended)
            self.vm_metric_history[vm.instance_id].append({
                'timestamp': moment.isoformat(),
                'name': moment.strftime('%H:%M'),
                'cpu': metrics['cpu_utilization'],
                'memory': metrics['memory_utilization'],
                'network_in': round(float(vm.network_in_mbps or 0), 2),
                'network_out': round(float(vm.network_out_mbps or 0), 2),
                'disk_read': round(float(vm.disk_read_iops or 0), 2),
                'disk_write': round(float(vm.disk_write_iops or 0), 2),
            })
            # Yield GIL briefly after each VM so Flask threads can be scheduled.
            self.stop_event.wait(0.001)
            # Commit every 10 VMs to keep transactions short.
            vm_count += 1
            if vm_count % 10 == 0:
                db.session.commit()

        for database in dbs:
            metrics = generator.generate_database_metrics(database, moment)
            database.cpu_utilization = metrics['cpu_utilization']
            database.memory_utilization = metrics.get('memory_utilization', 0.0)
            database.database_connections = metrics['database_connections']
            database.read_iops = metrics['read_iops']
            database.write_iops = metrics['write_iops']
            database.free_storage_space = metrics['free_storage_space']
            database.total_runtime_hours += self.tick_interval / 3600
            self._upsert_cost_record(database, 'database', moment, metrics)

        # Handle stopped VMs: cpu=0, memory=0
        stopped_vms = VirtualMachine.query.filter(
            VirtualMachine.status.in_([ResourceStatus.STOPPED, ResourceStatus.TERMINATED, ResourceStatus.FAILED])
        ).all()
        for vm in stopped_vms:
            vm.cpu_utilization = 0.0
            vm.memory_utilization = 0.0
            vm.disk_read_iops = 0.0
            vm.disk_write_iops = 0.0
            vm.network_in_mbps = 0.0
            vm.network_out_mbps = 0.0
            # Clear spike, prev_cpu, queue, DES engine and latency samples
            self._spike_cycles.pop(vm.instance_id, None)
            self._prev_cpu.pop(vm.instance_id, None)
            self._vm_queue.pop(vm.instance_id, None)
            self._vm_dropped.pop(vm.instance_id, None)
            self.vm_latency_samples.pop(vm.instance_id, None)
            # Reset DES engine so it starts fresh if VM restarts
            des = self._vm_des.pop(vm.instance_id, None)
            if des:
                des.reset()

        db.session.commit()

        # Emit resource_update events for each org with running resources
        # Query DB for current states to ensure consistency
        org_ids = {vm.organization_id for vm in vms} | {database.organization_id for database in dbs}
        total_vms_by_org = {}
        running_vms_by_org = {}
        if org_ids:
            total_vms_by_org = dict(
                db.session.query(
                    VirtualMachine.organization_id,
                    func.count(VirtualMachine.id),
                )
                .filter(
                    VirtualMachine.organization_id.in_(org_ids),
                    VirtualMachine.status != ResourceStatus.TERMINATED,
                )
                .group_by(VirtualMachine.organization_id)
                .all()
            )
            running_vms_by_org = dict(
                db.session.query(
                    VirtualMachine.organization_id,
                    func.count(VirtualMachine.id),
                )
                .filter(
                    VirtualMachine.organization_id.in_(org_ids),
                    VirtualMachine.status == ResourceStatus.RUNNING,
                )
                .group_by(VirtualMachine.organization_id)
                .all()
            )

        for org_id in org_ids:
            org_vms = [v for v in vms if v.organization_id == org_id]
            org_dbs = [d for d in dbs if d.organization_id == org_id]
            all_running = org_vms + org_dbs

            if all_running:
                cpu_avg = sum(float(r.cpu_utilization or 0) for r in all_running) / len(all_running)
                memory_avg = sum(float(r.memory_utilization or 0) for r in all_running) / len(all_running)
            else:
                cpu_avg = 0.0
                memory_avg = 0.0
            
            socketio.emit(
                'resource_update',
                {
                    'total_vms': int(total_vms_by_org.get(org_id, 0)),
                    'running_vms': int(running_vms_by_org.get(org_id, 0)),
                    'cpu_avg': round(cpu_avg, 2),
                    'memory_avg': round(memory_avg, 2),
                },
                room=f'org_{org_id}',
                namespace='/metrics'
            )

        self._tick_count += 1
        # Store per-org aggregated metric history point
        org_ids = {vm.organization_id for vm in vms} | {database.organization_id for database in dbs}
        for org_id in org_ids:
            org_vms = [v for v in vms if v.organization_id == org_id]
            org_dbs = [d for d in dbs if d.organization_id == org_id]
            cpu_vals = [v.cpu_utilization for v in org_vms] + [d.cpu_utilization for d in org_dbs]
            mem_vals = [v.memory_utilization for v in org_vms] + [
                min(98.0, max(5.0, d.cpu_utilization * 1.35 + d.database_connections * 0.65))
                for d in org_dbs
            ]
            self.org_metric_history[org_id].append({
                'timestamp': moment.isoformat(),
                'name': moment.strftime('%H:%M'),
                'cpu': round(float(np.mean(cpu_vals)) if cpu_vals else 0.0, 2),
                'memory': round(float(np.mean(mem_vals)) if mem_vals else 0.0, 2),
            })
            self._record_org_snapshot(org_id, moment)
            self._append_activity(
                org_id,
                title='Synthetic telemetry refreshed',
                severity='info',
                details=f'Updated {len(vms)} VM(s) and {len(dbs)} database(s) from the simulator.',
                moment=moment,
            )

    # ── Queue model constants (work-ms) ──────────────────────────────────────
    _QUEUE_THRESHOLD_MS = 1000.0   # 1s of backlog → overload flag
    _MAX_QUEUE_MS = 5000.0         # 5s of backlog → requests dropped
    _BASE_LATENCY_MS = 20.0        # minimum service latency (legacy)
    # Legacy aliases (referenced by _workload_explanation_for_org)
    _QUEUE_THRESHOLD = _QUEUE_THRESHOLD_MS
    _MAX_QUEUE = _MAX_QUEUE_MS

    # ── Task 1: Lognormal sigma per workload pattern ──────────────────────────
    _SERVICE_TIME_SIGMA = {
        'steady':  0.15,  # tight distribution
        'spiky':   0.45,  # still bursty, but not stress-test sharp
        'diurnal': 0.3,   # moderate variance
    }
    _DEFAULT_SIGMA = 0.3

    # ── Workload capacity table (max rps at 100% CPU) ────────────────────────
    RPS_CAPACITY = {
        't2.micro':   50,
        't2.small':  100,
        't2.medium': 200,
        't2.large':  400,
        't2.xlarge': 800,
    }
    _DEFAULT_CAPACITY = 200

    # ── Task 1: Baseline service time per instance type (ms per request) ──────
    # service_time = 1000 / capacity  (ms to process one request at full speed)
    # Stored explicitly so heavier instances serve requests faster.
    _BASE_SERVICE_TIME_MS = {
        't2.micro':    15.0,
        't2.small':     8.0,
        't2.medium':    3.8,
        't2.large':     2.0,
        't2.xlarge':    1.0,
    }
    _DEFAULT_SERVICE_TIME_MS = 5.0

    # ── Task 2: Request cost variability per workload pattern ─────────────────
    # Defines (light_pct, heavy_pct, light_multiplier, heavy_multiplier)
    # light requests finish faster; heavy requests take longer.
    _REQUEST_MIX = {
        'steady':  {'light': 0.70, 'heavy': 0.30, 'light_factor': 0.65, 'heavy_factor': 2.0},
        'spiky':   {'light': 0.40, 'heavy': 0.60, 'light_factor': 0.60, 'heavy_factor': 2.0},
        'diurnal': {'light': 0.65, 'heavy': 0.35, 'light_factor': 0.75, 'heavy_factor': 1.8},
    }
    _DEFAULT_MIX = {'light': 0.60, 'heavy': 0.40, 'light_factor': 0.65, 'heavy_factor': 2.0}

    # ── Learning text per pattern ─────────────────────────────────────────────
    _WORKLOAD_LEARNING = {
        'steady': {
            'effect': 'Stable CPU with small random fluctuations',
            'learning': 'Steady workloads are predictable; right-size the instance type.',
        },
        'spiky': {
            'effect': 'CPU spikes due to burst traffic',
            'learning': 'Auto-scaling is needed for burst workloads.',
        },
        'diurnal': {
            'effect': 'CPU follows a day/night sinusoidal curve',
            'learning': 'Scheduled scaling saves cost during off-peak hours.',
        },
    }

    @classmethod
    def _avg_service_time_ms(cls, instance_type, pattern):
        """Task 1+2: Compute weighted avg service time (ms) from request cost mix."""
        base_st = cls._BASE_SERVICE_TIME_MS.get(instance_type or '', cls._DEFAULT_SERVICE_TIME_MS)
        mix = cls._REQUEST_MIX.get((pattern or 'steady').lower(), cls._DEFAULT_MIX)
        avg_st = base_st * (
            mix['light'] * mix['light_factor'] + mix['heavy'] * mix['heavy_factor']
        )
        return avg_st  # ms per request

    def _compute_workload_metrics(self, vm, moment):
        """Return (effective_rps, cpu_pct, memory_pct, overload, queue_length,
                   latency_ms, dropped, avg_service_time, p95_latency, queue_delay)
        driven by VM workload model with service-time-aware queueing."""
        base_rps = int(vm.requests_per_second or 50)
        pattern = (vm.workload_pattern or 'steady').lower()
        instance_type = vm.instance_type or ''
        capacity = self.RPS_CAPACITY.get(instance_type, self._DEFAULT_CAPACITY)
        profile = self.INSTANCE_PROFILES.get(instance_type, {'ram': 4})
        base_mem_pct = profile.get('ram', 4) * 5.0

        # ── Pattern modulation ────────────────────────────────────────────────
        if pattern == 'steady':
            fluctuation = self._rng.uniform(-0.03, 0.03)
            effective_rps = max(1, int(base_rps * (1 + fluctuation)))

        elif pattern == 'spiky':
            spike_key = vm.instance_id
            if spike_key in self._spike_cycles:
                if self._spike_cycles[spike_key] > 0:
                    effective_rps = int(base_rps * self._rng.uniform(1.2, 1.5))
                    self._spike_cycles[spike_key] -= 1
                else:
                    del self._spike_cycles[spike_key]
                    effective_rps = max(1, int(base_rps * self._rng.uniform(0.97, 1.03)))
            else:
                if self._rng.random() < 0.03:
                    effective_rps = int(base_rps * self._rng.uniform(1.2, 1.5))
                    self._spike_cycles[spike_key] = 1
                else:
                    effective_rps = max(1, int(base_rps * self._rng.uniform(0.97, 1.03)))

        else:  # diurnal
            hour_frac = moment.hour + moment.minute / 60.0
            sinusoid = math.sin((hour_frac / 24.0 - 0.25) * 2 * math.pi)
            scale = 0.5 + 0.5 * sinusoid
            noise = self._rng.gauss(0, 0.04)
            scale = max(0.0, min(1.0, scale + noise))
            effective_rps = max(1, int(base_rps * (0.3 + 0.7 * scale)))

        # ── Service time (mean) ──────────────────────────────────────────────────
        avg_st_ms = self._avg_service_time_ms(instance_type, pattern)

        # ── Task 1: Stochastic per-tick service-time sample (lognormal) ───────
        sigma = self._SERVICE_TIME_SIGMA.get(pattern, self._DEFAULT_SIGMA)
        # lognormal parameterised so that E[X] == avg_st_ms:
        #   mu = ln(mean) - sigma^2 / 2
        mu = math.log(max(avg_st_ms, 0.1)) - (sigma ** 2) / 2.0
        service_time_sample = float(self._np_rng.lognormal(mean=mu, sigma=sigma))
        # clamp to sane bounds (10x mean max)
        service_time_sample = max(0.1, min(avg_st_ms * 10.0, service_time_sample))

        # ── DES: causal queue + emergent latency (Tasks 2, 3, 4, 5, 6) ─────────
        # vcpu drives processing_rate = vcpu × (1000 / service_time_ms) [Task 5]
        cores = max(1, int(profile.get('vcpu', 1) or 1))
        incoming_rate = float(effective_rps)  # retained for CPU calc below

        # Obtain (or create) the per-VM DES engine.
        if vm.instance_id not in self._vm_des:
            self._vm_des[vm.instance_id] = VMDESSimulator(vm.instance_id)
        des = self._vm_des[vm.instance_id]

        # Bug #1+#3+#5 fix: step() now takes mean (→ processing_rate) and
        # sample (→ incoming_work) separately. SERVICE_COMPLETE schedules
        # before REQUEST_ARRIVAL inside step() so drain happens first.
        des_out = des.step(
            dt_seconds=self.dt_seconds,
            rps=incoming_rate,
            mean_service_time_ms=avg_st_ms,            # deterministic
            sample_service_time_ms=service_time_sample,  # lognormal draw
            vcpu=cores,
        )

        current_queue = des_out["queue_ms"]
        latency_ms = des_out["latency_ms"]
        p95_latency = des_out["p95_latency_ms"]
        queue_delay = des_out["queue_delay_ms"]
        dropped = des_out["dropped"]

        # Sync shared-state dicts so get_org_workload_snapshot still works.
        self._vm_queue[vm.instance_id] = current_queue
        # Bug #4 fix: _vm_dropped now stores LAST-TICK drops (rate-style),
        # not cumulative. Cumulative is still tracked inside DES state for
        # accounting and exposed separately via the workload snapshot.
        self._vm_dropped[vm.instance_id] = des.state.dropped_in_last_tick
        # Point the deque alias at the DES's own history (zero-copy sync).
        self.vm_latency_samples[vm.instance_id] = des.state.latency_history

        # ── Overload via ms-queue threshold ──────────────────────────────────
        overload = current_queue > self._QUEUE_THRESHOLD_MS

        # ── CPU: derived from DES processing utilisation ──────────────────────
        # processing_utilisation = incoming_work_ms / drain_capacity_ms
        # This is causally correct: CPU reflects how much of the tick's
        # processing capacity was consumed by arriving work.
        incoming_work_ms = incoming_rate * self.dt_seconds * service_time_sample
        drain_capacity_ms = des_out["processing_rate_ms_per_s"] * self.dt_seconds
        if drain_capacity_ms > 0:
            cpu = min(100.0, (incoming_work_ms / drain_capacity_ms) * 100.0)
        else:
            cpu = 0.0
        cpu = round(max(0.0, min(100.0, cpu)), 2)

        # ── Decoupled memory model ────────────────────────────────────────────
        workload_factor = min(8.0, (incoming_rate / max(1, capacity)) * 5.0)
        memory = base_mem_pct + (cpu * 0.35) + workload_factor + self._rng.gauss(0, 1.8)
        memory = round(max(0.0, min(100.0, memory)), 2)

        return (
            effective_rps, cpu, memory, overload,
            round(current_queue, 2), latency_ms, dropped,
            round(avg_st_ms, 3), p95_latency, queue_delay,
            round(service_time_sample, 3),
        )

    def _usage_factor(self, metrics, kind='vm'):
        cpu = float(metrics.get('cpu_utilization', 0) or 0)
        memory = float(metrics.get('memory_utilization', 0) or 0)
        network_in = float(metrics.get('network_in_mbps', 0) or 0)
        network_out = float(metrics.get('network_out_mbps', 0) or 0)
        base = 0.35 if kind == 'vm' else 0.30
        usage = base + (cpu / 100.0) * 0.55 + (memory / 100.0) * 0.25
        usage += min(0.25, (network_in + network_out) / 2000.0)
        return max(0.25, usage)

    def _upsert_cost_record(self, resource, resource_type, moment, metrics):
        hourly_increment = resource.hourly_rate * self._usage_factor(metrics, resource_type) * (
            self.tick_interval / 3600
        )
        record = CostRecord.query.filter_by(
            organization_id=resource.organization_id,
            resource_id=resource.instance_id,
            resource_type=resource_type,
            date=moment.date(),
            hour=moment.hour,
        ).first()
        if record is None:
            record = CostRecord(
                organization_id=resource.organization_id,
                resource_id=resource.instance_id,
                resource_type=resource_type,
                date=moment.date(),
                hour=moment.hour,
                compute_cost=0.0,
                storage_cost=0.0,
                network_cost=0.0,
                total_cost=0.0,
                cpu_avg=0.0,
                memory_avg=0.0,
            )
            db.session.add(record)

        record.compute_cost = round((record.compute_cost or 0.0) + hourly_increment * 0.72, 6)
        record.storage_cost = round((record.storage_cost or 0.0) + hourly_increment * 0.18, 6)
        record.network_cost = round((record.network_cost or 0.0) + hourly_increment * 0.10, 6)
        record.total_cost = round((record.total_cost or 0.0) + hourly_increment, 6)
        record.cpu_avg = float(metrics.get('cpu_utilization', 0) or 0)
        record.memory_avg = float(metrics.get('memory_utilization', 0) or 0)
        record.timestamp = moment

    def _build_vm_traffic_metrics(self, vm):
        cpu = float(vm.cpu_utilization or 0)
        memory = float(vm.memory_utilization or 0)
        network_in = float(vm.network_in_mbps or 0)
        network_out = float(vm.network_out_mbps or 0)
        requests_per_minute = int(max(120, network_in * 14 + cpu * 24 + self._rng.uniform(0, 100)))
        avg_latency_ms = round(max(15.0, 30 + cpu * 1.8 + network_out * 0.3 + self._rng.uniform(-4, 18)), 2)
        error_rate = round(min(0.35, max(0.002, (cpu / 100.0) * 0.05 + self._rng.uniform(0.0, 0.01))), 4)
        auth_failures = int(max(0, (cpu - 70) / 5 + self._rng.uniform(0, 4))) if cpu > 70 else int(self._rng.uniform(0, 2))

        return {
            'requests_per_minute': requests_per_minute,
            'avg_latency_ms': avg_latency_ms,
            'error_rate': error_rate,
            'bytes_in': int(network_in * 125000),
            'bytes_out': int(network_out * 125000),
            'active_connections': int(max(1, network_in / 2 + cpu * 0.8)),
            'cpu_utilization': cpu,
            'memory_utilization': memory,
            'disk_read_iops': float(vm.disk_read_iops or 0),
            'disk_write_iops': float(vm.disk_write_iops or 0),
            'network_in_mbps': network_in,
            'network_out_mbps': network_out,
            'auth_failures': auth_failures,
        }

    def _map_threat_type(self, label):
        normalized = (label or '').lower()
        return {
            'ddos': ThreatType.DDoS,
            'brute_force': ThreatType.BRUTE_FORCE,
            'port_scan': ThreatType.PORT_SCAN,
            'sql_injection': ThreatType.SQL_INJECTION,
            'xss': ThreatType.XSS,
            'malware': ThreatType.MALWARE,
            'unauthorized_access': ThreatType.UNAUTHORIZED_ACCESS,
            'privilege_escalation': ThreatType.PRIVILEGE_ESCALATION,
            'data_exfiltration': ThreatType.DATA_EXFILTRATION,
            'suspicious_behavior': ThreatType.SUSPICIOUS_BEHAVIOR,
        }.get(normalized, ThreatType.SUSPICIOUS_BEHAVIOR)

    def _severity_from_confidence(self, confidence):
        if confidence >= 0.95:
            return ThreatSeverity.CRITICAL
        if confidence >= 0.82:
            return ThreatSeverity.HIGH
        if confidence >= 0.7:
            return ThreatSeverity.MEDIUM
        return ThreatSeverity.LOW

    def _threat_recent(self, vm, threat_type, moment):
        recent_cutoff = moment - timedelta(minutes=30)
        recent = ThreatDetection.query.filter(
            ThreatDetection.organization_id == vm.organization_id,
            ThreatDetection.detected_at >= recent_cutoff,
        ).order_by(ThreatDetection.detected_at.desc()).limit(10).all()
        for threat in recent:
            affected = threat.affected_resources or []
            if threat.threat_type == threat_type and vm.instance_id in affected and threat.status == 'active':
                return True
        return False

    def _analyze_vm_security(self, vm, moment):
        if threat_detector is None:
            return

        metrics = self._build_vm_traffic_metrics(vm)
        result = threat_detector.real_time_monitor(metrics)
        if not result.get('is_threat'):
            return

        threat_type = self._map_threat_type(result.get('threat_type'))
        if self._threat_recent(vm, threat_type, moment):
            return

        severity = self._severity_from_confidence(result.get('confidence', 0.0))
        threat = ThreatDetection(
            organization_id=vm.organization_id,
            threat_type=threat_type,
            severity=severity,
            confidence_score=float(result.get('confidence', 0.0)),
            affected_resources=[vm.instance_id],
            attack_vectors={
                'metrics': metrics,
                'source': result.get('source'),
                'signals': result.get('signals'),
            },
            network_traffic_snapshot=metrics,
            model_version=result.get('source', 'heuristic'),
            detection_pattern=f'Synthetic {result.get("threat_type")} pattern detected',
            status='active',
        )
        db.session.add(threat)
        db.session.flush()

        db.session.add(
            SecurityLog(
                organization_id=vm.organization_id,
                event_type=f'{result.get("threat_type", "suspicious_behavior")}_detected',
                severity=severity,
                source_ip='198.51.100.200',
                destination_ip=vm.private_ip,
                resource_id=vm.instance_id,
                description='Synthetic threat generated by the simulator.',
                raw_data=metrics,
            )
        )

        if remediation_agent is not None:
            remediation_result = remediation_agent.remediate(
                {'type': result.get('threat_type'), 'severity': severity.value, 'confidence': result.get('confidence', 0.0)},
                vm.to_dict(),
            )
            for action in remediation_result.get('results', []):
                db.session.add(
                    RemediationAction(
                        threat_id=threat.id,
                        action_type=action.get('action', 'request_review'),
                        executed_by='system',
                        status=action.get('status', 'success'),
                        details=action.get('details'),
                        result='Applied by dataset-backed simulator',
                        requires_approval=remediation_result.get('requires_approval', False),
                    )
                )

        socketio.emit(
            'threats:update',
            {
                'threat': threat.to_dict(),
                'source': 'resource_simulator',
            },
            room=f'org_{vm.organization_id}',
            namespace='/metrics',
        )
        socketio.emit(
            'dashboard_update',
            {'organization_id': vm.organization_id},
            room=f'org_{vm.organization_id}',
            namespace='/metrics',
        )

        self._append_activity(
            vm.organization_id,
            title='Security threat detected',
            severity=severity.value,
            details=f'{result.get("threat_type", "suspicious_behavior")} detected on {vm.instance_id}.',
            moment=moment,
        )

    def _record_org_snapshot(self, org_id, moment):
        vms = VirtualMachine.query.filter_by(organization_id=org_id).all()
        dbs = Database.query.filter_by(organization_id=org_id).all()
        running_vms = [vm for vm in vms if vm.status == ResourceStatus.RUNNING]
        running_dbs = [database for database in dbs if database.status == ResourceStatus.RUNNING]

        cpu_values = [vm.cpu_utilization for vm in running_vms] + [database.cpu_utilization for database in running_dbs]
        memory_values = [vm.memory_utilization for vm in running_vms] + [
            min(100.0, max(0.0, database.cpu_utilization * 1.35 + database.database_connections * 0.65))
            for database in running_dbs
        ]
        cost_values = [vm.calculate_current_cost() for vm in running_vms] + [
            database.total_runtime_hours * database.hourly_rate for database in running_dbs
        ]

        snapshot = {
            'timestamp': moment.isoformat(),
            'name': moment.strftime('%H:%M:%S'),
            'cpu': round(float(np.mean(cpu_values)) if cpu_values else 0.0, 2),
            'memory': round(float(np.mean(memory_values)) if memory_values else 0.0, 2),
            'cost': round(float(sum(cost_values)) if cost_values else 0.0, 4),
            'running_vms': len(running_vms),
            'running_dbs': len(running_dbs),
        }
        self._history_by_org[org_id].append(snapshot)

    def _append_activity(self, org_id, title, severity, details, moment=None):
        self._activity_by_org[org_id].appendleft(
            {
                'title': title,
                'severity': severity,
                'details': details,
                'timestamp': (moment or datetime.utcnow()).isoformat(),
            }
        )

    def _build_cost_trend_from_records(self, org_id):
        records = (
            CostRecord.query.filter_by(organization_id=org_id)
            .order_by(CostRecord.date.asc(), CostRecord.hour.asc())
            .all()
        )
        grouped = {}
        for record in records[-48:]:
            label = f'{record.date.isoformat()} {int(record.hour):02d}:00' if record.hour is not None else record.date.isoformat()
            grouped[label] = grouped.get(label, 0.0) + float(record.total_cost or 0.0)
        return [
            {'name': name, 'cost': round(cost, 2)}
            for name, cost in list(grouped.items())[-12:]
        ]

    def _build_utilization_trend_from_resources(self, org_id):
        vms = VirtualMachine.query.filter_by(organization_id=org_id).all()
        dbs = Database.query.filter_by(organization_id=org_id).all()
        cpu_values = [vm.cpu_utilization for vm in vms if vm.status == ResourceStatus.RUNNING] + [
            database.cpu_utilization for database in dbs if database.status == ResourceStatus.RUNNING
        ]
        memory_values = [vm.memory_utilization for vm in vms if vm.status == ResourceStatus.RUNNING] + [
            min(100.0, max(0.0, database.cpu_utilization * 1.35 + database.database_connections * 0.65))
            for database in dbs
            if database.status == ResourceStatus.RUNNING
        ]
        cpu = round(float(np.mean(cpu_values)) if cpu_values else 0.0, 2)
        memory = round(float(np.mean(memory_values)) if memory_values else 0.0, 2)
        # Use real org_metric_history if available (last 30 points)
        history = list(self.org_metric_history.get(org_id, []))
        if history:
            return [
                {'name': pt['name'], 'cpu': pt['cpu'], 'memory': pt['memory']}
                for pt in history[-30:]
            ]

        # Cold-start fallback: synthesize 6 points with diurnal pattern + Gaussian noise
        series = []
        now = datetime.utcnow()
        for offset in range(6):
            t = now - timedelta(hours=5 - offset)
            hour_frac = t.hour + t.minute / 60.0
            diurnal = math.sin(hour_frac / 24.0 * 2 * math.pi) * 15.0
            series.append({
                'name': t.strftime('%H:%M'),
                'cpu': max(0.0, round(cpu + diurnal + self._rng.gauss(0, 3.5), 2)),
                'memory': max(0.0, round(memory + diurnal * 0.6 + self._rng.gauss(0, 2.5), 2)),
            })
        return series

    def _build_recent_activity_from_db(self, org_id):
        items = []
        audit_logs = AuditLog.query.filter_by(organization_id=org_id).order_by(AuditLog.timestamp.desc()).limit(3).all()
        for log in audit_logs:
            items.append(
                {
                    'title': f'Audit: {log.action}',
                    'severity': 'info',
                    'details': f'{log.resource_type or "resource"} {log.resource_id or ""}'.strip(),
                    'timestamp': log.timestamp.isoformat() if log.timestamp else None,
                }
            )

        threats = ThreatDetection.query.filter_by(organization_id=org_id).order_by(ThreatDetection.detected_at.desc()).limit(3).all()
        for threat in threats:
            items.append(
                {
                    'title': f'Security: {threat.threat_type.value}',
                    'severity': threat.severity.value if threat.severity else 'medium',
                    'details': ', '.join(threat.affected_resources or []),
                    'timestamp': threat.detected_at.isoformat() if threat.detected_at else None,
                }
            )

        items.sort(key=lambda item: item.get('timestamp') or '', reverse=True)
        return items[:5]

    def _workload_explanation_for_org(self, org_id):
        """Return workload_explanation with pattern summary and queueing insight."""
        vms = VirtualMachine.query.filter_by(
            organization_id=org_id, status=ResourceStatus.RUNNING
        ).all()
        pattern_counts = {'steady': 0, 'spiky': 0, 'diurnal': 0}
        learning = {}
        total_queue = 0.0
        total_dropped = 0
        overloaded = 0
        for vm in vms:
            p = (vm.workload_pattern or 'steady').lower()
            if p in pattern_counts:
                pattern_counts[p] += 1
            else:
                pattern_counts[p] = pattern_counts.get(p, 0) + 1
            info = self._WORKLOAD_LEARNING.get(p, self._WORKLOAD_LEARNING['steady'])
            learning[p] = info
            total_queue += self._vm_queue.get(vm.instance_id, 0.0)
            total_dropped += self._vm_dropped.get(vm.instance_id, 0)
            if self._vm_queue.get(vm.instance_id, 0.0) > self._QUEUE_THRESHOLD:
                overloaded += 1
        # Task 7: include queue buildup and latency impact explanation
        queue_explanation = {
            'total_queue_length': round(total_queue, 2),
            'total_dropped_requests': total_dropped,
            'overloaded_vms': overloaded,
            'insight': (
                'Queue buildup detected — latency is rising. '
                'Consider scaling out or rate-limiting incoming traffic.'
                if total_queue > self._QUEUE_THRESHOLD
                else 'Queue depth is healthy. Latency within expected bounds.'
            ),
        }
        return {
            'patterns': pattern_counts,
            'learning': learning,
            'total_vms': len(vms),
            'queue': queue_explanation,
        }

    def get_dashboard_snapshot(self, org_id):
        """Return chart and activity series for the dashboard."""
        history = list(self._history_by_org.get(org_id, []))
        if history:
            cost_trend = [{'name': item['name'], 'cost': round(item['cost'], 2)} for item in history[-12:]]
            # Prefer real org_metric_history for utilization (finer-grained, diurnal-aware)
            metric_history = list(self.org_metric_history.get(org_id, []))
            if metric_history:
                utilization_trend = [
                    {'name': pt['name'], 'cpu': pt['cpu'], 'memory': pt['memory']}
                    for pt in metric_history[-30:]
                ]
            else:
                utilization_trend = [
                    {'name': item['name'], 'cpu': round(item['cpu'], 2), 'memory': round(item['memory'], 2)}
                    for item in history[-12:]
                ]
        else:
            cost_trend = self._build_cost_trend_from_records(org_id)
            utilization_trend = self._build_utilization_trend_from_resources(org_id)

        recent_activity = list(self._activity_by_org.get(org_id, []))
        if not recent_activity:
            recent_activity = self._build_recent_activity_from_db(org_id)

        return {
            'cost_trend': cost_trend,
            'utilization_trend': utilization_trend,
            'recent_activity': recent_activity,
            'workload_explanation': self._workload_explanation_for_org(org_id),
        }

    def get_vm_avg_latency(self, vm_id: str) -> float:
        """Mean of the rolling latency-samples deque for a single VM (ms).

        Returns 0.0 when no samples have been collected yet.
        """
        samples = self.vm_latency_samples.get(vm_id)
        if not samples:
            return 0.0
        # Deque is bounded (maxlen=200) so this O(n) sum is trivially cheap.
        return round(sum(samples) / len(samples), 2)

    def get_org_workload_snapshot(self, org_id: int) -> dict:
        """Aggregate the sim's in-memory queue/latency state for a single org.

        Aggregation is strictly over VMs currently tracked (those that have
        ticked at least once). Safe for the control plane to call every tick.
        """
        # Snapshot the list of running VMs once so aggregation is consistent.
        running_vms = (
            VirtualMachine.query
            .filter(VirtualMachine.organization_id == org_id)
            .filter(VirtualMachine.status == ResourceStatus.RUNNING)
            .all()
        )
        if not running_vms:
            return {
                'queue_avg_ms': 0.0,
                'queue_total_ms': 0.0,
                'latency_avg_ms': 0.0,
                'p95_latency_ms': 0.0,
                'dropped_requests_total': 0,
                'dropped_recent_total': 0,
                'overloaded_vms': 0,
                'vm_count': 0,
                'requests_per_second': 0,
                'avg_service_time_ms': 5.0,
            }

        queue_values: list[float] = []
        latency_values: list[float] = []
        p95_values: list[float] = []
        total_dropped = 0
        overloaded = 0
        total_rps = 0
        for vm in running_vms:
            q = self._vm_queue.get(vm.instance_id, 0.0)
            queue_values.append(q)
            # Avg latency from the rolling sample deque when available,
            # fallback to the most recent single sample if cold.
            samples = self.vm_latency_samples.get(vm.instance_id)
            if samples:
                latency_values.append(sum(samples) / len(samples))
                p95_values.append(float(np.percentile(list(samples), 95)))
            total_dropped += self._vm_dropped.get(vm.instance_id, 0)
            if q > self._QUEUE_THRESHOLD_MS:
                overloaded += 1
            
            # Aggregate effective RPS from history or base
            rps_history = self.vm_rps_history.get(vm.instance_id)
            if rps_history:
                total_rps += rps_history[-1].get('rps', 0)
            else:
                total_rps += int(vm.requests_per_second or 0)

        queue_avg = sum(queue_values) / len(queue_values) if queue_values else 0.0
        queue_total = sum(queue_values)
        latency_avg = (
            sum(latency_values) / len(latency_values) if latency_values else 0.0
        )
        # Org-level p95 is the max of per-VM p95s (worst-VM view) so the alarm
        # fires on the slowest instance rather than being diluted by the mean.
        p95_latency = max(p95_values) if p95_values else 0.0

        # Bug #5 fix: aggregate the DETERMINISTIC mean across VMs. The control
        # plane uses this to compute target_bpi = SLO / mean_service_time;
        # using the per-tick lognormal SAMPLE here would make the target
        # oscillate on every tick and the autoscaler would chase its own tail.
        mean_service_times: list[float] = [
            self._vm_des[vm.instance_id].state.last_mean_service_time_ms
            for vm in running_vms
            if vm.instance_id in self._vm_des
        ]
        avg_service_time_ms = (
            sum(mean_service_times) / len(mean_service_times)
            if mean_service_times else 5.0
        )

        # Bug #4 fix: expose BOTH cumulative drops (accounting) and the
        # most-recent-tick drops (used as the ALARM signal so the system
        # can recover from drops events instead of latching to ALARM).
        dropped_recent_total = sum(
            self._vm_des[vm.instance_id].state.dropped_in_last_tick
            for vm in running_vms
            if vm.instance_id in self._vm_des
        )
        dropped_cumulative_total = sum(
            self._vm_des[vm.instance_id].state.cumulative_dropped
            for vm in running_vms
            if vm.instance_id in self._vm_des
        )

        return {
            'queue_avg_ms': round(queue_avg, 2),
            'queue_total_ms': round(queue_total, 2),
            'latency_avg_ms': round(latency_avg, 2),
            'p95_latency_ms': round(p95_latency, 2),
            # Existing key kept for backward-compat (cumulative since boot).
            'dropped_requests_total': int(dropped_cumulative_total),
            # New: per-evaluation rate-style counter — control plane uses this.
            'dropped_recent_total': int(dropped_recent_total),
            'overloaded_vms': overloaded,
            'vm_count': len(running_vms),
            'requests_per_second': int(total_rps),
            # Deterministic mean: feeds target_bpi (Bug #5 fix).
            'avg_service_time_ms': round(avg_service_time_ms, 3),
        }

    def get_vm_rps_history(self, vm_id: str, n: int = 60) -> list[dict]:
        """Return last N entries of per-VM RPS history.

        Each entry: ``{'timestamp': ISO, 'rps': int, 'overload': bool}``
        """
        history = list(self.vm_rps_history.get(vm_id, []))
        return history[-n:] if history else []

    def get_vm_metrics_history(self, vm_id: str, minutes: int = 60) -> list[dict]:
        """Return per-VM metric history for the last *minutes* minutes.

        Each entry: ``{'timestamp': ISO, 'name': 'HH:MM', 'cpu': float, 'memory': float,
                        'network_in': float, 'network_out': float}``
        """
        history = list(self.vm_metric_history.get(vm_id, []))
        if not history:
            return []
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        return [pt for pt in history if pt.get('timestamp', '') >= cutoff.isoformat()]
