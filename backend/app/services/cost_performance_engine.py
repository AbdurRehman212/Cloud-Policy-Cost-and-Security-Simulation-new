"""Deterministic cost and performance optimization logic.

The engine is snapshot-driven and org-scoped. It reads live resource state
from the database, correlates utilization with spend, and emits optimization
recommendations without relying on any AI or external billing integration.
"""

from __future__ import annotations

import math
from statistics import median
from typing import Any

from app.config import Config
from app.models.resources import Database, ResourceStatus, VirtualMachine


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _composite_utilization(cpu: float, memory: float) -> float:
    return _clamp((cpu * 0.65) + (memory * 0.35))


def _pearson_correlation(values_a: list[float], values_b: list[float]) -> float:
    if len(values_a) < 2 or len(values_b) < 2 or len(values_a) != len(values_b):
        return 0.0

    mean_a = sum(values_a) / len(values_a)
    mean_b = sum(values_b) / len(values_b)
    numerator = sum((a - mean_a) * (b - mean_b) for a, b in zip(values_a, values_b))
    denominator_a = math.sqrt(sum((a - mean_a) ** 2 for a in values_a))
    denominator_b = math.sqrt(sum((b - mean_b) ** 2 for b in values_b))
    denominator = denominator_a * denominator_b
    if denominator == 0:
        return 0.0
    return max(-1.0, min(1.0, numerator / denominator))


def _pricing_table(resource_kind: str) -> list[tuple[str, float]]:
    if resource_kind == "vm":
        return sorted(Config.VM_PRICING.items(), key=lambda item: item[1])
    return sorted(Config.DB_PRICING.items(), key=lambda item: item[1])


def _suggest_cheaper_tier(resource_kind: str, current_type: str, current_rate: float) -> dict[str, Any] | None:
    pricing = _pricing_table(resource_kind)
    cheaper = [item for item in pricing if item[1] < current_rate]
    if not cheaper:
        return None

    suggested_type, suggested_rate = cheaper[-1]
    savings_pct = round(((current_rate - suggested_rate) / current_rate) * 100, 1) if current_rate > 0 else 0.0
    if savings_pct <= 0:
        return None

    return {
        "suggested_type": suggested_type,
        "suggested_rate": round(suggested_rate, 4),
        "savings_pct": savings_pct,
        "savings_rate_delta": round(current_rate - suggested_rate, 4),
        "current_type": current_type,
    }


def _resource_efficiency(utilization_pct: float, hourly_rate: float, avg_hourly_rate: float) -> float:
    rate_ratio = hourly_rate / avg_hourly_rate if avg_hourly_rate > 0 else 1.0
    penalty = max(0.5, rate_ratio)
    return _clamp(utilization_pct * (1.15 / penalty))


def _monthly_savings(rate_delta: float) -> float:
    return round(rate_delta * 24 * 30, 2)


def analyze_cost_performance(org_id: int, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate efficiency metrics and optimization recommendations."""

    snapshot = snapshot or {}

    vms = (
        VirtualMachine.query
        .filter(VirtualMachine.organization_id == org_id)
        .filter(VirtualMachine.status != ResourceStatus.TERMINATED)
        .all()
    )
    databases = (
        Database.query
        .filter(Database.organization_id == org_id)
        .filter(Database.status != ResourceStatus.TERMINATED)
        .all()
    )

    resources: list[dict[str, Any]] = []
    for vm in vms:
        cpu = float(vm.cpu_utilization or 0.0)
        memory = float(vm.memory_utilization or 0.0)
        utilization = _composite_utilization(cpu, memory)
        current_cost = float(vm.calculate_current_cost() or 0.0)
        resources.append(
            {
                "kind": "vm",
                "id": vm.id,
                "name": vm.name,
                "resource_kind": "vm",
                "type": vm.instance_type,
                "status": vm.status.value if vm.status else None,
                "cpu_utilization": round(cpu, 2),
                "memory_utilization": round(memory, 2),
                "utilization_pct": round(utilization, 2),
                "hourly_rate": round(float(vm.hourly_rate or 0.0), 4),
                "current_cost": round(current_cost, 4),
            }
        )

    for database in databases:
        cpu = float(database.cpu_utilization or 0.0)
        memory = min(100.0, max(0.0, cpu * 1.35 + float(database.database_connections or 0) * 0.65))
        utilization = _composite_utilization(cpu, memory)
        current_cost = float(database.total_runtime_hours or 0.0) * float(database.hourly_rate or 0.0)
        resources.append(
            {
                "kind": "database",
                "id": database.id,
                "name": database.name,
                "resource_kind": "database",
                "type": database.instance_class,
                "status": database.status.value if database.status else None,
                "cpu_utilization": round(cpu, 2),
                "memory_utilization": round(memory, 2),
                "utilization_pct": round(utilization, 2),
                "hourly_rate": round(float(database.hourly_rate or 0.0), 4),
                "current_cost": round(current_cost, 4),
            }
        )

    if not resources:
        return {
            "org_id": org_id,
            "fresh": bool(snapshot.get("snapshot_fresh", True)),
            "freshness_seconds": float(snapshot.get("snapshot_age_seconds", 0.0) or 0.0),
            "summary": {
                "efficiency_score": 100.0,
                "cost_pressure_score": 0.0,
                "underutilized_count": 0,
                "overspending_count": 0,
                "utilization_cost_correlation": 0.0,
                "potential_monthly_savings": 0.0,
                "potential_monthly_savings_pct": 0.0,
                "top_recommendation": "No running resources detected.",
            },
            "underutilized_resources": [],
            "overspending_resources": [],
            "recommendations": [],
            "trend": [],
        }

    average_hourly_rate = sum(item["hourly_rate"] for item in resources) / len(resources)
    total_hourly_cost = sum(item["hourly_rate"] for item in resources)
    total_utilization = sum(item["utilization_pct"] for item in resources)
    average_utilization = total_utilization / len(resources)

    scored_resources: list[dict[str, Any]] = []
    underutilized_resources: list[dict[str, Any]] = []
    overspending_resources: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    potential_monthly_savings = 0.0

    for resource in resources:
        efficiency = _resource_efficiency(resource["utilization_pct"], resource["hourly_rate"], average_hourly_rate)
        resource["efficiency_score"] = round(efficiency, 2)
        resource["waste_score"] = round(max(0.0, 100.0 - efficiency), 2)
        scored_resources.append(resource)

        is_running = resource.get("status") == ResourceStatus.RUNNING.value
        is_underutilized = is_running and resource["kind"] == "vm" and resource["utilization_pct"] <= 20.0
        is_overspending = is_running and resource["hourly_rate"] >= average_hourly_rate and resource["utilization_pct"] <= 40.0

        if is_underutilized:
            suggestion = _suggest_cheaper_tier(resource["kind"], resource["type"], resource["hourly_rate"])
            savings_monthly = 0.0
            if suggestion:
                savings_monthly = _monthly_savings(suggestion["savings_rate_delta"])
                potential_monthly_savings += savings_monthly
            record = {
                **resource,
                "suggestion": suggestion,
                "estimated_monthly_savings": savings_monthly,
            }
            underutilized_resources.append(record)
            if suggestion:
                recommendations.append(
                    {
                        "resource_id": resource["id"],
                        "resource_name": resource["name"],
                        "resource_kind": resource["kind"],
                        "title": f"Downsize {resource['name']}",
                        "message": (
                            f"{resource['name']} utilization is {resource['utilization_pct']:.0f}%. "
                            f"Downsizing to {suggestion['suggested_type']} could save {suggestion['savings_pct']:.0f}% monthly."
                        ),
                        "action": "rightsize",
                        "savings_pct": suggestion["savings_pct"],
                        "estimated_monthly_savings": savings_monthly,
                        "target_type": suggestion["suggested_type"],
                    }
                )

        if is_overspending:
            overspending_resources.append(resource)
            recommendations.append(
                {
                    "resource_id": resource["id"],
                    "resource_name": resource["name"],
                    "resource_kind": resource["kind"],
                    "title": f"Review {resource['name']}",
                    "message": (
                        f"{resource['name']} is costing ${resource['hourly_rate']:.4f}/hr while using only "
                        f"{resource['utilization_pct']:.0f}% of its capacity."
                    ),
                    "action": "review",
                    "savings_pct": None,
                    "estimated_monthly_savings": 0.0,
                    "target_type": resource["type"],
                }
            )

    resource_count = len(scored_resources)
    weighted_efficiency = sum(item["efficiency_score"] * max(item["hourly_rate"], 0.01) for item in scored_resources)
    weighted_efficiency /= max(total_hourly_cost, 0.01)
    cost_pressure_score = _clamp((average_hourly_rate / max(average_utilization, 1.0)) * 20.0)
    efficiency_score = _clamp(weighted_efficiency)

    utilization_values = [item["utilization_pct"] for item in scored_resources]
    cost_values = [item["hourly_rate"] for item in scored_resources]
    utilization_cost_correlation = round(_pearson_correlation(utilization_values, cost_values), 3)

    if not recommendations:
        recommendations.append(
            {
                "resource_id": None,
                "resource_name": None,
                "resource_kind": "org",
                "title": "Keep current mix",
                "message": "Utilization and spend are aligned well enough that no immediate resize recommendation is active.",
                "action": "monitor",
                "savings_pct": 0.0,
                "estimated_monthly_savings": 0.0,
                "target_type": None,
            }
        )

    if recommendations:
        top_recommendation = recommendations[0]["message"]
    else:
        top_recommendation = "No optimization recommendations available."

    cost_trend = snapshot.get("cost_trend", []) or []
    utilization_trend = snapshot.get("utilization_trend", []) or []
    trend: list[dict[str, Any]] = []
    aligned_count = min(len(cost_trend), len(utilization_trend))
    for cost_point, utilization_point in zip(cost_trend[-aligned_count:], utilization_trend[-aligned_count:]):
        cost_value = float(cost_point.get("cost", 0.0) or 0.0)
        utilization_value = _clamp(
            (float(utilization_point.get("cpu_avg", 0.0) or 0.0) * 0.65)
            + (float(utilization_point.get("memory_avg", 0.0) or 0.0) * 0.35)
        )
        cost_pressure = _clamp((cost_value / max(total_hourly_cost, 0.01)) * 100.0)
        efficiency = _clamp(100.0 - (cost_pressure * 0.55) - ((100.0 - utilization_value) * 0.45))
        trend.append(
            {
                "time": cost_point.get("name") or utilization_point.get("timestamp") or cost_point.get("timestamp"),
                "cost": round(cost_value, 4),
                "utilization": round(utilization_value, 2),
                "efficiency": round(efficiency, 2),
            }
        )

    return {
        "org_id": org_id,
        "fresh": bool(snapshot.get("snapshot_fresh", True)),
        "freshness_seconds": float(snapshot.get("snapshot_age_seconds", 0.0) or 0.0),
        "summary": {
            "efficiency_score": round(efficiency_score, 2),
            "cost_pressure_score": round(cost_pressure_score, 2),
            "underutilized_count": len(underutilized_resources),
            "overspending_count": len(overspending_resources),
            "resource_count": resource_count,
            "utilization_cost_correlation": utilization_cost_correlation,
            "average_utilization": round(average_utilization, 2),
            "average_hourly_rate": round(average_hourly_rate, 4),
            "current_hourly_cost": round(total_hourly_cost, 4),
            "potential_monthly_savings": round(potential_monthly_savings, 2),
            "potential_monthly_savings_pct": round((potential_monthly_savings / max(total_hourly_cost * 24 * 30, 0.01)) * 100.0, 2),
            "top_recommendation": top_recommendation,
        },
        "underutilized_resources": underutilized_resources,
        "overspending_resources": overspending_resources,
        "recommendations": recommendations,
        "trend": trend,
        "resources": scored_resources,
    }
