"""Threat detector for the simulator using a lightweight real-dataset model."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from app.data_sources.real_datasets import dataset_catalog

logger = logging.getLogger(__name__)

try:  # Lightweight, Chromebook-friendly classifier.
    from sklearn.ensemble import RandomForestClassifier
except Exception:  # pragma: no cover - optional dependency
    RandomForestClassifier = None


THREAT_LABELS = {
    0: 'normal',
    1: 'ddos',
    2: 'port_scan',
    3: 'brute_force',
}


class _CentroidClassifier:
    """Tiny nearest-centroid classifier for environments without sklearn."""

    def fit(self, X, y):
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=int)
        self.classes_ = np.unique(y)
        self.centroids_ = {}
        self.spreads_ = {}
        for label in self.classes_:
            class_rows = X[y == label]
            centroid = class_rows.mean(axis=0) if len(class_rows) else np.zeros(X.shape[1], dtype=float)
            spread = class_rows.std(axis=0) if len(class_rows) else np.ones(X.shape[1], dtype=float)
            self.centroids_[int(label)] = centroid
            self.spreads_[int(label)] = np.where(np.isfinite(spread) & (spread > 1e-6), spread, 1.0)
        return self

    def predict_proba(self, X):
        X = np.asarray(X, dtype=float)
        scores = []
        ordered_labels = [int(label) for label in self.classes_]
        for row in X:
            row_scores = []
            for label in ordered_labels:
                centroid = self.centroids_[label]
                spread = self.spreads_[label]
                distance = np.sqrt(np.mean(((row - centroid) / spread) ** 2))
                row_scores.append(-distance)
            row_scores = np.asarray(row_scores, dtype=float)
            row_scores = row_scores - np.max(row_scores)
            exp_scores = np.exp(row_scores)
            probs = exp_scores / max(float(exp_scores.sum()), 1e-12)
            scores.append(probs)
        return np.asarray(scores, dtype=float)


@dataclass
class ThreatDetector:
    """Train a small RandomForest classifier on a staged real dataset when available."""

    def __post_init__(self):
        self.model = None
        self.backend = 'heuristic'
        self.feature_columns = [
            'requests_per_minute',
            'avg_latency_ms',
            'error_rate',
            'bytes_in',
            'bytes_out',
            'active_connections',
            'cpu_utilization',
            'memory_utilization',
            'disk_read_iops',
            'disk_write_iops',
            'network_in_mbps',
            'network_out_mbps',
            'auth_failures',
        ]
        self._train_if_possible()

    def _training_frame(self) -> pd.DataFrame:
        frame = dataset_catalog.load_security_frame()
        if frame.empty or 'label' not in frame.columns:
            return pd.DataFrame()
        for column in self.feature_columns:
            if column not in frame.columns:
                frame[column] = 0.0
        return frame

    def train_from_frame(self, frame: pd.DataFrame):
        """Train from a real staged dataset frame."""
        if frame is None or frame.empty or 'label' not in frame.columns:
            return False
        for column in self.feature_columns:
            if column not in frame.columns:
                frame[column] = 0.0
        if len(frame) < 20:
            return False

        X = frame[self.feature_columns].fillna(0.0).astype(float)
        y = frame['label'].astype(int)

        if RandomForestClassifier is not None:
            self.backend = 'sklearn'
            self.model = RandomForestClassifier(
                n_estimators=64,
                max_depth=8,
                min_samples_leaf=2,
                class_weight='balanced_subsample',
                random_state=42,
                n_jobs=1,
            )
            self.model.fit(X, y)
            logger.info(
                '[threat_detector] Trained RandomForest on %d rows (13 features, 4 classes)',
                len(frame),
            )
            return True

        self.backend = 'centroid'
        self.model = _CentroidClassifier().fit(X.to_numpy(), y.to_numpy())
        logger.info(
            '[threat_detector] Trained centroid classifier on %d rows (13 features, 4 classes)',
            len(frame),
        )
        return True

    def _train_if_possible(self):
        frame = self._training_frame()
        if frame.empty:
            self.backend = 'heuristic'
            logger.warning(
                '[threat_detector] No training data available — running in heuristic mode'
            )
            return
        logger.info(
            '[threat_detector] Training on %d rows (label dist: %s)',
            len(frame),
            dict(frame['label'].value_counts().sort_index()),
        )
        self.train_from_frame(frame)

    def _feature_frame(self, metrics):
        row = {column: float(metrics.get(column, 0) or 0) for column in self.feature_columns}
        return pd.DataFrame([row])

    def real_time_monitor(self, metrics):
        """Return the threat verdict for a single metrics snapshot."""
        snapshot = metrics or {}
        frame = self._feature_frame(snapshot)

        if self.backend in {'sklearn', 'centroid'} and self.model is not None:
            probabilities = self.model.predict_proba(frame)[0]
            label = int(probabilities.argmax())
            confidence = float(probabilities[label])
            return self._format_result(label, confidence, snapshot)

        return self._heuristic_monitor(snapshot)

    def analyze_traffic_logs(self, traffic_frame: pd.DataFrame):
        """Analyze a dataframe of traffic logs and return a summary."""
        if traffic_frame is None or traffic_frame.empty:
            return {'total': 0, 'threats': 0, 'results': []}
        results = [self.real_time_monitor(row.to_dict()) for _, row in traffic_frame.iterrows()]
        return {
            'total': len(results),
            'threats': len([r for r in results if r.get('is_threat')]),
            'results': results,
        }

    def _heuristic_monitor(self, metrics):
        requests_per_minute = float(metrics.get('requests_per_minute', 0) or 0)
        error_rate = float(metrics.get('error_rate', 0) or 0)
        avg_latency_ms = float(metrics.get('avg_latency_ms', 0) or 0)
        auth_failures = float(metrics.get('auth_failures', 0) or 0)
        network_in = float(metrics.get('network_in_mbps', 0) or 0)
        network_out = float(metrics.get('network_out_mbps', 0) or 0)
        cpu = float(metrics.get('cpu_utilization', 0) or 0)

        if requests_per_minute > 5000 or network_in > 250 or network_out > 250:
            return self._format_result(1, 0.92, metrics)
        if requests_per_minute > 1600 and network_in > 80 and error_rate < 0.08:
            return self._format_result(2, 0.87, metrics)
        if auth_failures > 20 or (requests_per_minute < 1500 and error_rate > 0.08):
            return self._format_result(3, 0.88, metrics)
        if avg_latency_ms > 300 or error_rate > 0.15 or cpu > 90:
            return self._format_result(1, 0.79, metrics)
        return self._format_result(0, 0.96, metrics)

    def _format_result(self, label, confidence, metrics):
        threat_type = THREAT_LABELS.get(label, 'normal')
        is_threat = threat_type != 'normal'
        return {
            'is_threat': is_threat,
            'threat_type': threat_type,
            'confidence': round(float(confidence), 4),
            'source': self.backend,
            'detected_at': datetime.utcnow().isoformat(),
            'prediction': threat_type,
            'signals': {
                'requests_per_minute': metrics.get('requests_per_minute'),
                'avg_latency_ms': metrics.get('avg_latency_ms'),
                'error_rate': metrics.get('error_rate'),
                'network_in_mbps': metrics.get('network_in_mbps'),
                'network_out_mbps': metrics.get('network_out_mbps'),
                'auth_failures': metrics.get('auth_failures'),
            },
        }


threat_detector = ThreatDetector()
