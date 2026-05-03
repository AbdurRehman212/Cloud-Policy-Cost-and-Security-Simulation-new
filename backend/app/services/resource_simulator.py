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

from app import db, socketio
from app.ai_models.data_generator import SyntheticDataGenerator
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

    def __init__(self, tick_interval: int = 5, history_limit: int = 120):
        self.tick_interval = tick_interval
        self.history_limit = history_limit
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
        # Per-VM previous CPU for smooth transitions
        self._prev_cpu: dict[str, float] = {}

    def _get_generator(self) -> SyntheticDataGenerator:
        if self._generator is None:
            self._generator = SyntheticDataGenerator()
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
        """Main simulation loop."""
        if self._app is None:
            return

        with self._app.app_context():
            while self.running and not self.stop_event.is_set():
                try:
                    self._update_resources()
                except Exception as exc:  # pragma: no cover - defensive runtime logging
                    db.session.rollback()
                    print(f'Simulation error: {exc}')
                finally:
                    self.stop_event.wait(self.tick_interval)

    def _update_resources(self):
        """Update all running resources with dataset-backed telemetry."""
        generator = self._get_generator()
        moment = datetime.utcnow()

        vms = VirtualMachine.query.filter_by(status=ResourceStatus.RUNNING).all()
        dbs = Database.query.filter_by(status=ResourceStatus.RUNNING).all()

        for vm in vms:
            metrics = generator.generate_vm_metrics(vm, moment)

            # --- Realistic VM behavior with instance specs ---
            profile = self.INSTANCE_PROFILES.get(vm.instance_type or '', {'vcpu': 2, 'ram': 4, 'baseline_cpu': 30.0})
            base_cpu = profile['baseline_cpu']
            base_mem = profile['ram'] * 0.7  # Base memory as % of RAM
            
            # Time-of-day based CPU calculation
            hour = moment.hour
            time_factor = (hour / 24) * 2 * math.pi
            cpu = base_cpu + math.sin(time_factor) * 15 + random.gauss(0, 5)
            
            # Spike mechanism: 3% chance, only if cpu < 70 before spike
            if vm.instance_id in self._spike_cycles:
                if self._spike_cycles[vm.instance_id] > 0:
                    cpu += 30
                    self._spike_cycles[vm.instance_id] -= 1
                else:
                    del self._spike_cycles[vm.instance_id]
            elif cpu < 70 and random.random() < 0.03:
                cpu += 30
                self._spike_cycles[vm.instance_id] = 2  # 3 cycles total (current + 2 more)
            
            # Smooth transition with previous CPU
            prev_cpu = self._prev_cpu.get(vm.instance_id, cpu)
            cpu = (prev_cpu * 0.7) + (cpu * 0.3)
            self._prev_cpu[vm.instance_id] = cpu
            
            # Memory formula with soft cap
            memory = base_mem + (cpu * 0.5) + random.gauss(0, 3)
            if memory > 90:
                memory = 90 + random.gauss(0, 2)
            
            # Clamp values 0-100
            cpu = max(0.0, min(100.0, cpu))
            memory = max(0.0, min(100.0, memory))
            
            metrics['cpu_utilization'] = round(cpu, 2)
            metrics['memory_utilization'] = round(memory, 2)

            vm.cpu_utilization = metrics['cpu_utilization']
            vm.memory_utilization = metrics['memory_utilization']
            vm.disk_read_iops = metrics['disk_read_iops']
            vm.disk_write_iops = metrics['disk_write_iops']
            vm.network_in_mbps = metrics['network_in_mbps']
            vm.network_out_mbps = metrics['network_out_mbps']
            vm.total_runtime_hours += self.tick_interval / 3600
            self._upsert_cost_record(vm, 'vm', moment, metrics)
            self._analyze_vm_security(vm, moment)

            # Store per-VM metric history point
            self.vm_metric_history[vm.instance_id].append({
                'timestamp': moment.isoformat(),
                'name': moment.strftime('%H:%M'),
                'cpu': metrics['cpu_utilization'],
                'memory': metrics['memory_utilization'],
                'network_in': round(float(vm.network_in_mbps or 0), 2),
                'network_out': round(float(vm.network_out_mbps or 0), 2),
            })

        for database in dbs:
            metrics = generator.generate_database_metrics(database, moment)
            database.cpu_utilization = metrics['cpu_utilization']
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
            # Clear spike and prev_cpu tracking for stopped VMs
            if vm.instance_id in self._spike_cycles:
                del self._spike_cycles[vm.instance_id]
            if vm.instance_id in self._prev_cpu:
                del self._prev_cpu[vm.instance_id]

        db.session.commit()

        # Emit resource_update events for each org with running resources
        # Query DB for current states to ensure consistency
        for org_id in ({vm.organization_id for vm in vms} | {database.organization_id for database in dbs}):
            # Query DB for current VM states
            total_vms = VirtualMachine.query.filter_by(
                organization_id=org_id,
            ).filter(VirtualMachine.status != 'terminated').count()
            running_vms = VirtualMachine.query.filter_by(
                organization_id=org_id,
                status='running'
            ).count()
            
            # Query DB for running resources to compute averages
            running_vms_objs = VirtualMachine.query.filter_by(
                organization_id=org_id,
                status='running'
            ).all()
            running_dbs_objs = Database.query.filter_by(
                organization_id=org_id,
                status='running'
            ).all()
            all_running = running_vms_objs + running_dbs_objs
            
            # Compute cpu_avg and memory_avg only from running VMs
            if all_running:
                cpu_avg = sum(float(r.cpu_utilization or 0) for r in all_running) / len(all_running)
                memory_avg = sum(float(r.memory_utilization or 0) for r in all_running) / len(all_running)
            else:
                cpu_avg = 0.0
                memory_avg = 0.0
            
            socketio.emit(
                'resource_update',
                {
                    'total_vms': total_vms,
                    'running_vms': running_vms,
                    'cpu_avg': round(cpu_avg, 2),
                    'memory_avg': round(memory_avg, 2),
                },
                room=f'org_{org_id}',
                namespace='/metrics'
            )

        self._tick_count += 1
        if self._tick_count % 6 == 0:
            org_ids = {vm.organization_id for vm in vms}
            for org_id in org_ids:
                self.check_autoscaling(org_id, self._app)

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

    def check_autoscaling(self, org_id, app):
        """Autoscale overloaded VMs and flag underutilized ones."""
        if app is None:
            return

        with app.app_context():
            vms = VirtualMachine.query.filter_by(
                organization_id=org_id,
                status=ResourceStatus.RUNNING,
            ).all()
            for vm in vms:
                history = list(self.vm_metric_history.get(vm.instance_id, []))
                if not history:
                    continue

                recent_24 = history[-24:]
                recent_60 = history[-60:]
                now = datetime.utcnow()
                last_scaled = self.last_scaled_at.get(vm.instance_id)

                if (
                    len(recent_24) >= 24
                    and float(np.mean([point.get('cpu', 0.0) for point in recent_24])) > 70.0
                    and (
                        last_scaled is None
                        or (now - last_scaled).total_seconds() >= 600
                    )
                ):
                    timestamp = now.strftime('%Y%m%d%H%M%S')
                    scaled_vm = VirtualMachine(
                        organization_id=vm.organization_id,
                        name=f'{vm.name}-scaled-{timestamp}',
                        instance_id=f'{vm.instance_id}-scaled-{timestamp}',
                        instance_type=vm.instance_type,
                        status=ResourceStatus.PENDING,
                        vcpu=vm.vcpu,
                        memory_gb=vm.memory_gb,
                        storage_gb=vm.storage_gb,
                        private_ip=f'10.0.{random.randint(0, 255)}.{random.randint(1, 254)}',
                        public_ip=None,
                        subnet_id=vm.subnet_id,
                        vpc_id=vm.vpc_id,
                        cpu_utilization=0.0,
                        memory_utilization=0.0,
                        disk_read_iops=0.0,
                        disk_write_iops=0.0,
                        network_in_mbps=0.0,
                        network_out_mbps=0.0,
                        image_id=vm.image_id,
                        key_name=vm.key_name,
                        hourly_rate=vm.hourly_rate,
                    )
                    scaled_vm.security_groups = list(vm.security_groups)
                    db.session.add(scaled_vm)
                    db.session.flush()

                    self.last_scaled_at[vm.instance_id] = now
                    db.session.add(
                        AuditLog(
                            organization_id=org_id,
                            action=f'Auto Scaling triggered for {vm.name}',
                            resource_type='vm',
                            resource_id=vm.instance_id,
                            new_values={
                                'scaled_vm_id': scaled_vm.id,
                                'scaled_instance_id': scaled_vm.instance_id,
                                'source_vm_id': vm.id,
                            },
                        )
                    )
                    db.session.commit()

                    socketio.emit(
                        'autoscaling_event',
                        {
                            'org_id': org_id,
                            'message': 'Auto Scaling triggered for {name}'.format(name=vm.name),
                            'source_vm': {
                                'id': vm.id,
                                'instance_id': vm.instance_id,
                                'name': vm.name,
                            },
                            'scaled_vm': {
                                'id': scaled_vm.id,
                                'instance_id': scaled_vm.instance_id,
                                'name': scaled_vm.name,
                            },
                        },
                        room=f'org_{org_id}',
                        namespace='/metrics',
                    )

                    from app.routes.resources import _complete_vm_creation

                    socketio.start_background_task(
                        _complete_vm_creation,
                        scaled_vm.id,
                        app,
                    )

                if len(recent_60) >= 60:
                    avg_cpu = float(np.mean([point.get('cpu', 0.0) for point in recent_60]))
                    if avg_cpu < 10.0:
                        self.waste_candidates.add(vm.id)
                        socketio.emit(
                            'waste_detected',
                            {
                                'org_id': org_id,
                                'vm_id': vm.id,
                                'instance_id': vm.instance_id,
                                'name': vm.name,
                                'avg_cpu': round(avg_cpu, 2),
                                'message': 'Low utilization - consider stopping',
                            },
                            room=f'org_{org_id}',
                            namespace='/metrics',
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
        requests_per_minute = int(max(120, network_in * 20 + cpu * 35 + random.uniform(0, 160)))
        avg_latency_ms = round(max(15.0, 35 + cpu * 2.4 + network_out * 0.45 + random.uniform(-5, 25)), 2)
        error_rate = round(min(0.42, max(0.002, (cpu / 100.0) * 0.06 + random.uniform(0.0, 0.015))), 4)
        auth_failures = int(max(0, (cpu - 70) / 5 + random.uniform(0, 4))) if cpu > 70 else int(random.uniform(0, 2))

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
                'cpu': max(0.0, round(cpu + diurnal + random.gauss(0, 3.5), 2)),
                'memory': max(0.0, round(memory + diurnal * 0.6 + random.gauss(0, 2.5), 2)),
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
        }

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

    def simulate_load_test(self, vm_id, duration_seconds=60, intensity='medium'):
        """Simulate load test on a specific VM."""
        vm = VirtualMachine.query.get(vm_id)
        if not vm or vm.status != ResourceStatus.RUNNING:
            return False

        intensity_factor = {'low': 1.5, 'medium': 3, 'high': 5}.get(intensity, 3)
        original_cpu = vm.cpu_utilization

        def apply_load():
            start_time = time.time()
            while time.time() - start_time < duration_seconds:
                vm.cpu_utilization = min(100, original_cpu * intensity_factor + np.random.normal(0, 10))
                db.session.commit()
                time.sleep(1)
            vm.cpu_utilization = original_cpu
            db.session.commit()

        Thread(target=apply_load, daemon=True).start()
        return True
