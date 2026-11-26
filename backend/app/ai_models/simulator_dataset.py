"""Simulator-domain telemetry and labelled synthetic training data for the threat detector.

Why this exists (ML_EVIDENCE.md, limitation 1): the detector was trained only on CICIDS2017
flows rescaled to "VM metrics", and attack scenarios reached it with four of its ten features
missing (sent as 0). It classified every simulator attack as normal.

This module provides
- ``vm_traffic_metrics``: the formula that turns VM utilisation into traffic features. The live
  simulator (``ResourceSimulator._build_vm_traffic_metrics``) uses this same function.
- ``build_attack_scenario``: the attack templates used by Security → Simulate Attack, now
  emitting all ten model features with the same derivations as live telemetry.
- ``simulator_frame``: a seeded, labelled synthetic dataset (normal Data-Generator telemetry
  plus jittered attack scenarios). It is *synthetic*: labels are known because the generator
  produced the rows. Training and evaluation use disjoint seeds, and evaluation also uses an
  intensity band never seen in training (see ``scripts/evaluate_threat_detector.py``).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd

LABELS = {'normal': 0, 'ddos': 1, 'port_scan': 2, 'brute_force': 3}
INTENSITY_SCALE = {'low': 1.0, 'medium': 1.5, 'high': 2.2}
TRAIN_SEED, TRAIN_BAND = 1000, (0.8, 2.4)  # covers every UI intensity (low 1.0 … high 2.2)

# Attack templates (unchanged from earlier builds) plus per-step increments.
_TEMPLATES = {
    'brute_force': (
        {'requests_per_minute': 1100, 'avg_latency_ms': 180, 'error_rate': 0.09, 'bytes_in': 420000,
         'bytes_out': 760000, 'active_connections': 120, 'auth_failures': 18},
        [{}, {'requests_per_minute': 180, 'avg_latency_ms': 20, 'error_rate': 0.01, 'auth_failures': 6},
         {'requests_per_minute': 320, 'avg_latency_ms': 35, 'error_rate': 0.015, 'auth_failures': 10}],
    ),
    'port_scan': (
        {'requests_per_minute': 2200, 'avg_latency_ms': 95, 'error_rate': 0.04, 'bytes_in': 760000,
         'bytes_out': 1220000, 'active_connections': 210, 'auth_failures': 2},
        [{}, {'requests_per_minute': 250, 'avg_latency_ms': 10, 'error_rate': 0.005, 'auth_failures': 1},
         {'requests_per_minute': 420, 'avg_latency_ms': 15, 'error_rate': 0.008, 'auth_failures': 2}],
    ),
    'ddos': (
        {'requests_per_minute': 4200, 'avg_latency_ms': 240, 'error_rate': 0.12, 'bytes_in': 2_400_000,
         'bytes_out': 6_500_000, 'active_connections': 180, 'auth_failures': 4},
        [{}, {'requests_per_minute': 900, 'avg_latency_ms': 40, 'error_rate': 0.01, 'auth_failures': 1},
         {'requests_per_minute': 1700, 'avg_latency_ms': 70, 'error_rate': 0.02, 'auth_failures': 2}],
    ),
}
# Fields that grow with attack intensity (latency/error rate grow sub-linearly).
_SCALED = {'requests_per_minute': 1.0, 'bytes_in': 1.0, 'bytes_out': 1.0, 'active_connections': 1.0,
           'avg_latency_ms': 0.6, 'error_rate': 0.6}


def _complete(row):
    """Derive the remaining model features exactly like live telemetry does."""
    row['network_in_mbps'] = round(row['bytes_in'] / 125000, 2)
    row['network_out_mbps'] = round(row['bytes_out'] / 125000, 2)
    # Each request touches storage; the simulator's I/O model is proportional to request rate.
    row.setdefault('disk_read_iops', round(20 + row['requests_per_minute'] * 0.03, 2))
    row.setdefault('disk_write_iops', round(10 + row['requests_per_minute'] * 0.012, 2))
    return row


def build_attack_scenario(attack_type, intensity='medium', scale=None, rng=None, jitter=0.0):
    """Rows of one attack. ``intensity`` (low/medium/high) or an explicit ``scale`` sets the size;
    ``rng`` + ``jitter`` add multiplicative log-normal noise (used only to build datasets)."""
    attack_type = (attack_type or 'ddos').strip().lower()
    if attack_type not in _TEMPLATES:
        attack_type = 'ddos'
    if scale is None:
        scale = INTENSITY_SCALE.get((intensity or 'medium').strip().lower(), 1.5)
    base, increments = _TEMPLATES[attack_type]
    rows = []
    for step in increments:
        row = {}
        for key, value in base.items():
            factor = scale ** _SCALED[key] if key in _SCALED else 1.0
            row[key] = value * factor + step.get(key, 0)
        if rng is not None and jitter:
            for key in row:
                row[key] *= float(rng.lognormal(0.0, jitter))
        row['requests_per_minute'] = int(row['requests_per_minute'])
        row['bytes_in'], row['bytes_out'] = int(row['bytes_in']), int(row['bytes_out'])
        row['active_connections'] = int(row['active_connections'])
        row['avg_latency_ms'] = round(row['avg_latency_ms'], 2)
        row['error_rate'] = round(min(row['error_rate'], 0.95), 4)
        row['auth_failures'] = int(row['auth_failures'])
        rows.append(_complete(row))
    return rows


def vm_traffic_metrics(vm, rng):
    """Traffic features for a VM from its utilisation (``rng`` provides ``uniform``)."""
    cpu = float(vm.cpu_utilization or 0)
    memory = float(vm.memory_utilization or 0)
    network_in = float(vm.network_in_mbps or 0)
    network_out = float(vm.network_out_mbps or 0)
    requests_per_minute = int(max(120, network_in * 14 + cpu * 24 + rng.uniform(0, 100)))
    avg_latency_ms = round(max(15.0, 30 + cpu * 1.8 + network_out * 0.3 + rng.uniform(-4, 18)), 2)
    error_rate = round(min(0.35, max(0.002, (cpu / 100.0) * 0.05 + rng.uniform(0.0, 0.01))), 4)
    auth_failures = int(max(0, (cpu - 70) / 5 + rng.uniform(0, 4))) if cpu > 70 else int(rng.uniform(0, 2))
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


def simulator_frame(seed, band=TRAIN_BAND, normal_rows=600, attack_rows_per_class=200, jitter=0.12):
    """Labelled synthetic simulator telemetry. Same seed → identical frame."""
    from app.ai_models.data_generator import SyntheticDataGenerator

    rng = np.random.default_rng(seed)
    generator = SyntheticDataGenerator(seed=seed)
    rows = []
    instance_types = [('t2.micro', 1, 1), ('t2.small', 1, 2), ('t2.medium', 2, 4), ('t2.large', 2, 8)]
    while len(rows) < normal_rows:
        itype, vcpu, mem = instance_types[int(rng.integers(len(instance_types)))]
        vm = SimpleNamespace(instance_type=itype, vcpu=vcpu, memory_gb=mem, memory_utilization=float(rng.uniform(20, 70)),
                             cpu_utilization=float(rng.uniform(5, 85)), network_in_mbps=0, network_out_mbps=0,
                             requests_per_second=100, disk_read_iops=0, disk_write_iops=0)
        moment = datetime(2026, 10, 1 + int(rng.integers(28)), int(rng.integers(24)))
        vm.__dict__.update(generator.generate_vm_metrics(vm, moment))
        rows.append({**vm_traffic_metrics(vm, rng), 'label': LABELS['normal']})
    for attack in ('ddos', 'port_scan', 'brute_force'):
        produced = 0
        while produced < attack_rows_per_class:
            scale = float(rng.uniform(*band))
            for row in build_attack_scenario(attack, scale=scale, rng=rng, jitter=jitter):
                if produced < attack_rows_per_class:
                    rows.append({**row, 'label': LABELS[attack]})
                    produced += 1
    return pd.DataFrame(rows)
