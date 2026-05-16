"""Module 3 — MAPE control plane for organization resource snapshots.

Monitor → Analyze → Plan → Execute loop over the in-memory simulation state
exposed by `resource_simulator`. Extends (never removes) existing response
keys so the frontend continues to work unchanged.
"""

import calendar
import math
import threading
import time
from datetime import datetime

from app import db
from app.models.resources import VirtualMachine, Database, ResourceStatus

# ── Snapshot cache — updated by background thread, read by API ───────────────
_snapshot_cache: dict[int, dict] = {}
_cache_lock = threading.Lock()
_cache_ttl = 2.0  # seconds between recomputes
_control_plane_task = None
_control_plane_lock = threading.Lock()

# In-memory storage for CPU history per organization (max 5 entries)
cpu_history: dict[int, list] = {}

# EMA smoothing parameters
alpha = 0.3
ema_cpu: dict[int, float] = {}
ema_memory: dict[int, float] = {}

# Alert state storage (CloudWatch-style state transitions)
alert_states = {}  # org_id -> { alert_type: state }

# Scaling state storage for cooldown and capacity control
scaling_state = {}  # org_id -> { last_action_time, capacity }


def _empty_workload_snapshot() -> dict:
    """Canonical zero-workload shape used when no simulator data exists."""
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


def _normalize_workload_snapshot(raw: dict | None) -> dict:
    """Keep REST/socket snapshots schema-stable across cold and active runtime."""
    normalized = _empty_workload_snapshot()
    if isinstance(raw, dict):
        normalized.update({key: raw.get(key, value) for key, value in normalized.items()})
    return normalized


def clear_snapshot_cache(org_id: int | None = None) -> None:
    """Clear the cached org snapshot(s) used by the dashboard and timeline."""
    with _cache_lock:
        if org_id is None:
            _snapshot_cache.clear()
        else:
            _snapshot_cache.pop(org_id, None)

# ── MAPE thresholds ─────────────────────────────────────────────────────────
_QUEUE_ALARM_MS = 1000.0        # 1s of backlog → queue ALARM
_LATENCY_P95_ALARM_MS = 500.0   # p95 SLO (ms) — also used for target BPI
_LATENCY_P95_CRITICAL_MS = 1500.0
_TARGET_UTIL_PCT = 60
_SCALE_COOLDOWN_S = 15
_CAPACITY_MIN = 1
_CAPACITY_MAX = 10
# Scale-in hysteresis: only scale in when BPI < target × (1 − SCALE_IN_TOLERANCE)
_SCALE_IN_BPI_RATIO = 0.7       # AWS recommended: 70% of target triggers scale-in
# Hard step cap: never add/remove more than this many instances per evaluation.
_MAX_STEP = 2
_GLOBAL_MAX_VMS = 100

# ── VM provisioning helpers for autoscaling execution ──────────────────────────

_INSTANCE_SPECS = {
    "t2.micro":  {"vcpu": 1, "memory_gb": 1,  "baseline_cpu": 0.20, "baseline_memory": 0.30, "hourly_rate": 0.0116},
    "t2.small":  {"vcpu": 1, "memory_gb": 2,  "baseline_cpu": 0.40, "baseline_memory": 0.50, "hourly_rate": 0.0230},
    "t2.medium": {"vcpu": 2, "memory_gb": 4,  "baseline_cpu": 0.60, "baseline_memory": 0.70, "hourly_rate": 0.0464},
    "t2.large":  {"vcpu": 2, "memory_gb": 8,  "baseline_cpu": 0.75, "baseline_memory": 0.80, "hourly_rate": 0.0928},
}


def _next_autoscale_sequence(org_id: int) -> int:
    """Return a deterministic org-local autoscale sequence."""
    existing = (
        VirtualMachine.query
        .filter(VirtualMachine.organization_id == org_id)
        .filter(VirtualMachine.name.like("autoscale-%"))
        .count()
    )
    return existing + 1


def _create_autoscale_vm(org_id: int, instance_type: str, base_rps: int, pattern: str) -> VirtualMachine:
    """Create and commit a RUNNING VM for autoscaling execution."""
    from app.models.resources import Database
    current_vms = VirtualMachine.query.filter_by(organization_id=org_id).filter(VirtualMachine.status != ResourceStatus.TERMINATED).count()
    current_dbs = Database.query.filter_by(organization_id=org_id).filter(Database.status != ResourceStatus.TERMINATED).count()
    if current_vms + current_dbs >= _GLOBAL_MAX_VMS:
        raise Exception(f"Organization has reached the maximum allowed limit of {_GLOBAL_MAX_VMS} resources.")
    
    spec = _INSTANCE_SPECS.get(instance_type, _INSTANCE_SPECS["t2.medium"])
    sequence = _next_autoscale_sequence(org_id)
    octet_3 = org_id % 256
    octet_4 = ((sequence - 1) % 254) + 1
    vm = VirtualMachine(
        organization_id=org_id,
        name=f"autoscale-org{org_id}-{sequence:03d}",
        instance_id=f"i-autoscale-{org_id}-{sequence:03d}",
        instance_type=instance_type,
        status=ResourceStatus.RUNNING,
        vcpu=spec["vcpu"],
        memory_gb=spec["memory_gb"],
        storage_gb=8,
        private_ip=f"10.0.{octet_3}.{octet_4}",
        cpu_utilization=round(spec["baseline_cpu"] * 100, 2),
        memory_utilization=round(spec["baseline_memory"] * 100, 2),
        hourly_rate=spec["hourly_rate"],
        total_runtime_hours=0.0,
        requests_per_second=base_rps,
        workload_pattern=pattern,
        launched_at=datetime.utcnow(),
    )
    db.session.add(vm)
    db.session.commit()
    return vm


def _terminate_autoscale_vm(org_id: int) -> bool:
    """Terminate one autoscale-created VM (lowest utilisation first). Returns True if a VM was terminated."""
    candidates = (
        VirtualMachine.query
        .filter(VirtualMachine.organization_id == org_id)
        .filter(VirtualMachine.status == ResourceStatus.RUNNING)
        .filter(VirtualMachine.name.like("autoscale-%"))
        .order_by(VirtualMachine.cpu_utilization.asc())
        .all()
    )
    if not candidates:
        return False
    vm = candidates[0]
    vm.status = ResourceStatus.TERMINATED
    vm.terminated_at = datetime.utcnow()
    db.session.commit()
    # Remove from simulator in-memory state so it stops contributing to queue/latency.
    try:
        from flask import current_app
        sim = getattr(current_app, 'simulator', None)
        if sim and hasattr(sim, '_vm_des'):
            sim._vm_des.pop(vm.instance_id, None)
            sim._vm_queue.pop(vm.instance_id, None)
            sim._vm_dropped.pop(vm.instance_id, None)
            sim.vm_latency_samples.pop(vm.instance_id, None)
            sim.vm_rps_history.pop(vm.instance_id, None)
            sim.vm_metric_history.pop(vm.instance_id, None)
    except Exception:
        pass
    return True


def _workload_snapshot_for(org_id: int) -> dict:
    """Pull the simulator's per-org queue/latency aggregate. Safe on no-sim."""
    try:
        from app import simulation_engine
        state = simulation_engine.get_state(org_id)
        if state and state.get('is_running'):
            metrics = state.get('metrics', {})
            return _normalize_workload_snapshot({
                'queue_total_ms': metrics.get('queue_depth', 0) * 10, # Mock scale for UI
                'latency_avg_ms': metrics.get('latency_ms', 0),
                'p95_latency_ms': metrics.get('latency_ms', 0) * 1.2,
                'dropped_recent_total': state.get('dropped_requests', 0),
                'vm_count': state.get('vm_count', 0),
                'avg_service_time_ms': 5.0,
                'requests_per_second': metrics.get('incoming_rps', 0)
            })
            
        from flask import current_app
        if hasattr(current_app, 'simulator'):
            return _normalize_workload_snapshot(current_app.simulator.get_org_workload_snapshot(org_id))
        return _empty_workload_snapshot()
    except Exception as e:
        print(f"[CONTROL_PLANE] Error pulling from engine: {e}")
        return _empty_workload_snapshot()


def _topology_for(org_id: int) -> dict:
    """Build the VM→Host→Datacenter view for Module 1 §5."""
    try:
        from app.services.infrastructure import aggregate_via_topology
        return aggregate_via_topology(org_id)
    except Exception:
        return {}


def _security_for(org_id: int) -> dict:
    """Build org security metrics from persisted threat state."""
    try:
        from app.models.security import ThreatDetection, ThreatSeverity

        threats = ThreatDetection.query.filter_by(organization_id=org_id, status='active').all()
        active_threats = len(threats)
        critical_count = sum(1 for threat in threats if threat.severity == ThreatSeverity.CRITICAL)
        high_count = sum(1 for threat in threats if threat.severity == ThreatSeverity.HIGH)
        medium_count = sum(1 for threat in threats if threat.severity == ThreatSeverity.MEDIUM)
        security_score = max(0, min(100, 100 - (critical_count * 20 + high_count * 10 + medium_count * 5)))

        return {
            'active_threats': active_threats,
            'security_score': security_score,
            'threats_by_severity': {
                'critical': critical_count,
                'high': high_count,
                'medium': medium_count,
            },
            'latest_threats': [threat.to_dict() for threat in threats[:5]],
        }
    except Exception:
        return {
            'active_threats': 0,
            'security_score': 100,
            'threats_by_severity': {'critical': 0, 'high': 0, 'medium': 0},
            'latest_threats': [],
        }


def _cost_for(org_id: int) -> dict:
    """Build org cost metrics from persisted cost and budget state."""
    try:
        from app.models.cost import CostRecord, Budget

        today = datetime.utcnow().date()
        month_start = today.replace(day=1)
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        records = CostRecord.query.filter(
            CostRecord.organization_id == org_id,
            CostRecord.date >= month_start,
        ).all()

        by_service: dict[str, float] = {}
        by_day: dict[str, float] = {}
        current_month_spend = 0.0
        for record in records:
            current_month_spend += float(record.total_cost or 0)
            by_service[record.resource_type] = by_service.get(record.resource_type, 0.0) + float(record.total_cost or 0)
            by_day[str(record.date)] = by_day.get(str(record.date), 0.0) + float(record.total_cost or 0)

        budgets = Budget.query.filter_by(organization_id=org_id, is_active=True).all()
        budget_status = []
        for budget in budgets:
            status = budget.to_dict()
            status['alert_level'] = 'normal'
            if status['percentage_used'] > 100:
                status['alert_level'] = 'critical'
            elif status['percentage_used'] > 80:
                status['alert_level'] = 'warning'
            budget_status.append(status)

        return {
            'current_month_spend': round(current_month_spend, 2),
            'monthly_spend': round(current_month_spend, 2),
            'by_service': {k: round(v, 2) for k, v in by_service.items()},
            'by_day': {k: round(v, 2) for k, v in sorted(by_day.items())},
            'projected_month_end': round(current_month_spend / max(1, today.day) * days_in_month, 2),
            'budgets': budget_status,
            'budget_count': len(budget_status),
            'over_budget_count': sum(1 for item in budget_status if item.get('alert_level') == 'critical'),
        }
    except Exception:
        return {
            'current_month_spend': 0.0,
            'monthly_spend': 0.0,
            'by_service': {},
            'by_day': {},
            'projected_month_end': 0.0,
            'budgets': [],
            'budget_count': 0,
            'over_budget_count': 0,
        }


def _governance_for(org_id: int) -> dict:
    """Build org governance metrics from persisted policy state."""
    try:
        from app.models.governance import Policy, ComplianceCheck, PolicyStatus

        policies = Policy.query.filter_by(organization_id=org_id).all()
        active_policies = [policy for policy in policies if policy.status == PolicyStatus.ACTIVE]
        compliance_checks = ComplianceCheck.query.join(
            ComplianceCheck.policy
        ).filter(
            Policy.organization_id == org_id
        ).all()

        if compliance_checks:
            passed_count = sum(1 for check in compliance_checks if check.status == 'passed')
            compliance_score = int((passed_count / len(compliance_checks)) * 100)
        else:
            compliance_score = 100

        return {
            'policy_count': len(policies),
            'active_policy_count': len(active_policies),
            'compliance_check_count': len(compliance_checks),
            'compliance_score': compliance_score,
            'recent_checks': [
                {
                    'policy_id': check.policy_id,
                    'resource_id': check.resource_id,
                    'resource_type': check.resource_type,
                    'checked_at': check.checked_at.isoformat() if check.checked_at else None,
                    'status': getattr(check, 'status', 'unknown'),
                }
                for check in compliance_checks[:5]
            ],
        }
    except Exception:
        return {
            'policy_count': 0,
            'active_policy_count': 0,
            'compliance_check_count': 0,
            'compliance_score': 100,
            'recent_checks': [],
        }


def _runtime_for(org_id: int) -> dict:
    """Build current simulation/runtime state for recovery-oriented views."""
    try:
        from app import simulation_engine

        state = simulation_engine.get_state(org_id) or {}
        total_ticks = int(state.get('total_ticks', 0) or 0)
        current_tick = int(state.get('current_tick', 0) or 0)
        progress_pct = round((current_tick / total_ticks) * 100, 1) if total_ticks else 0.0
        return {
            'scenario_id': state.get('scenario_id'),
            'is_running': bool(state.get('is_running', False)),
            'current_tick': current_tick,
            'total_ticks': total_ticks,
            'progress_pct': progress_pct,
            'dropped_requests': int(state.get('dropped_requests', 0) or 0),
            'vm_count': int(state.get('vm_count', 0) or 0),
            'recovery_state': 'running' if state.get('is_running') else 'idle',
        }
    except Exception:
        return {
            'scenario_id': None,
            'is_running': False,
            'current_tick': 0,
            'total_ticks': 0,
            'progress_pct': 0.0,
            'dropped_requests': 0,
            'vm_count': 0,
            'recovery_state': 'idle',
        }


def _telemetry_for(org_id: int) -> dict:
    """Build dashboard telemetry series from the simulator when available."""
    try:
        from flask import current_app

        simulator = getattr(current_app, 'simulator', None)
        if simulator and hasattr(simulator, 'get_dashboard_snapshot'):
            telemetry = simulator.get_dashboard_snapshot(org_id) or {}
            return {
                'cost_trend': telemetry.get('cost_trend', []),
                'utilization_trend': telemetry.get('utilization_trend', []),
                'recent_activity': telemetry.get('recent_activity', []),
                'workload_explanation': telemetry.get('workload_explanation', {}),
            }
    except Exception:
        pass

    return {
        'cost_trend': [],
        'utilization_trend': [],
        'recent_activity': [],
        'workload_explanation': {},
    }


def _operational_feed_for(org_id: int, snapshot: dict | None = None) -> dict:
    """Build a compact cause → impact → recovery feed for the dashboard."""
    snapshot = snapshot or {}
    try:
        from app.services.event_bus import (
            event_bus,
            EVENT_METRIC_UPDATE,
            EVENT_SCALING_DECISION,
            EVENT_WORKLOAD_UPDATE,
        )

        recent_events = event_bus.recent(org_id, limit=15)
    except Exception:
        recent_events = []

    recent_events = sorted(recent_events, key=lambda item: item.get('timestamp') or 0)

    chains: list[dict] = []
    current_chain: dict | None = None

    def _new_chain(seed_event: dict) -> dict:
        return {
            'cause': None,
            'impact': None,
            'recovery': None,
            'status': 'steady',
            'summary': '',
            'events': [seed_event],
        }

    for event in recent_events:
        event_type = event.get('type')
        if event_type == EVENT_WORKLOAD_UPDATE:
            if current_chain and (current_chain.get('cause') or current_chain.get('impact') or current_chain.get('recovery')):
                chains.append(current_chain)
            current_chain = _new_chain(event)
            current_chain['cause'] = {
                'type': 'workload_update',
                'title': 'Workload changed',
                'details': event.get('payload', {}),
                'timestamp': event.get('timestamp'),
            }
        elif event_type == EVENT_METRIC_UPDATE:
            if current_chain is None:
                current_chain = _new_chain(event)
            current_chain['impact'] = {
                'type': 'metric_update',
                'title': 'Metrics shifted',
                'details': event.get('payload', {}),
                'timestamp': event.get('timestamp'),
            }
            current_chain['status'] = 'under_pressure'
        elif event_type == EVENT_SCALING_DECISION:
            if current_chain is None:
                current_chain = _new_chain(event)
            action = (event.get('payload') or {}).get('action', {})
            current_chain['recovery'] = {
                'type': 'scaling_decision',
                'title': action.get('type', 'scaling_decision').replace('_', ' ').title(),
                'details': action,
                'timestamp': event.get('timestamp'),
            }
            current_chain['status'] = 'recovering' if action.get('type') in {'scale_up', 'scale_down'} else 'steady'
            current_chain['summary'] = action.get('reason', '')
            chains.append(current_chain)
            current_chain = None

    if current_chain and (current_chain.get('cause') or current_chain.get('impact') or current_chain.get('recovery')):
        if not current_chain.get('summary'):
            current_chain['summary'] = 'No recovery action has been published yet.'
        chains.append(current_chain)

    if not chains:
        current_queue = float(snapshot.get('workload', {}).get('queue_total_ms', 0) or 0)
        current_bpi = float(snapshot.get('bpi', 0) or 0)
        current_target = float(snapshot.get('target_bpi', 0) or 0)
        chains = [{
            'cause': {
                'type': 'snapshot',
                'title': 'Snapshot refreshed',
                'details': {'queue_total_ms': current_queue, 'bpi': current_bpi},
                'timestamp': snapshot.get('timestamp'),
            },
            'impact': {
                'type': 'snapshot',
                'title': 'Current workload state',
                'details': {
                    'queue_total_ms': current_queue,
                    'bpi': current_bpi,
                    'target_bpi': current_target,
                },
                'timestamp': snapshot.get('timestamp'),
            },
            'recovery': None,
            'status': 'steady',
            'summary': 'Snapshot is healthy and ready for the next control-plane tick.',
            'events': [],
        }]

    return {
        'recent_events': recent_events[-10:],
        'chains': chains[-5:],
        'freshness_seconds': 0.0,
    }


def get_org_snapshot(org_id: int, use_cache: bool = True) -> dict:
    """Return the latest computed snapshot for an org.

    By default reads from the in-memory cache (updated every ~2 s by the
    background control-plane loop). Set use_cache=False to force a fresh
    computation (used by the cache-refresh path itself).
    """
    if use_cache:
        with _cache_lock:
            cached = _snapshot_cache.get(org_id)
            if cached is not None:
                snapshot = dict(cached)
            else:
                snapshot = _compute_org_snapshot(org_id)
    else:
        snapshot = _compute_org_snapshot(org_id)

    timestamp = float(snapshot.get('timestamp') or time.time())
    snapshot_age_seconds = max(0.0, round(time.time() - timestamp, 3))
    snapshot['snapshot_timestamp'] = timestamp
    snapshot['snapshot_age_seconds'] = snapshot_age_seconds
    snapshot['snapshot_fresh'] = snapshot_age_seconds <= (_cache_ttl * 2)
    snapshot['operational_feed'] = _operational_feed_for(org_id, snapshot)
    snapshot['operational_feed']['freshness_seconds'] = snapshot_age_seconds
    topology_mini_map = snapshot.get('topology_mini_map')
    if isinstance(topology_mini_map, dict):
        topology_mini_map['freshness_seconds'] = snapshot_age_seconds
        topology_mini_map['fresh'] = snapshot_age_seconds <= (_cache_ttl * 2)
    cost_performance = snapshot.get('cost_performance')
    if isinstance(cost_performance, dict):
        cost_performance['freshness_seconds'] = snapshot_age_seconds
        cost_performance['fresh'] = snapshot_age_seconds <= (_cache_ttl * 2)
    operational_insights = snapshot.get('operational_insights')
    if isinstance(operational_insights, dict):
        operational_insights['freshness_seconds'] = snapshot_age_seconds
        operational_insights['fresh'] = snapshot_age_seconds <= (_cache_ttl * 2)
    return snapshot


def _compute_org_snapshot(org_id: int) -> dict:
    """Get current organization resource snapshot.
    
    Queries the database once for a consistent snapshot and computes metrics.
    
    Args:
        org_id: Organization ID
        
    Returns:
        Dict with keys:
            - total_vms: Total non-terminated VMs
            - running_vms: Total running VMs
            - cpu_avg: Weighted average CPU utilization of running VMs (0-100)
            - memory_avg: Average memory utilization of running VMs (0-100)
    """
    # Single DB query for all VMs in organization
    vms = VirtualMachine.query.filter_by(
        organization_id=org_id,
    ).filter(VirtualMachine.status != ResourceStatus.TERMINATED).all()
    
    # Compute total_vms from queried list
    total_vms = len(vms)
    
    # Filter running VMs in memory (separate from valid_vms for accurate counting)
    running_vms = [vm for vm in vms if vm.status == ResourceStatus.RUNNING]
    running_vms_count = len(running_vms)
    
    # Filter VMs with valid metrics for aggregation (subset of running_vms)
    valid_vms = [
        vm for vm in running_vms
        if vm.cpu_utilization is not None and vm.memory_utilization is not None
    ]
    
    # BPI defaults — overwritten in the valid_vms branch if simulation is active.
    bpi: float = 0.0
    target_bpi: float = 0.0
    avg_service_time_ms: float = 5.0

    current_hourly_cost = sum(float(vm.hourly_rate or 0) for vm in running_vms)

    # Compute metrics only from valid VMs
    if valid_vms:
        # Weight CPU by vcpu for realistic cross-instance-type averaging
        total_vcpu = sum(float(vm.vcpu or 1) for vm in valid_vms)
        if total_vcpu > 0:
            weighted_cpu_sum = sum(
                float(vm.cpu_utilization or 0) * float(vm.vcpu or 1)
                for vm in valid_vms
            )
            cpu_avg = weighted_cpu_sum / total_vcpu
        else:
            cpu_avg = 0.0
        
        # Memory computed normally (unweighted)
        memory_avg = sum(float(vm.memory_utilization or 0) for vm in valid_vms) / len(valid_vms)
        
        # Clamp values to 0-100 range
        cpu_avg = max(0.0, min(100.0, cpu_avg))
        memory_avg = max(0.0, min(100.0, memory_avg))
        
        # EMA smoothing for CPU
        if org_id not in ema_cpu:
            ema_cpu[org_id] = cpu_avg
        else:
            ema_cpu[org_id] = (alpha * cpu_avg) + ((1 - alpha) * ema_cpu[org_id])
        smoothed_cpu = ema_cpu[org_id]
        
        # Replace cpu_avg with smoothed for all downstream usage
        cpu_avg = smoothed_cpu
        
        # EMA smoothing for memory
        if org_id not in ema_memory:
            ema_memory[org_id] = memory_avg
        else:
            ema_memory[org_id] = (alpha * memory_avg) + ((1 - alpha) * ema_memory[org_id])
        smoothed_memory = ema_memory[org_id]
        
        # Replace memory_avg with smoothed for all downstream usage
        memory_avg = smoothed_memory
        
        # Initialize bottleneck variables
        raw_max_cpu = 0
        raw_max_memory = 0
        smoothed_max_cpu = 0
        smoothed_max_memory = 0
        
        # Bottleneck detection (hybrid: raw max + smoothed average)
        raw_max_cpu = max(float(vm.cpu_utilization or 0) for vm in valid_vms)
        raw_max_memory = max(float(vm.memory_utilization or 0) for vm in valid_vms)
        
        smoothed_max_cpu = (0.7 * raw_max_cpu) + (0.3 * smoothed_cpu)
        smoothed_max_memory = (0.7 * raw_max_memory) + (0.3 * smoothed_memory)
        
        cpu_bottleneck = smoothed_max_cpu > 85
        memory_bottleneck = smoothed_max_memory > 90
        
        max_cpu = raw_max_cpu
        max_memory = raw_max_memory
        
        # System pressure assessment
        if cpu_bottleneck or memory_bottleneck:
            system_pressure = "high"
        elif smoothed_cpu > 70:
            system_pressure = "moderate"
        else:
            system_pressure = "normal"
        
        # Trend detection
        history = cpu_history.get(org_id, [])

        if len(history) < 4:
            cpu_trend = "stable"
        else:
            recent = history[-3:]
            previous = history[-4:-1]

            recent_avg = sum(recent) / len(recent)
            previous_avg = sum(previous) / len(previous)

            if recent_avg > previous_avg + 3:
                cpu_trend = "increasing"
            elif recent_avg < previous_avg - 3:
                cpu_trend = "decreasing"
            else:
                cpu_trend = "stable"
        
        # Update CPU history (keep max 5 entries) - use smoothed value
        history.append(smoothed_cpu)
        if len(history) > 5:
            history.pop(0)
        cpu_history[org_id] = history
        
        # System risk assessment
        if cpu_trend == "increasing" and smoothed_cpu > 60:
            system_risk = "rising"
        else:
            system_risk = "normal"
        
        # Alert engine with CloudWatch-style state transitions
        prev_states = alert_states.get(org_id, {}).copy()
        org_alerts = {}
        
        # Define insufficient data conditions
        cpu_insufficient = (
            total_vms == 0
            or len(cpu_history.get(org_id, [])) < 3
        )
        memory_insufficient = (
            total_vms == 0
            or len(cpu_history.get(org_id, [])) < 3
        )
        
        # CPU alert state
        if cpu_insufficient:
            cpu_state = "INSUFFICIENT_DATA"
        elif cpu_bottleneck:
            cpu_state = "ALARM"
        else:
            cpu_state = "OK"
        org_alerts["cpu"] = cpu_state
        
        # Memory alert state
        if memory_insufficient:
            memory_state = "INSUFFICIENT_DATA"
        elif memory_bottleneck:
            memory_state = "ALARM"
        else:
            memory_state = "OK"
        org_alerts["memory"] = memory_state
        
        # Trend alert state
        if cpu_trend == "stable" and len(cpu_history.get(org_id, [])) < 3:
            trend_state = "INSUFFICIENT_DATA"
        elif system_risk == "rising":
            trend_state = "ALARM"
        else:
            trend_state = "OK"
        org_alerts["trend"] = trend_state
        
        # Track state transitions
        transitions = []
        for key, new_state in org_alerts.items():
            old_state = prev_states.get(key)
            if old_state and old_state != new_state:
                transitions.append({
                    "type": key,
                    "from": old_state,
                    "to": new_state
                })
        
        # Save state
        alert_states[org_id] = org_alerts
        
        # ── Module 3: MAPE — MONITOR (pull sim workload snapshot) ──────────────
        workload = _workload_snapshot_for(org_id)
        queue_total_ms = float(workload.get('queue_total_ms', 0.0) or 0.0)
        latency_avg_ms = float(workload.get('latency_avg_ms', 0.0) or 0.0)
        p95_latency_ms = float(workload.get('p95_latency_ms', 0.0) or 0.0)
        # Bug #4 fix: ALARM logic uses RECENT drops (per evaluation cycle), not
        # cumulative — otherwise drops_state stays ALARM forever and scale-in
        # is permanently blocked. Cumulative remains for accounting only.
        dropped_recent = int(workload.get('dropped_recent_total', 0) or 0)
        dropped_total = int(workload.get('dropped_requests_total', 0) or 0)
        overloaded_vms = int(workload.get('overloaded_vms', 0) or 0)
        # Bug #2 fix: BPI must use the actual instance count (vm_count), not
        # the autoscaler's abstract capacity scalar — those diverge because the
        # simulator does not actually launch new VMs when capacity bumps.
        vm_count = int(workload.get('vm_count', 0) or 0)

        # ── Module 3: MAPE — ANALYZE (queue/latency/drops alerts) ───────────
        # Queue alert: ALARM when backlog > 1s of work; INSUFFICIENT on cold sim.
        if workload.get('vm_count', 0) == 0:
            queue_state = "INSUFFICIENT_DATA"
        elif queue_total_ms > _QUEUE_ALARM_MS:
            queue_state = "ALARM"
        else:
            queue_state = "OK"
        org_alerts["queue"] = queue_state

        # Latency alert: ALARM when p95 breaches SLO.
        if workload.get('vm_count', 0) == 0:
            latency_state = "INSUFFICIENT_DATA"
        elif p95_latency_ms > _LATENCY_P95_ALARM_MS:
            latency_state = "ALARM"
        else:
            latency_state = "OK"
        org_alerts["latency"] = latency_state

        # Drops alert: rate-style — any drops in the most recent tick.
        # Bug #4 fix: was previously cumulative, which never recovered.
        drops_state = "ALARM" if dropped_recent > 0 else "OK"
        org_alerts["drops"] = drops_state

        # Re-track transitions so the newly-added alert keys are included.
        transitions = []
        for key, new_state in org_alerts.items():
            old_state = prev_states.get(key)
            if old_state and old_state != new_state:
                transitions.append({"type": key, "from": old_state, "to": new_state})
        alert_states[org_id] = org_alerts

        # ── MAPE — PLAN + EXECUTE (Task 1: AWS BPI target-tracking) ──────────
        # Import DES helpers lazily to avoid module-load cycle.
        from app.services.des_engine import (
            compute_backlog_per_instance,
            compute_target_bpi,
            compute_desired_capacity,
        )

        state = scaling_state.get(org_id, {"last_action_time": 0, "capacity": max(1, vm_count)})
        # Source of truth sync: align desired capacity with actual running VMs if user manually intervened
        if state["capacity"] != vm_count:
            state["capacity"] = max(1, vm_count)
            scaling_state[org_id] = state

        current_time = time.time()

        # Retrieve org-level avg service time from the workload snapshot so
        # target BPI uses the actual measured distribution, not a hard-coded
        # constant. Falls back to 5 ms if the simulator hasn't reported yet.
        avg_service_time_ms = float(workload.get("avg_service_time_ms", 5.0) or 5.0)

        # PRIMARY SIGNAL: backlog-per-instance (AWS Target Tracking).
        # Bug #2 fix: denominator is vm_count (instances actually doing work),
        # not state["capacity"] (autoscaler's desired-count scalar). They
        # diverge in this simulation because scale_up bumps the scalar but
        # does not spawn real VMs — using the scalar would make BPI 'recover'
        # without any real capacity change, defeating the AWS principle:
        # "scaling metric MUST be proportional to capacity actually present".
        # Fall back to capacity scalar only when no VMs are running.
        instances_for_bpi = vm_count if vm_count > 0 else state["capacity"]
        bpi = compute_backlog_per_instance(
            queue_total_ms, avg_service_time_ms, instances_for_bpi
        )

        # TARGET: how many requests of backlog can each instance hold and still
        # drain within the latency SLO?
        # target_bpi = SLO_ms / avg_service_time_ms
        target_bpi = compute_target_bpi(_LATENCY_P95_ALARM_MS, avg_service_time_ms)

        if current_time - state["last_action_time"] < _SCALE_COOLDOWN_S:
            # Cooldown gate: Execute phase allows only one action per cooldown.
            actions = []
        else:
            actions = []
            action_taken = False

            # ── Debug: queue calculation ────────────────────────────────────────
            print(
                f"[CONTROL_PLANE:AUTOSCALE] org={org_id} "
                f"bpi={bpi:.2f} target_bpi={target_bpi:.2f} "
                f"queue_total_ms={queue_total_ms:.1f} p95_latency={p95_latency_ms:.1f}ms "
                f"vm_count={vm_count} capacity={state['capacity']}"
            )

            if bpi > target_bpi and state["capacity"] < _CAPACITY_MAX:
                # SCALE OUT — proportional to overload.
                # desired = ceil(backlog_requests / target_bpi)
                # step = desired - current_capacity, clamped to [1, MAX_STEP].
                desired = compute_desired_capacity(
                    queue_total_ms, avg_service_time_ms, target_bpi
                )
                step = max(1, min(_MAX_STEP, desired - state["capacity"]))
                new_capacity = min(_CAPACITY_MAX, state["capacity"] + step)
                actual_step = new_capacity - state["capacity"]

                # Execute: create actual VMs in the database.
                created = 0
                instance_type = running_vms[0].instance_type if running_vms else "t2.medium"
                base_rps = 50
                pattern = (running_vms[0].workload_pattern or "steady") if running_vms else "steady"
                for _ in range(actual_step):
                    try:
                        _create_autoscale_vm(org_id, instance_type, base_rps, pattern)
                        created += 1
                    except Exception:
                        db.session.rollback()
                        break

                if created > 0:
                    state["capacity"] = state["capacity"] + created
                    reason = (
                        f"BPI={bpi:.1f} > target={target_bpi:.1f} — "
                        f"queue={queue_total_ms:.0f}ms, p95={p95_latency_ms:.0f}ms, "
                        f"drops={dropped_total}, +{created} instance(s) created"
                    )
                    print(
                        f"[CONTROL_PLANE:SCALE_OUT] org={org_id} "
                        f"created={created} decision=bpi_exceeded "
                        f"bpi={bpi:.2f}>target={target_bpi:.2f} "
                        f"queue={queue_total_ms:.0f}ms new_capacity={state['capacity']}/{_GLOBAL_MAX_VMS}"
                    )
                    actions.append({
                        "type": "scale_up",
                        "capacity": state["capacity"],
                        "bpi": round(bpi, 2),
                        "target_bpi": round(target_bpi, 2),
                        "created": created,
                        "reason": reason,
                    })
                    state["last_action_time"] = current_time
                    action_taken = True

            elif (
                bpi < target_bpi * _SCALE_IN_BPI_RATIO
                and latency_state == "OK"
                and drops_state == "OK"
                and system_risk != "rising"
                and state["capacity"] > _CAPACITY_MIN
            ):
                # SCALE IN — only when BPI is well below target AND no SLO breach.
                # Execute: terminate one autoscale-created VM.
                terminated = _terminate_autoscale_vm(org_id)
                if terminated:
                    state["capacity"] -= 1
                    reason = (
                        f"BPI={bpi:.1f} < target×0.7={target_bpi * _SCALE_IN_BPI_RATIO:.1f} — "
                        f"queue stable, latency/drops OK — 1 instance terminated"
                    )
                    print(
                        f"[CONTROL_PLANE:SCALE_IN] org={org_id} "
                        f"terminated={terminated} decision=bpi_below_threshold "
                        f"bpi={bpi:.2f}<target*0.7={target_bpi * _SCALE_IN_BPI_RATIO:.2f} "
                        f"new_capacity={state['capacity']}/{_GLOBAL_MAX_VMS}"
                    )
                    actions.append({
                        "type": "scale_down",
                        "capacity": state["capacity"],
                        "bpi": round(bpi, 2),
                        "target_bpi": round(target_bpi, 2),
                        "terminated": terminated,
                        "reason": reason,
                    })
                    state["last_action_time"] = current_time
                    action_taken = True

            # Publish scaling_decision event for observability.
            if action_taken:
                try:
                    from app.services.event_bus import event_bus, EVENT_SCALING_DECISION
                    event_bus.publish(
                        EVENT_SCALING_DECISION,
                        org_id=org_id,
                        payload={"action": actions[0], "alerts": org_alerts},
                    )
                except Exception:
                    pass
        
        scaling_state[org_id] = state
        capacity = state["capacity"]
        if actions:
            refreshed_vms = VirtualMachine.query.filter_by(
                organization_id=org_id,
            ).filter(VirtualMachine.status != ResourceStatus.TERMINATED).all()
            total_vms = len(refreshed_vms)
            running_vms = [vm for vm in refreshed_vms if vm.status == ResourceStatus.RUNNING]
            running_vms_count = len(running_vms)
            current_hourly_cost = sum(float(vm.hourly_rate or 0) for vm in running_vms)
        
        # Build learning explanation based on actions
        if actions:
            action_type = actions[0].get("type")
            _bpi_val = actions[0].get("bpi", 0)
            _tgt_val = actions[0].get("target_bpi", 0)
            if action_type == "scale_up":
                learning_insight = {
                    "title": "Scale-out triggered (BPI target tracking)",
                    "what_happened": (
                        f"Backlog per instance ({_bpi_val:.1f} req/inst) exceeded "
                        f"target ({_tgt_val:.1f} req/inst derived from {_LATENCY_P95_ALARM_MS:.0f}ms SLO)."
                    ),
                    "why_it_happened": (
                        "Arrival rate exceeded drain capacity. Queue grew, pushing "
                        "waiting time above the latency SLO per instance."
                    ),
                    "system_thinking": (
                        "AWS target-tracking: desired = ceil(backlog / target_bpi). "
                        "Adding instances reduces BPI proportionally until SLO is met."
                    ),
                }
            elif action_type == "scale_down":
                learning_insight = {
                    "title": "Scale-in triggered (BPI below threshold)",
                    "what_happened": (
                        f"BPI ({_bpi_val:.1f}) fell below 70% of target "
                        f"({_tgt_val * _SCALE_IN_BPI_RATIO:.1f}). Latency and drops OK."
                    ),
                    "why_it_happened": "Demand decreased; current capacity is over-provisioned.",
                    "system_thinking": (
                        "Hysteresis band (70% of target) prevents oscillation. "
                        "Removing 1 instance conservatively."
                    ),
                }
            else:
                learning_insight = {
                    "title": "System stable",
                    "what_happened": "BPI within target band",
                    "why_it_happened": "Throughput matches demand",
                    "system_thinking": "No scaling action required",
                }
        else:
            learning_insight = {
                "title": "System stable",
                "what_happened": f"BPI={bpi:.1f}, target={target_bpi:.1f} — within band or in cooldown",
                "why_it_happened": "No SLO breach detected",
                "system_thinking": "Thermostat steady — no scaling required",
            }
        
        # Build alerts with state
        alerts = []
        
        if cpu_bottleneck:
            alerts.append({
                "type": "cpu",
                "state": cpu_state,
                "level": "critical" if cpu_state == "ALARM" else "normal",
                "message": "High CPU usage detected"
            })
        
        if memory_bottleneck:
            alerts.append({
                "type": "memory",
                "state": memory_state,
                "level": "critical" if memory_state == "ALARM" else "normal",
                "message": "High memory usage detected"
            })
        
        if system_risk == "rising":
            alerts.append({
                "type": "trend",
                "state": trend_state,
                "level": "warning" if trend_state == "ALARM" else "normal",
                "message": "CPU trend increasing"
            })
        
        alert_count = len(alerts)
    elif running_vms:
        # Running VMs exist but none have valid metrics
        cpu_avg = 0.0
        memory_avg = 0.0
        max_cpu = 0.0
        max_memory = 0.0
        smoothed_max_cpu = 0.0
        smoothed_max_memory = 0.0
        cpu_bottleneck = False
        memory_bottleneck = False
        system_pressure = "normal"
        cpu_trend = "stable"
        system_risk = "normal"
        alerts = []
        alert_count = 0
        transitions = []
        actions = []
        capacity = running_vms_count
        learning_insight = {
            "title": "System stable",
            "what_happened": "No valid metrics available",
            "why_it_happened": "Running VMs lack CPU/memory data",
            "system_thinking": "Waiting for metric collection"
        }
    else:
        cpu_avg = 0.0
        memory_avg = 0.0
        max_cpu = 0.0
        max_memory = 0.0
        smoothed_max_cpu = 0.0
        smoothed_max_memory = 0.0
        cpu_bottleneck = False
        memory_bottleneck = False
        system_pressure = "normal"
        cpu_trend = "stable"
        system_risk = "normal"
        alerts = []
        alert_count = 0
        transitions = []
        actions = []
        capacity = running_vms_count
        learning_insight = {
            "title": "System stable",
            "what_happened": "No resources detected",
            "why_it_happened": "No VMs running",
            "system_thinking": "System idle"
        }
    
    # Module 3/4: attach workload snapshot + topology without removing keys.
    workload_block = _workload_snapshot_for(org_id)
    topology_block = _topology_for(org_id)
    security_block = _security_for(org_id)
    cost_block = _cost_for(org_id)
    governance_block = _governance_for(org_id)
    runtime_block = _runtime_for(org_id)
    telemetry_block = _telemetry_for(org_id)

    active_threats = security_block.get('active_threats', 0)
    security_score = security_block.get('security_score', 100)
    compliance_score = governance_block.get('compliance_score', 100)
    current_month_spend = cost_block.get('current_month_spend', 0.0)
    monthly_spend = cost_block.get('monthly_spend', 0.0)
    budgets = cost_block.get('budgets', [])

    snapshot = {
        'org_id': org_id,
        'organization_id': org_id,
        'total_vms': total_vms,
        'running_vms': running_vms_count,
        'cpu_avg': round(cpu_avg, 2),
        'memory_avg': round(memory_avg, 2),
        'max_cpu': round(max_cpu, 2),
        'max_memory': round(max_memory, 2),
        'smoothed_max_cpu': round(smoothed_max_cpu, 2),
        'smoothed_max_memory': round(smoothed_max_memory, 2),
        'cpu_bottleneck': cpu_bottleneck,
        'memory_bottleneck': memory_bottleneck,
        'system_pressure': system_pressure,
        'cpu_trend': cpu_trend,
        'system_risk': system_risk,
        'alerts': alerts,
        'alert_count': alert_count,
        'alert_transitions': transitions,
        'alert_states': alert_states.get(org_id, {}),
        'actions': actions,
        'capacity': capacity,
        'learning_insight': learning_insight,
        # BPI observability (Task 1) — let dashboard render the scaling signal
        'bpi': round(bpi, 2),
        'target_bpi': round(target_bpi, 2),
        'avg_service_time_ms': round(avg_service_time_ms, 3),
        # Transparency (Bug #2 follow-up): expose both numbers so the user
        # can see the divergence between desired (autoscaler) and running
        # (simulator). In a real AWS deployment, the ASG reconciler would
        # spawn EC2 instances to close the gap.
        'desired_capacity': capacity,
        'running_capacity': running_vms_count,
        # Module 4 extensions
        'workload': workload_block,
        # Module 1 extension
        'topology': topology_block,
        'security': security_block,
        'costs': cost_block,
        'governance': governance_block,
        'runtime': runtime_block,
        'cost_trend': telemetry_block.get('cost_trend', []),
        'utilization_trend': telemetry_block.get('utilization_trend', []),
        'recent_activity': telemetry_block.get('recent_activity', []),
        'workload_explanation': telemetry_block.get('workload_explanation', {}),
        'recovery_state': runtime_block.get('recovery_state', 'idle'),
        'active_threats': active_threats,
        'security_score': security_score,
        'compliance_score': compliance_score,
        'current_month_spend': current_month_spend,
        'monthly_spend': monthly_spend,
        'budgets': budgets,
        'current_hourly_cost': round(current_hourly_cost, 4),
    }

    try:
        from app.services.operational_insights_engine import operational_insights_engine
        from app.services.topology_mini_map import build_topology_mini_map
        from app.services.cost_performance_engine import analyze_cost_performance

        snapshot['operational_insights'] = operational_insights_engine.generate(snapshot, org_id=org_id)
        snapshot['topology_mini_map'] = build_topology_mini_map(org_id, snapshot)
        snapshot['cost_performance'] = analyze_cost_performance(org_id, snapshot)
    except Exception:
        snapshot['operational_insights'] = {
            'org_id': org_id,
            'fresh': True,
            'freshness_seconds': 0.0,
            'summary': {
                'severity': 'info',
                'title': 'Operational insights unavailable',
                'message': 'Insight generation is temporarily unavailable.',
                'recommended_actions': ['Retry on the next control-plane tick.'],
            },
            'insight_count': 0,
            'insights': [],
        }
        snapshot['topology_mini_map'] = {
            'org_id': org_id,
            'fresh': True,
            'freshness_seconds': 0.0,
            'summary': {
                'node_count': 0,
                'edge_count': 0,
                'vm_count': 0,
                'database_count': 0,
                'security_group_count': 0,
                'active_threats': 0,
                'unhealthy_node_count': 0,
                'health': 'green',
            },
            'nodes': [],
            'edges': [],
            'unhealthy_node_ids': [],
            'active_threat_overlays': [],
            'scaling': {
                'direction': 'steady',
                'desired_capacity': snapshot.get('capacity', 0),
                'running_capacity': snapshot.get('running_capacity', 0),
                'bpi': snapshot.get('bpi', 0),
                'target_bpi': snapshot.get('target_bpi', 0),
            },
        }
        snapshot['cost_performance'] = {
            'org_id': org_id,
            'fresh': True,
            'freshness_seconds': 0.0,
            'summary': {
                'efficiency_score': 100.0,
                'cost_pressure_score': 0.0,
                'underutilized_count': 0,
                'overspending_count': 0,
                'resource_count': 0,
                'utilization_cost_correlation': 0.0,
                'average_utilization': 0.0,
                'average_hourly_rate': 0.0,
                'current_hourly_cost': 0.0,
                'potential_monthly_savings': 0.0,
                'potential_monthly_savings_pct': 0.0,
                'top_recommendation': 'No running resources detected.',
            },
            'underutilized_resources': [],
            'overspending_resources': [],
            'recommendations': [],
            'trend': [],
            'resources': [],
        }

    return snapshot


def run_control_plane_loop():
    """Background task: refresh snapshot cache + emit real-time dashboard updates.

    Runs every _cache_ttl seconds (2 s by default).  All API endpoints
    read from _snapshot_cache so they never block on heavy computation.
    """
    from app import socketio
    from app.models.organization import Organization

    while True:
        t0 = time.time()
        try:
            orgs = Organization.query.all()
            for org in orgs:
                snap_t0 = time.time()
                snapshot = _compute_org_snapshot(org.id)
                snapshot['timestamp'] = time.time()
                with _cache_lock:
                    _snapshot_cache[org.id] = snapshot
                socketio.emit(
                    "dashboard_update",
                    snapshot,
                    room=f"org_{org.id}",
                    namespace="/metrics"
                )
                # TASK 6: log per-org snapshot compute time
                elapsed_ms = round((time.time() - snap_t0) * 1000, 1)
                if elapsed_ms > 500:
                    print(f"[CONTROL_PLANE] org={org.id} snapshot took {elapsed_ms} ms — consider reducing VM count")
        except Exception:
            pass
        # TASK 4: sleep between iterations — prevents busy-loop and CPU saturation
        socketio.sleep(_cache_ttl)  # 2 s


def start_control_plane_loop():
    """Launch run_control_plane_loop as a SocketIO background task (idempotent)."""
    from app import socketio
    global _control_plane_task
    with _control_plane_lock:
        if _control_plane_task is not None:
            task_alive = getattr(_control_plane_task, 'is_alive', None)
            if callable(task_alive):
                try:
                    if task_alive():
                        return
                except Exception:
                    pass
            dead_flag = getattr(_control_plane_task, 'dead', None)
            if dead_flag is not None and not dead_flag:
                return
        _control_plane_task = socketio.start_background_task(run_control_plane_loop)
