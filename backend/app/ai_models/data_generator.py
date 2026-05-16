"""Synthetic data generation backed by real staged datasets when available."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

import numpy as np
import pandas as pd

from app.data_sources.real_datasets import dataset_catalog

logger = logging.getLogger(__name__)


def _safe_float(value, default):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    if np.isnan(result):
        return float(default)
    return float(result)


def _pick_numeric_mean(frame: pd.DataFrame, candidates: Iterable[str], default: float) -> float:
    for column in candidates:
        if column in frame.columns:
            series = pd.to_numeric(frame[column], errors='coerce').dropna()
            if not series.empty:
                return float(series.mean())
    return float(default)


def _pick_numeric_std(frame: pd.DataFrame, candidates: Iterable[str], default: float) -> float:
    for column in candidates:
        if column in frame.columns:
            series = pd.to_numeric(frame[column], errors='coerce').dropna()
            if not series.empty and float(series.std(ddof=0) or 0) > 0:
                return float(series.std(ddof=0))
    return float(default)


@dataclass
class SyntheticDataGenerator:
    """Generate realistic metrics for the digital twin simulator."""

    seed: int = 1337
    rng: np.random.Generator = field(init=False, repr=False)

    def __post_init__(self):
        self.rng = np.random.default_rng(self.seed)
        self.finops_frame = dataset_catalog.load_finops_frame()
        self.security_frame = dataset_catalog.load_security_frame()
        self.core_frame = dataset_catalog.load_simulator_core_frame()
        self.governance_frame = dataset_catalog.load_governance_frame()
        self.baseline = self._build_baseline()
        source_desc = (
            f'finops frame ({len(self.finops_frame)} rows)'
            if not self.finops_frame.empty
            else f'core frame ({len(self.core_frame)} rows)'
            if not self.core_frame.empty
            else 'hardcoded defaults'
        )
        logger.info(
            '[data_generator] Baseline built from %s: cpu_mean=%.2f%%, memory_mean=%.2f%%',
            source_desc, self.baseline['cpu_mean'], self.baseline['memory_mean'],
        )

    def _build_baseline(self):
        source = self.finops_frame if not self.finops_frame.empty else self.core_frame
        if source.empty:
            source = pd.DataFrame()
        return {
            'cpu_mean': _pick_numeric_mean(source, ['cpu_utilization_avg', 'cpu_avg', 'cpu', 'cpu_utilization'], 28.0),
            'cpu_std': max(_pick_numeric_std(source, ['cpu_utilization_avg', 'cpu_avg', 'cpu', 'cpu_utilization'], 8.0), 1.0),
            'memory_mean': _pick_numeric_mean(source, ['memory_utilization_avg', 'memory_avg', 'memory_utilization'], 42.0),
            'memory_std': max(_pick_numeric_std(source, ['memory_utilization_avg', 'memory_avg', 'memory_utilization'], 10.0), 1.0),
            'disk_read_mean': _pick_numeric_mean(source, ['disk_read_iops', 'read_iops'], 95.0),
            'disk_write_mean': _pick_numeric_mean(source, ['disk_write_iops', 'write_iops'], 55.0),
            'network_mean': _pick_numeric_mean(source, ['network_in_mbps', 'network_mbps'], 45.0),
            'database_connections_mean': _pick_numeric_mean(source, ['database_connections', 'connections'], 18.0),
            'cost_mean': _pick_numeric_mean(source, ['total_cost', 'hourly_cost'], 1.0),
            'security_rpm_mean': _pick_numeric_mean(self.security_frame, ['requests_per_minute'], 1600.0),
            'security_error_mean': _pick_numeric_mean(self.security_frame, ['error_rate'], 0.04),
        }

    @staticmethod
    def _instance_factor(instance_type: str, cpu_units: float, memory_gb: float) -> float:
        normalized = (instance_type or '').lower()
        mapping = {
            't2.micro': 0.65,
            't2.small': 0.82,
            't2.medium': 1.0,
            't2.large': 1.18,
            'm5.large': 1.22,
            'm5.xlarge': 1.45,
            'c5.large': 1.08,
            'c5.xlarge': 1.3,
            'db.t2.micro': 0.58,
            'db.t2.small': 0.72,
            'db.m5.large': 1.18,
            'db.r5.large': 1.32,
        }
        base = mapping.get(normalized, 1.0)
        cpu_bonus = max(0.0, (cpu_units or 1.0) - 1.0) * 0.08
        memory_bonus = max(0.0, (memory_gb or 1.0) - 1.0) * 0.02
        return base + cpu_bonus + memory_bonus

    @staticmethod
    def _business_hour_factor(moment: datetime) -> float:
        hour = moment.hour
        if 9 <= hour <= 17:
            return 1.18
        if 18 <= hour <= 22:
            return 1.05
        return 0.82

    @staticmethod
    def _bounded(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
        return float(max(lower, min(upper, value)))

    def generate_vm_metrics(self, vm, moment: datetime | None = None):
        """Generate synthetic VM telemetry using baseline dataset patterns."""
        moment = moment or datetime.utcnow()
        instance_factor = self._instance_factor(vm.instance_type, vm.vcpu, vm.memory_gb)
        business_factor = self._business_hour_factor(moment)
        cpu_noise = self.rng.normal(0, self.baseline['cpu_std'] * 0.35)
        memory_noise = self.rng.normal(0, self.baseline['memory_std'] * 0.22)
        spike = self.rng.exponential(8.0) if self.rng.random() < 0.05 else 0.0

        cpu_util = self._bounded(
            self.baseline['cpu_mean'] * instance_factor * business_factor + cpu_noise + spike,
        )
        memory_util = self._bounded(
            (vm.memory_utilization * 0.55 if vm.memory_utilization else self.baseline['memory_mean'] * 0.4)
            + cpu_util * 0.38
            + memory_noise,
        )
        disk_read = max(0.0, self.rng.normal(self.baseline['disk_read_mean'], self.baseline['disk_read_mean'] * 0.22) + cpu_util * 1.4)
        disk_write = max(0.0, self.rng.normal(self.baseline['disk_write_mean'], self.baseline['disk_write_mean'] * 0.2) + cpu_util * 0.9)
        network_in = max(0.0, self.rng.normal(self.baseline['network_mean'], self.baseline['network_mean'] * 0.18) + cpu_util * 1.25)
        network_out = max(0.0, network_in * self.rng.uniform(0.55, 1.6))

        return {
            'cpu_utilization': round(cpu_util, 2),
            'memory_utilization': round(memory_util, 2),
            'disk_read_iops': round(disk_read, 2),
            'disk_write_iops': round(disk_write, 2),
            'network_in_mbps': round(network_in, 2),
            'network_out_mbps': round(network_out, 2),
        }

    def generate_database_metrics(self, database, moment: datetime | None = None):
        """Generate synthetic database telemetry using baseline dataset patterns."""
        moment = moment or datetime.utcnow()
        instance_factor = self._instance_factor(database.instance_class, 1.0, database.allocated_storage_gb / 20.0)
        business_factor = self._business_hour_factor(moment)
        cpu_noise = self.rng.normal(0, self.baseline['cpu_std'] * 0.2)
        conn_noise = self.rng.poisson(2)

        cpu_util = self._bounded(
            self.baseline['cpu_mean'] * 0.75 * instance_factor * business_factor + cpu_noise + conn_noise,
        )
        db_connections = max(0, int(self.rng.normal(self.baseline['database_connections_mean'], 4) + cpu_util * 0.22))
        read_iops = max(0.0, self.rng.normal(420, 90) + db_connections * 10 + cpu_util * 2.2)
        write_iops = max(0.0, self.rng.normal(180, 45) + db_connections * 6 + cpu_util * 1.4)
        free_storage = max(0.0, (database.free_storage_space or 20.0) - self.rng.uniform(0.02, 0.28) - db_connections * 0.002)

        return {
            'cpu_utilization': round(cpu_util, 2),
            'database_connections': db_connections,
            'read_iops': round(read_iops, 2),
            'write_iops': round(write_iops, 2),
            'free_storage_space': round(free_storage, 2),
        }

    def generate_cost_estimate(self, vm_metrics: dict, db_metrics: dict | None = None) -> float:
        """Estimate a per-tick cost score from telemetry for trend generation."""
        db_metrics = db_metrics or {}
        cpu_component = _safe_float(vm_metrics.get('cpu_utilization'), 0) * 0.006
        mem_component = _safe_float(vm_metrics.get('memory_utilization'), 0) * 0.003
        io_component = (
            _safe_float(vm_metrics.get('disk_read_iops'), 0) + _safe_float(vm_metrics.get('disk_write_iops'), 0)
        ) * 0.00006
        db_component = _safe_float(db_metrics.get('database_connections'), 0) * 0.012
        return round(cpu_component + mem_component + io_component + db_component + self.baseline['cost_mean'] * 0.1, 4)

    def summarize_history(self, snapshots: list[dict]) -> list[dict]:
        """Collapse raw history snapshots into chart-friendly series data."""
        return [
            {
                'name': snapshot.get('label') or snapshot.get('timestamp'),
                'cpu': round(_safe_float(snapshot.get('cpu'), 0), 2),
                'memory': round(_safe_float(snapshot.get('memory'), 0), 2),
                'cost': round(_safe_float(snapshot.get('cost'), 0), 2),
            }
            for snapshot in snapshots
        ]
