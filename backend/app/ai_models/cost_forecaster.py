"""Cost forecasting and waste detection helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

try:  # Optional dependency, used when available.
    from sklearn.cluster import KMeans
    from sklearn.linear_model import LinearRegression
    from sklearn.preprocessing import StandardScaler
except Exception:  # pragma: no cover - optional dependency
    KMeans = None
    LinearRegression = None
    StandardScaler = None

logger = logging.getLogger(__name__)


@dataclass
class CostForecaster:
    """Forecast spending and detect idle resources."""

    @staticmethod
    def load_historical_frame() -> pd.DataFrame:
        """Return a cost history frame derived from the 3k dataset.

        Used as a fallback when no CostRecord DB rows exist for an org,
        ensuring the forecaster always has enough history to fit a trend.
        """
        try:
            from app.data_sources.real_datasets import dataset_catalog
            frame = dataset_catalog.load_finops_frame()
            if not frame.empty:
                logger.info(
                    '[cost_forecaster] Using 3k-derived cost history (%d rows)',
                    len(frame),
                )
            return frame
        except Exception as exc:
            logger.warning('[cost_forecaster] Could not load historical frame: %s', exc)
            return pd.DataFrame()

    def forecast(self, df: pd.DataFrame, days_ahead: int = 30):
        """Forecast future costs using a trend model with optional sklearn support."""
        if df is None or df.empty:
            df = self.load_historical_frame()
        if df is None or df.empty:
            logger.warning('[cost_forecaster] No cost data available — returning flat fallback forecast')
            return self._fallback_forecast(days_ahead, base_cost=0.0)
        logger.info('[cost_forecaster] Forecasting %d days from %d historical rows', days_ahead, len(df))

        frame = df.copy()
        frame['date'] = pd.to_datetime(frame['date'])
        daily = frame.groupby(frame['date'].dt.date, as_index=False)['total_cost'].sum()
        daily['day_index'] = np.arange(len(daily))

        if len(daily) < 2:
            return self._fallback_forecast(days_ahead, base_cost=float(daily['total_cost'].mean()))

        x = daily[['day_index']].astype(float)
        y = daily['total_cost'].astype(float)

        if LinearRegression is not None:
            model = LinearRegression()
            model.fit(x, y)
            future_index = np.arange(len(daily), len(daily) + days_ahead).reshape(-1, 1)
            predictions = model.predict(future_index)
            fitted = model.predict(x)
        else:
            slope, intercept = np.polyfit(daily['day_index'], y, 1)
            future_index = np.arange(len(daily), len(daily) + days_ahead)
            predictions = slope * future_index + intercept
            fitted = slope * daily['day_index'] + intercept

        residuals = y.to_numpy() - np.asarray(fitted)
        residual_std = float(np.std(residuals)) if len(residuals) > 1 else max(float(y.mean()) * 0.1, 1.0)
        start_date = daily['date'].iloc[-1] if 'date' in daily else datetime.utcnow().date()

        forecast = []
        for offset, predicted in enumerate(predictions, start=1):
            predicted = float(max(0, predicted))
            forecast.append({
                'date': (pd.Timestamp(start_date) + timedelta(days=offset)).date().isoformat(),
                'predicted_cost': round(predicted, 2),
                'confidence_lower': round(max(0, predicted - residual_std * 1.5), 2),
                'confidence_upper': round(predicted + residual_std * 1.5, 2),
            })
        return forecast

    def detect_wastage(self, vm_data: pd.DataFrame):
        """Cluster simulated resources and identify wasteful idle instances."""
        if vm_data is None or vm_data.empty:
            return []

        frame = vm_data.copy()
        numeric_columns = ['cpu_utilization_avg', 'memory_utilization_avg', 'hourly_rate']
        for column in numeric_columns:
            if column not in frame.columns:
                frame[column] = 0.0
        features = frame[numeric_columns].fillna(0.0).astype(float)

        if KMeans is None or len(frame) < 2:
            return self._rule_based_wastage(frame)

        cluster_count = min(3, len(frame))
        scaler = StandardScaler() if StandardScaler is not None else None
        scaled = scaler.fit_transform(features) if scaler is not None else features.to_numpy()
        model = KMeans(n_clusters=cluster_count, random_state=42, n_init=10)
        labels = model.fit_predict(scaled)
        frame['cluster'] = labels

        cluster_quality = (
            frame.groupby('cluster')[['cpu_utilization_avg', 'memory_utilization_avg']]
            .mean()
            .sum(axis=1)
        )
        idle_cluster = cluster_quality.idxmin()

        recommendations = []
        for _, row in frame[frame['cluster'] == idle_cluster].iterrows():
            cpu = float(row['cpu_utilization_avg'])
            memory = float(row['memory_utilization_avg'])
            hourly_rate = float(row['hourly_rate'])
            monthly_savings = round(hourly_rate * 730 * 0.25, 2)
            if cpu < 30 or memory < 35:
                recommendations.append({
                    'instance_id': row.get('instance_id'),
                    'recommendation': 'Consider downsizing or scheduling shutdowns',
                    'potential_monthly_savings': monthly_savings,
                    'cluster': int(idle_cluster),
                    'reason': f'Low utilization detected (CPU {cpu:.1f}%, Memory {memory:.1f}%)',
                })
        return recommendations

    def _rule_based_wastage(self, frame: pd.DataFrame):
        recommendations = []
        for _, row in frame.iterrows():
            cpu = float(row.get('cpu_utilization_avg', 0))
            memory = float(row.get('memory_utilization_avg', 0))
            hourly_rate = float(row.get('hourly_rate', 0))
            if cpu < 25 or memory < 30:
                recommendations.append({
                    'instance_id': row.get('instance_id'),
                    'recommendation': 'Consider downsizing or scheduling shutdowns',
                    'potential_monthly_savings': round(hourly_rate * 730 * 0.25, 2),
                    'reason': f'Low utilization detected (CPU {cpu:.1f}%, Memory {memory:.1f}%)',
                })
        return recommendations

    def _fallback_forecast(self, days_ahead: int, base_cost: float):
        start_date = datetime.utcnow().date()
        return [{
            'date': (start_date + timedelta(days=offset)).isoformat(),
            'predicted_cost': round(base_cost, 2),
            'confidence_lower': round(base_cost * 0.9, 2),
            'confidence_upper': round(base_cost * 1.1, 2),
        } for offset in range(1, days_ahead + 1)]


cost_forecaster = CostForecaster()
