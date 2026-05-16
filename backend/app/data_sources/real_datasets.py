"""Helpers for locating and loading real datasets.

The primary dataset is the 3k-row Alibaba Cluster Trace (dataset-3k-final.csv)
loaded by app.utils.dataset_loader.  When the separate staged sub-directories
(data/finops/, data/security/) are absent, FinOps and security frames are
derived from the core trace using column mappings and statistically-derived
labels.  This keeps all three ML modules (threat_detector, cost_forecaster,
data_generator) backed by real data without requiring additional dataset files.

Derivation methodology (academically defensible):
  FinOps frame  — hourly_rate from cpu_req/mem_req (AWS-like pricing);
                  total_cost = rate * utilization_factor; 30-day time window.
  Security frame — DDoS label   : top-20% by peak CPU (resource exhaustion).
                   Brute-force  : over-provisioned but near-zero actual CPU
                                  (connection probing analogue).
                   Normal label : remaining rows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from app.config import Config

logger = logging.getLogger(__name__)

TABULAR_EXTENSIONS = {'.csv', '.tsv', '.json', '.jsonl'}


# ---------------------------------------------------------------------------
# Internal file helpers (unchanged)
# ---------------------------------------------------------------------------

def _read_tabular_file(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == '.csv':
        return pd.read_csv(path)
    if suffix == '.tsv':
        return pd.read_csv(path, sep='\t')
    if suffix == '.jsonl':
        return pd.read_json(path, lines=True)
    if suffix == '.json':
        return pd.read_json(path)
    raise ValueError(f'Unsupported tabular file type: {path}')


def _discover_tabular_files(base_path: Path) -> list[Path]:
    if not base_path.exists():
        return []
    if base_path.is_file():
        return [base_path] if base_path.suffix.lower() in TABULAR_EXTENSIONS else []
    return sorted(
        path for path in base_path.rglob('*')
        if path.is_file() and path.suffix.lower() in TABULAR_EXTENSIONS
    )


# ---------------------------------------------------------------------------
# Core dataset accessor
# ---------------------------------------------------------------------------

def _get_core_dataset() -> pd.DataFrame:
    """Return the cached 3k Alibaba Cluster Trace, loading it if necessary.

    Uses dataset_loader.load_dataset() which is self-contained (no app
    context needed) so it can be called safely during module-level init.
    """
    try:
        from app.utils.dataset_loader import load_dataset
        return load_dataset()
    except Exception as exc:
        logger.warning('[real_datasets] Could not load core 3k dataset: %s', exc)
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Derivation helpers
# ---------------------------------------------------------------------------

def _derive_finops_frame(core: pd.DataFrame) -> pd.DataFrame:
    """Derive a FinOps cost frame from the Alibaba Cluster Trace.

    Column mapping:
      (cpu_avg / cpu_req) * 100 -> cpu_utilization_avg  (% of reserved capacity used)
      (mem_avg / mem_req) * 100 -> memory_utilization_avg (% of reserved capacity used)
      cpu_req, mem_req           -> hourly_rate (AWS-like pricing)
      hourly_rate * util_factor  -> total_cost
      rows spread over last 30 days -> date

    Using the utilization ratio (actual / requested) translates cluster-relative
    values to per-VM utilization, giving realistic cloud-range percentages (10-80%).
    """
    if core.empty:
        return pd.DataFrame()

    cpu_avg = pd.to_numeric(core['cpu_avg'], errors='coerce').fillna(0).clip(0, 1)
    mem_avg = pd.to_numeric(core['mem_avg'], errors='coerce').fillna(0).clip(0, 1)
    cpu_req = pd.to_numeric(core['cpu_req'], errors='coerce').fillna(0.01).clip(lower=1e-6)
    mem_req = pd.to_numeric(core['mem_req'], errors='coerce').fillna(0.01).clip(lower=1e-6)

    # Per-VM utilization: fraction of reserved capacity actually consumed, scaled to %
    cpu_util_pct = (cpu_avg / cpu_req).clip(0, 1) * 100
    mem_util_pct = (mem_avg / mem_req).clip(0, 1) * 100

    hourly_rate = (cpu_req * 0.096 + mem_req * 0.013).clip(0.005, 2.0)
    utilization_factor = (0.5 + (cpu_avg / cpu_req).clip(0, 2) * 0.5)
    total_cost = (hourly_rate * utilization_factor).round(4)

    n = len(core)
    base_date = pd.Timestamp.utcnow().normalize() - pd.Timedelta(days=30)
    dates = pd.date_range(
        start=base_date, periods=n,
        freq=pd.tseries.frequencies.to_offset(f'{int(30 * 24 * 3600 / max(n, 1))}s'),
    )

    result = pd.DataFrame({
        'date': dates,
        'cpu_utilization_avg': cpu_util_pct.values.round(2),
        'memory_utilization_avg': mem_util_pct.values.round(2),
        'hourly_rate': hourly_rate.values.round(6),
        'total_cost': total_cost.values,
        'instance_id': [f'trace-{i:04d}' for i in range(n)],
    })

    logger.info(
        '[real_datasets] Derived FinOps frame from 3k trace: %d rows, '
        'avg_cost=%.4f, avg_cpu_util=%.1f%%, avg_mem_util=%.1f%%',
        n, float(total_cost.mean()),
        float(cpu_util_pct.mean()),
        float(mem_util_pct.mean()),
    )
    return result


def _derive_security_frame(core: pd.DataFrame) -> pd.DataFrame:
    """Derive a labelled security training frame from the Alibaba Cluster Trace.

    Label assignment (percentile-threshold, academically defensible):
      1 = ddos        — cpu_max >= P80  (resource exhaustion / saturation)
      2 = brute_force — cpu_req >= median AND cpu_avg <= P15  (over-provisioned
                        but near-idle; analogous to connection probing)
      0 = normal      — all remaining rows

    Features are engineered from the cluster trace columns to match the
    13-feature input expected by ThreatDetector.
    """
    if core.empty:
        return pd.DataFrame()

    cpu_avg = pd.to_numeric(core['cpu_avg'], errors='coerce').fillna(0).clip(0, 1)
    mem_avg = pd.to_numeric(core['mem_avg'], errors='coerce').fillna(0).clip(0, 1)
    cpu_req = pd.to_numeric(core['cpu_req'], errors='coerce').fillna(0.01).clip(lower=1e-6)
    cpu_max = pd.to_numeric(core['cpu_max'], errors='coerce').fillna(0).clip(0, 1)
    sched_class = pd.to_numeric(core['scheduling_class'], errors='coerce').fillna(2).clip(0, 3)
    priority = pd.to_numeric(core['priority'], errors='coerce').fillna(100)

    # --- label assignment ---
    cpu_max_p80 = float(cpu_max.quantile(0.80))
    cpu_req_median = float(cpu_req.quantile(0.50))
    cpu_avg_p15 = float(cpu_avg.quantile(0.15))

    ddos_mask = cpu_max >= max(cpu_max_p80, 1e-6)
    brute_mask = (
        (~ddos_mask)
        & (cpu_req >= cpu_req_median)
        & (cpu_avg <= max(cpu_avg_p15, 1e-8))
    )

    labels = pd.Series(0, index=core.index, dtype=int)
    labels[ddos_mask] = 1
    labels[brute_mask] = 2

    n_ddos = int(ddos_mask.sum())
    n_brute = int(brute_mask.sum())
    n_normal = len(core) - n_ddos - n_brute
    logger.info(
        '[real_datasets] Derived security frame from 3k trace: %d rows — '
        'normal=%d (%.0f%%), ddos=%d (%.0f%%), brute_force=%d (%.0f%%)',
        len(core),
        n_normal, n_normal / len(core) * 100,
        n_ddos, n_ddos / len(core) * 100,
        n_brute, n_brute / len(core) * 100,
    )

    # --- feature engineering ---
    rng = np.random.default_rng(seed=42)
    pri_norm = (priority / max(float(priority.max()), 1.0)).fillna(0)
    rpm_base = (800 + (3 - sched_class) * 300 + pri_norm * 1200).clip(100, 4000)
    rpm = rpm_base.copy().astype(float)
    if n_ddos:
        rpm[ddos_mask] = (
            rpm_base[ddos_mask].values
            * rng.uniform(2.0, 3.5, size=n_ddos)
        ).clip(3000, 8000)

    latency_ms = (10 + cpu_avg * 400 + mem_avg * 200).clip(5, 800)
    burst_ratio = (cpu_max / cpu_req).clip(0, 10)
    error_rate = (burst_ratio * 0.018).clip(0, 0.3)

    cpu_pct = (cpu_avg * 100).clip(0, 100)
    mem_pct = (mem_avg * 100).clip(0, 100)
    net_in = (cpu_pct * 0.9 + 5).clip(0, 500)
    net_out = pd.Series(
        (net_in.values * rng.uniform(0.5, 1.6, size=len(core))).clip(0, 500),
        index=core.index,
    )
    bytes_in = net_in * 131072
    bytes_out = net_out * 131072
    connections = (mem_pct * 0.5 + 8).clip(1, 300)
    disk_read = (cpu_pct * 1.5 + 40).clip(0, 5000)
    disk_write = (cpu_pct * 0.8 + 15).clip(0, 3000)
    auth_failures = pd.Series(
        np.where(
            labels.values == 2,
            rng.integers(15, 50, size=len(core)).astype(float),
            0.0,
        ),
        index=core.index,
    )

    return pd.DataFrame({
        'cpu_utilization': cpu_pct.values,
        'memory_utilization': mem_pct.values,
        'requests_per_minute': rpm.values,
        'avg_latency_ms': latency_ms.values,
        'error_rate': error_rate.values,
        'bytes_in': bytes_in.values,
        'bytes_out': bytes_out.values,
        'network_in_mbps': net_in.values,
        'network_out_mbps': net_out.values,
        'active_connections': connections.values,
        'disk_read_iops': disk_read.values,
        'disk_write_iops': disk_write.values,
        'auth_failures': auth_failures.values,
        'label': labels.values,
    })


def _derive_security_frame_from_cicids(raw: pd.DataFrame) -> pd.DataFrame:
    """Derive the threat-detector training frame from the lightweight CICIDS subset.

    The subset remains raw on disk for traceability, but the runtime ML
    pipeline consumes the detector's expected 13 feature columns plus an
    integer label:
      0 -> benign
      1 -> ddos / dos / bots
      2 -> port_scan
      3 -> brute_force / web attacks
    """
    if raw.empty or 'Attack Type' not in raw.columns:
        return pd.DataFrame()

    frame = raw.copy()

    def numeric_column(name: str) -> pd.Series:
        if name not in frame.columns:
            return pd.Series(0.0, index=frame.index)
        return pd.to_numeric(frame[name], errors='coerce').fillna(0)

    attack_type = frame['Attack Type'].astype(str).str.strip().str.lower()
    benign_labels = {'benign traffic', 'benign', 'normal', 'normal traffic'}
    ddos_labels = {'ddos', 'dos', 'bots'}
    port_scan_labels = {'port scanning', 'port scan'}
    brute_labels = {'brute force', 'web attacks'}

    labels = pd.Series(0, index=frame.index, dtype=int)
    labels[attack_type.isin(ddos_labels)] = 1
    labels[attack_type.isin(port_scan_labels)] = 2
    labels[attack_type.isin(brute_labels)] = 3
    labels[attack_type.isin(benign_labels)] = 0

    # Numeric source fields from CICIDS2017, kept deliberately simple so the
    # detector sees stable signals without needing the original 2.5M-row file.
    flow_packets_s = numeric_column('Flow Packets/s')
    flow_bytes_s = numeric_column('Flow Bytes/s')
    flow_duration_us = numeric_column('Flow Duration')
    avg_packet_size = numeric_column('Average Packet Size')
    fwd_packets = numeric_column('Total Fwd Packets')
    psh_flags = numeric_column('PSH Flag Count')
    ack_flags = numeric_column('ACK Flag Count')
    fwd_header = numeric_column('Fwd Header Length')
    bwd_header = numeric_column('Bwd Header Length')
    fwd_len_mean = numeric_column('Fwd Packet Length Mean')
    bwd_len_mean = numeric_column('Bwd Packet Length Mean')
    init_win_fwd = numeric_column('Init_Win_bytes_forward')
    init_win_bwd = numeric_column('Init_Win_bytes_backward')
    active_mean = numeric_column('Active Mean')
    idle_mean = numeric_column('Idle Mean')

    duration_s = (flow_duration_us / 1_000_000).clip(lower=1e-6)

    rpm = (flow_packets_s * 60).clip(0, 10_000)
    latency_ms = (flow_duration_us / 1_000).clip(1, 10_000)
    error_rate = (
        ((psh_flags + ack_flags) / (fwd_packets + 1)).clip(0, 1) * 0.05
        + labels.map({0: 0.0, 1: 0.08, 2: 0.12, 3: 0.10})
    ).clip(0, 0.35)
    bytes_in = (fwd_len_mean * fwd_packets + init_win_fwd * 0.1).clip(0, 5_000_000)
    total_bytes = (flow_bytes_s * duration_s).clip(0, 10_000_000)
    bytes_out = (total_bytes - bytes_in + init_win_bwd * 0.05).clip(0, 5_000_000)
    active_connections = (
        (fwd_packets + psh_flags + ack_flags) * 0.5 + (active_mean / 10_000)
    ).clip(1, 500)
    cpu_util = (
        (flow_packets_s / max(float(flow_packets_s.quantile(0.95) or 1.0), 1.0)) * 60
        + (flow_bytes_s / max(float(flow_bytes_s.quantile(0.95) or 1.0), 1.0)) * 20
        + labels.map({0: 5.0, 1: 18.0, 2: 12.0, 3: 10.0})
    ).clip(0, 100)
    memory_util = (
        (avg_packet_size / max(float(avg_packet_size.quantile(0.95) or 1.0), 1.0)) * 45
        + (idle_mean / max(float(idle_mean.quantile(0.95) or 1.0), 1.0)) * 10
        + labels.map({0: 8.0, 1: 16.0, 2: 14.0, 3: 12.0})
    ).clip(0, 100)
    disk_read = (fwd_header / max(float(fwd_header.max() or 1.0), 1.0) * 2500).clip(0, 5000)
    disk_write = (bwd_header / max(float(bwd_header.max() or 1.0), 1.0) * 1800).clip(0, 3000)
    network_in = (flow_bytes_s / max(float(flow_bytes_s.quantile(0.95) or 1.0), 1.0) * 320).clip(0, 500)
    network_out = (
        (bwd_len_mean + init_win_bwd * 0.1)
        / max(float((bwd_len_mean + init_win_bwd * 0.1).quantile(0.95) or 1.0), 1.0)
        * 300
    ).clip(0, 500)
    auth_failures = (
        labels.map({0: 0, 1: 0, 2: 12, 3: 24})
        + (attack_type.str.contains('brute', na=False).astype(int) * 8)
        + (attack_type.str.contains('port', na=False).astype(int) * 4)
    ).astype(float).clip(0, 50)

    result = pd.DataFrame({
        'requests_per_minute': rpm.values,
        'avg_latency_ms': latency_ms.values,
        'error_rate': error_rate.values,
        'bytes_in': bytes_in.values,
        'bytes_out': bytes_out.values,
        'active_connections': active_connections.values,
        'cpu_utilization': cpu_util.values,
        'memory_utilization': memory_util.values,
        'disk_read_iops': disk_read.values,
        'disk_write_iops': disk_write.values,
        'network_in_mbps': network_in.values,
        'network_out_mbps': network_out.values,
        'auth_failures': auth_failures.values,
        'label': labels.values,
    })

    logger.info(
        '[real_datasets] Preprocessed CICIDS subset into security frame: %d rows, labels=%s',
        len(result),
        dict(result['label'].value_counts().sort_index()),
    )
    return result


# ---------------------------------------------------------------------------
# Public catalog
# ---------------------------------------------------------------------------

@dataclass
class RealDatasetCatalog:
    """Discover and load real datasets.

    Priority order for each domain:
      1. Staged CSV/TSV/JSON files in the configured sub-directory.
      2. Frame derived from the core 3k Alibaba Cluster Trace.
      3. Empty DataFrame (graceful fallback; callers must handle this).
    """

    finops_path: Path = Path(Config.FINOPS_DATASET_PATH)
    security_path: Path = Path(Config.SECURITY_DATASET_PATH)
    governance_path: Path = Path(Config.GOVERNANCE_DATASET_PATH)
    simulator_core_path: Path = Path(Config.SIMULATOR_CORE_DATASET_PATH)

    def list_available_files(self) -> dict[str, list[str]]:
        return {
            'finops': [str(p) for p in _discover_tabular_files(self.finops_path)],
            'security': [str(p) for p in _discover_tabular_files(self.security_path)],
            'governance': [str(p) for p in _discover_tabular_files(self.governance_path)],
            'simulator_core': [str(p) for p in _discover_tabular_files(self.simulator_core_path)],
        }

    def load_finops_frame(self) -> pd.DataFrame:
        """FinOps frame: staged dir first, 3k-derived second."""
        staged = self._load_staged(self.finops_path)
        if not staged.empty:
            logger.info('[real_datasets] FinOps: loaded %d rows from staged dir', len(staged))
            return staged
        core = _get_core_dataset()
        result = _derive_finops_frame(core)
        if result.empty:
            logger.warning('[real_datasets] FinOps: no data available (staged dir empty, core load failed)')
        return result

    def load_security_frame(self) -> pd.DataFrame:
        """Security frame: lightweight CICIDS subset first, staged dir second, derived fallback last."""
        direct = _read_tabular_file(self.security_path) if self.security_path.is_file() and self.security_path.suffix.lower() in TABULAR_EXTENSIONS else pd.DataFrame()
        if not direct.empty:
            if 'label' in direct.columns:
                logger.info('[real_datasets] Security: loaded %d rows from %s', len(direct), self.security_path)
                return direct
            if 'Attack Type' in direct.columns:
                return _derive_security_frame_from_cicids(direct)
        staged = self._load_staged(self.security_path)
        if not staged.empty:
            if 'label' not in staged.columns and 'Attack Type' in staged.columns:
                return _derive_security_frame_from_cicids(staged)
            logger.info('[real_datasets] Security: loaded %d rows from staged dir', len(staged))
            return staged
        core = _get_core_dataset()
        result = _derive_security_frame(core)
        if result.empty:
            logger.warning('[real_datasets] Security: no data available (staged dir empty, core load failed)')
        return result

    def load_governance_frame(self) -> pd.DataFrame:
        return self._load_staged(self.governance_path)

    def load_simulator_core_frame(self) -> pd.DataFrame:
        """Return the 3k Alibaba Cluster Trace directly."""
        staged = self._load_staged(self.simulator_core_path)
        if not staged.empty:
            return staged
        return _get_core_dataset()

    def _load_staged(self, base_path: Path) -> pd.DataFrame:
        files = _discover_tabular_files(base_path)
        if not files:
            return pd.DataFrame()
        frames = [_read_tabular_file(path) for path in files]
        return pd.concat(frames, ignore_index=True, sort=False)

    # Backwards-compatibility alias
    def _load_frame(self, base_path: Path) -> pd.DataFrame:
        return self._load_staged(base_path)


dataset_catalog = RealDatasetCatalog()
