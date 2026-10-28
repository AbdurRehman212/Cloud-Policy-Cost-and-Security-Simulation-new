"""Cost forecasting and waste detection helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

try:  # Optional dependency, used when available.
    from sklearn.linear_model import LinearRegression
except Exception:  # pragma: no cover - optional dependency
    LinearRegression = None

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

    IDLE_CPU_PCT = 10.0
    UNDERUSED_CPU_PCT = 30.0
    UNDERUSED_MEMORY_PCT = 40.0
    HOURS_PER_MONTH = 730

    def detect_wastage(self, vm_data: pd.DataFrame):
        """Flag running resources with explainable utilization rules.

        IDLE:          CPU < 10%                    -> stop/schedule, saves 100% of monthly cost
        UNDERUTILIZED: CPU < 30% and memory < 40%   -> downsize,      saves  50% of monthly cost
        Savings are estimates (hourly rate x 730h x saving fraction). Resources that are
        not running are never flagged.
        """
        if vm_data is None or vm_data.empty:
            return []

        recommendations = []
        for _, row in vm_data.iterrows():
            if str(row.get('status', 'running')).lower() != 'running':
                continue
            cpu = float(row.get('cpu_utilization_avg') or 0.0)
            memory = float(row.get('memory_utilization_avg') or 0.0)
            monthly_cost = float(row.get('hourly_rate') or 0.0) * self.HOURS_PER_MONTH

            if cpu < self.IDLE_CPU_PCT:
                rule, fraction = 'IDLE', 1.0
                recommendation = 'Stop or schedule shutdown of this idle resource'
                reason = f'CPU {cpu:.1f}% is below the idle threshold of {self.IDLE_CPU_PCT:.0f}%'
            elif cpu < self.UNDERUSED_CPU_PCT and memory < self.UNDERUSED_MEMORY_PCT:
                rule, fraction = 'UNDERUTILIZED', 0.5
                recommendation = 'Consider downsizing to a smaller instance type'
                reason = (
                    f'CPU {cpu:.1f}% < {self.UNDERUSED_CPU_PCT:.0f}% and memory {memory:.1f}% '
                    f'< {self.UNDERUSED_MEMORY_PCT:.0f}%'
                )
            else:
                continue

            recommendations.append({
                'instance_id': row.get('instance_id'),
                'resource_kind': row.get('resource_kind'),
                'instance_type': row.get('instance_type'),
                'rule': rule,
                'recommendation': recommendation,
                'reason': reason,
                'potential_monthly_savings': round(monthly_cost * fraction, 2),
                'estimated': True,
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
