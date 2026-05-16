"""Rule-based operational insight generation for org snapshots.

The engine is deliberately deterministic and snapshot-driven. It does not
call any ML or LLM services. Each generated insight is derived from the
current OrgSnapshot payload and deduplicated by a stable signature so the
dashboard can display lightweight, actionable guidance without noise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


@dataclass(frozen=True)
class OperationalInsight:
    """Single dashboard insight with a stable identity."""

    key: str
    category: str
    severity: str
    title: str
    message: str
    recommended_actions: tuple[str, ...]
    signal_value: float | int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "category": self.category,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "recommended_actions": list(self.recommended_actions),
            "signal_value": self.signal_value,
            "signature": self.signature,
        }

    @property
    def signature(self) -> str:
        return f"{self.key}:{self.severity}:{self.signal_value}:{self.title}"


class OperationalInsightsEngine:
    """Deterministic rule engine for dashboard operational insights."""

    CPU_WARNING = 75.0
    CPU_CRITICAL = 90.0
    QUEUE_WARNING_MS = 1000.0
    QUEUE_CRITICAL_MS = 2500.0
    BPI_WARNING_MULTIPLIER = 1.0
    BPI_CRITICAL_MULTIPLIER = 1.5
    SECURITY_WARNING = 90
    SECURITY_CRITICAL = 70
    COMPLIANCE_WARNING = 80
    COMPLIANCE_CRITICAL = 60
    BUDGET_WARNING = 80.0
    BUDGET_CRITICAL = 100.0

    def generate(self, snapshot: dict[str, Any], *, org_id: int | None = None) -> dict[str, Any]:
        """Generate a deduplicated insight feed from a single OrgSnapshot."""

        insights: list[OperationalInsight] = []
        insights.extend(self._cpu_pressure(snapshot))
        insights.extend(self._scaling_pressure(snapshot))
        insights.extend(self._topology_pressure(snapshot))
        insights.extend(self._overspending_trends(snapshot))
        insights.extend(self._security_degradation(snapshot))
        insights.extend(self._compliance_issues(snapshot))
        insights.extend(self._queue_congestion(snapshot))

        deduped: list[OperationalInsight] = []
        seen: set[str] = set()
        for insight in sorted(insights, key=self._sort_key):
            if insight.signature in seen:
                continue
            seen.add(insight.signature)
            deduped.append(insight)

        summary = self._summary_for(deduped)
        freshness_seconds = float(snapshot.get("snapshot_age_seconds", 0.0) or 0.0)

        return {
            "org_id": org_id,
            "freshness_seconds": freshness_seconds,
            "fresh": bool(snapshot.get("snapshot_fresh", True)),
            "summary": summary,
            "insight_count": len(deduped),
            "insights": [insight.to_dict() for insight in deduped],
        }

    def _sort_key(self, insight: OperationalInsight) -> tuple[int, str, str]:
        return (-_SEVERITY_ORDER.get(insight.severity, 0), insight.category, insight.key)

    def _summary_for(self, insights: list[OperationalInsight]) -> dict[str, Any]:
        if not insights:
            return {
                "severity": "info",
                "title": "No operational risks detected",
                "message": "Current snapshot is stable.",
                "recommended_actions": ["Continue monitoring the snapshot stream."],
            }

        worst = max(insights, key=lambda item: _SEVERITY_ORDER.get(item.severity, 0))
        return {
            "severity": worst.severity,
            "title": worst.title,
            "message": worst.message,
            "recommended_actions": list(worst.recommended_actions),
        }

    def _cpu_pressure(self, snapshot: dict[str, Any]) -> list[OperationalInsight]:
        cpu_avg = float(snapshot.get("cpu_avg", 0.0) or 0.0)
        utilization_trend = snapshot.get("utilization_trend", []) or []
        cpu_points = [float(point.get("cpu_avg", point.get("cpu", 0.0)) or 0.0) for point in utilization_trend[-3:]]
        increasing = len(cpu_points) >= 3 and cpu_points[-1] > cpu_points[-2] > cpu_points[-3]

        if cpu_avg < self.CPU_WARNING and not increasing:
            return []

        severity = "critical" if cpu_avg >= self.CPU_CRITICAL else "warning"
        if increasing and severity == "warning" and cpu_avg >= self.CPU_WARNING:
            severity = "warning"

        title = "CPU pressure increasing" if increasing else "High CPU pressure"
        message = (
            f"CPU average is {cpu_avg:.1f}%, and the recent trend is increasing."
            if increasing
            else f"CPU average is {cpu_avg:.1f}% and above the operating threshold."
        )
        actions = [
            "Review the busiest VM tier for saturation.",
            "Increase capacity if queue depth is also rising.",
        ]
        return [OperationalInsight(
            key="cpu_pressure",
            category="performance",
            severity=severity,
            title=title,
            message=message,
            recommended_actions=tuple(actions),
            signal_value=round(cpu_avg, 2),
        )]

    def _scaling_pressure(self, snapshot: dict[str, Any]) -> list[OperationalInsight]:
        bpi = float(snapshot.get("bpi", 0.0) or 0.0)
        target = float(snapshot.get("target_bpi", 0.0) or 0.0)
        queue_total_ms = float(snapshot.get("workload", {}).get("queue_total_ms", 0.0) or 0.0)
        running_capacity = int(snapshot.get("running_capacity", 0) or 0)

        if target <= 0 or bpi <= target * self.BPI_WARNING_MULTIPLIER:
            return []

        severity = "critical" if bpi >= target * self.BPI_CRITICAL_MULTIPLIER or queue_total_ms >= self.QUEUE_CRITICAL_MS else "warning"
        message = (
            f"Backlog per instance is {bpi:.1f}, above target {target:.1f}, with {running_capacity} running instances."
        )
        actions = [
            "Scale out the workload until BPI returns below target.",
            "Confirm the queue is draining after the next control-plane tick.",
        ]
        return [OperationalInsight(
            key="scaling_pressure",
            category="scaling",
            severity=severity,
            title="Scaling pressure building",
            message=message,
            recommended_actions=tuple(actions),
            signal_value=round(bpi, 2),
        )]

    def _topology_pressure(self, snapshot: dict[str, Any]) -> list[OperationalInsight]:
        topology = snapshot.get("topology", {}) or {}
        hosts = topology.get("hosts", []) or []
        if not hosts:
            return []

        host_cpu_values = [float(host.get("cpu_avg", 0.0) or 0.0) for host in hosts]
        max_cpu = max(host_cpu_values) if host_cpu_values else 0.0
        min_cpu = min(host_cpu_values) if host_cpu_values else 0.0
        imbalance = max_cpu - min_cpu
        overloaded_hosts = sum(1 for value in host_cpu_values if value >= 85.0)

        if overloaded_hosts == 0 and imbalance < 35.0:
            return []

        severity = "critical" if overloaded_hosts >= 2 or max_cpu >= 95.0 else "warning"
        message = (
            f"Topology is imbalanced: {overloaded_hosts} host(s) are overloaded and CPU spread is {imbalance:.1f} points."
        )
        actions = [
            "Rebalance VMs across hosts to reduce hotspot pressure.",
            "Add capacity if the hot host is expected to stay busy.",
        ]
        return [OperationalInsight(
            key="unhealthy_topology",
            category="topology",
            severity=severity,
            title="Unhealthy topology detected",
            message=message,
            recommended_actions=tuple(actions),
            signal_value=round(max_cpu, 2),
        )]

    def _overspending_trends(self, snapshot: dict[str, Any]) -> list[OperationalInsight]:
        costs = snapshot.get("costs", {}) or {}
        budgets = costs.get("budgets", []) or []
        current_spend = float(costs.get("current_month_spend", 0.0) or 0.0)
        monthly_spend = float(costs.get("monthly_spend", current_spend) or current_spend)
        cost_trend = snapshot.get("cost_trend", []) or []
        trend_values = [float(point.get("cost", 0.0) or 0.0) for point in cost_trend[-3:]]
        rising = len(trend_values) >= 3 and trend_values[-1] >= trend_values[-2] >= trend_values[-3]

        if not budgets and not rising:
            return []

        budget_amount = max((float(budget.get("amount", 0.0) or 0.0) for budget in budgets), default=0.0)
        percentage_used = max((float(budget.get("percentage_used", 0.0) or 0.0) for budget in budgets), default=0.0)
        if budget_amount <= 0 and not rising:
            return []

        severity = "critical" if percentage_used >= self.BUDGET_CRITICAL or (budget_amount > 0 and current_spend >= budget_amount) else "warning"
        if rising and severity != "critical":
            severity = "warning"

        projected = float(costs.get("projected_month_end", monthly_spend) or monthly_spend)
        message = (
            f"Current spend is ${current_spend:.2f} and projected month-end spend is ${projected:.2f}."
        )
        actions = [
            "Review the most expensive resources for idle spend.",
            "Right-size or stop resources that are not serving active demand.",
        ]
        return [OperationalInsight(
            key="overspending_trend",
            category="cost",
            severity=severity,
            title="Overspending trend detected",
            message=message,
            recommended_actions=tuple(actions),
            signal_value=round(projected, 2),
        )]

    def _security_degradation(self, snapshot: dict[str, Any]) -> list[OperationalInsight]:
        security = snapshot.get("security", {}) or {}
        active_threats = int(security.get("active_threats", 0) or 0)
        security_score = float(security.get("security_score", snapshot.get("security_score", 100)) or 100)

        if active_threats <= 0 and security_score >= self.SECURITY_WARNING:
            return []

        severity = "critical" if security_score < self.SECURITY_CRITICAL or active_threats >= 2 else "warning"
        message = f"Security score is {security_score:.0f}/100 with {active_threats} active threat(s)."
        actions = [
            "Investigate active threats and confirm they are contained.",
            "Tighten security groups and review exposed resources.",
        ]
        return [OperationalInsight(
            key="security_degradation",
            category="security",
            severity=severity,
            title="Security degradation detected",
            message=message,
            recommended_actions=tuple(actions),
            signal_value=round(security_score, 2),
        )]

    def _compliance_issues(self, snapshot: dict[str, Any]) -> list[OperationalInsight]:
        governance = snapshot.get("governance", {}) or {}
        compliance_score = float(governance.get("compliance_score", snapshot.get("compliance_score", 100)) or 100)

        if compliance_score >= self.COMPLIANCE_WARNING:
            return []

        severity = "critical" if compliance_score < self.COMPLIANCE_CRITICAL else "warning"
        message = f"Compliance score is {compliance_score:.0f}/100 and below the expected threshold."
        actions = [
            "Review failed policy checks in the governance panel.",
            "Correct the resource configuration that is violating policy.",
        ]
        return [OperationalInsight(
            key="compliance_issue",
            category="governance",
            severity=severity,
            title="Compliance issue detected",
            message=message,
            recommended_actions=tuple(actions),
            signal_value=round(compliance_score, 2),
        )]

    def _queue_congestion(self, snapshot: dict[str, Any]) -> list[OperationalInsight]:
        workload = snapshot.get("workload", {}) or {}
        queue_total_ms = float(workload.get("queue_total_ms", 0.0) or 0.0)
        p95_latency_ms = float(workload.get("p95_latency_ms", 0.0) or 0.0)

        if queue_total_ms < self.QUEUE_WARNING_MS and p95_latency_ms < self.QUEUE_WARNING_MS:
            return []

        severity = "critical" if queue_total_ms >= self.QUEUE_CRITICAL_MS or p95_latency_ms >= self.QUEUE_CRITICAL_MS else "warning"
        message = f"Queue depth is {queue_total_ms:.0f}ms and p95 latency is {p95_latency_ms:.0f}ms."
        actions = [
            "Scale out the hot tier to drain the queue.",
            "Reduce incoming burst size if the load is controllable.",
        ]
        return [OperationalInsight(
            key="queue_congestion",
            category="workload",
            severity=severity,
            title="Queue congestion detected",
            message=message,
            recommended_actions=tuple(actions),
            signal_value=round(queue_total_ms, 2),
        )]


operational_insights_engine = OperationalInsightsEngine()