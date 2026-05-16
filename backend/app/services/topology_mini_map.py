"""Deterministic topology mini-map generation for the dashboard.

The dashboard consumes the returned snapshot payload directly so the frontend
does not maintain a second topology source of truth. The layout is compact,
lightweight, and intentionally graph-engine free.
"""

from __future__ import annotations

from math import ceil
from typing import Any

from app.models.resources import Database, ResourceStatus, SecurityGroup, VirtualMachine


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _health_from_metric(value: float, *, yellow: float, red: float) -> str:
    if value >= red:
        return "red"
    if value >= yellow:
        return "yellow"
    return "green"


def _status_health(status: str | None) -> str:
    if not status:
        return "green"
    normalized = str(status).lower()
    if normalized in {ResourceStatus.RUNNING.value}:
        return "green"
    if normalized in {ResourceStatus.PENDING.value, ResourceStatus.SCALING.value}:
        return "yellow"
    if normalized in {ResourceStatus.OVERLOADED.value, ResourceStatus.STOPPED.value, ResourceStatus.FAILED.value}:
        return "red"
    return "yellow"


def _parse_security_group_ids(raw_value: Any) -> list[int]:
    group_ids: list[int] = []
    if not raw_value:
        return group_ids
    for item in raw_value:
        candidate = item
        if isinstance(item, dict):
            candidate = item.get("id") or item.get("group_id")
        try:
            group_id = int(candidate)
        except (TypeError, ValueError):
            continue
        group_ids.append(group_id)
    return group_ids


def _grid_positions(count: int, *, x_start: float, x_end: float, y_start: float, y_end: float, max_cols: int = 4) -> list[tuple[float, float]]:
    if count <= 0:
        return []
    cols = max(1, min(max_cols, count))
    rows = ceil(count / cols)
    x_step = 0 if cols == 1 else (x_end - x_start) / (cols - 1)
    y_step = 0 if rows == 1 else (y_end - y_start) / (rows - 1)
    positions: list[tuple[float, float]] = []
    for index in range(count):
        row = index // cols
        col = index % cols
        positions.append((x_start + col * x_step, y_start + row * y_step))
    return positions


def build_topology_mini_map(org_id: int, snapshot: dict | None = None) -> dict:
    """Build a compact org-scoped infrastructure mini-map.

    The return value contains fixed coordinates so the frontend can render the
    map with simple SVG lines and positioned cards.
    """

    snapshot = snapshot or {}
    topology = snapshot.get("topology", {}) or {}
    workload = snapshot.get("workload", {}) or {}
    security_block = snapshot.get("security", {}) or {}
    actions = snapshot.get("actions", []) or []

    vms = (
        VirtualMachine.query
        .filter(VirtualMachine.organization_id == org_id)
        .filter(VirtualMachine.status != ResourceStatus.TERMINATED)
        .order_by(VirtualMachine.id.asc())
        .all()
    )
    databases = (
        Database.query
        .filter(Database.organization_id == org_id)
        .filter(Database.status != ResourceStatus.TERMINATED)
        .order_by(Database.id.asc())
        .all()
    )
    security_groups = (
        SecurityGroup.query
        .filter(SecurityGroup.org_id == org_id)
        .order_by(SecurityGroup.created_at.asc(), SecurityGroup.id.asc())
        .all()
    )

    vm_by_id = {vm.id: vm for vm in vms}
    sg_by_id = {group.id: group for group in security_groups}
    db_by_id = {database.id: database for database in databases}

    health_signal = float(workload.get("queue_total_ms", 0.0) or 0.0)
    p95_latency = float(workload.get("p95_latency_ms", 0.0) or 0.0)
    active_threats = int(security_block.get("active_threats", 0) or 0)
    security_score = float(security_block.get("security_score", 100) or 100)
    current_actions = actions[0] if actions else {}
    action_type = current_actions.get("type") if isinstance(current_actions, dict) else None

    scaling_direction = "steady"
    if action_type == "scale_up":
        scaling_direction = "scale_out"
    elif action_type == "scale_down":
        scaling_direction = "scale_in"
    elif float(snapshot.get("bpi", 0.0) or 0.0) > float(snapshot.get("target_bpi", 0.0) or 0.0) > 0:
        scaling_direction = "pressure"

    host_entries = topology.get("hosts", []) or []
    ordered_vm_ids: list[int] = []
    for host in host_entries:
        ordered_vm_ids.extend(int(vm_id) for vm_id in host.get("vm_ids", []) if vm_id in vm_by_id)
    remaining_vm_ids = [vm.id for vm in vms if vm.id not in ordered_vm_ids]
    ordered_vm_ids.extend(remaining_vm_ids)

    vm_positions = _grid_positions(
        len(ordered_vm_ids),
        x_start=28.0,
        x_end=58.0,
        y_start=32.0,
        y_end=70.0,
        max_cols=4,
    )
    db_positions = _grid_positions(
        len(databases),
        x_start=68.0,
        x_end=86.0,
        y_start=42.0,
        y_end=72.0,
        max_cols=3,
    )
    sg_positions = _grid_positions(
        len(security_groups),
        x_start=68.0,
        x_end=90.0,
        y_start=16.0,
        y_end=34.0,
        max_cols=3,
    )
    threat_nodes = security_block.get("latest_threats", []) or []
    threat_positions = _grid_positions(
        len(threat_nodes),
        x_start=84.0,
        x_end=95.0,
        y_start=6.0,
        y_end=24.0,
        max_cols=1,
    )

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    unhealthy_node_ids: list[str] = []
    node_lookup: dict[str, dict[str, Any]] = {}

    def add_node(node: dict[str, Any]) -> None:
        node_lookup[node["id"]] = node
        nodes.append(node)
        if node.get("health") == "red" or node.get("health") == "yellow":
            unhealthy_node_ids.append(node["id"])

    load_balancer_health = "green"
    if active_threats > 0:
        load_balancer_health = "red"
    elif health_signal >= 1500 or p95_latency >= 1200:
        load_balancer_health = "yellow"

    add_node(
        {
            "id": f"lb-{org_id}",
            "type": "load_balancer",
            "label": "Load Balancer",
            "resource_kind": "load_balancer",
            "status": "active" if vms else "idle",
            "health": load_balancer_health,
            "x": 12.0,
            "y": 18.0,
            "details": {
                "running_vms": len(vms),
                "queue_total_ms": round(health_signal, 2),
                "p95_latency_ms": round(p95_latency, 2),
            },
        }
    )

    for index, vm_id in enumerate(ordered_vm_ids):
        vm = vm_by_id[vm_id]
        x, y = vm_positions[index]
        vm_health = _status_health(vm.status.value if vm.status else None)
        cpu_health = _health_from_metric(float(vm.cpu_utilization or 0.0), yellow=70.0, red=88.0)
        if vm_health == "green":
            vm_health = cpu_health
        if vm.status and vm.status.value == ResourceStatus.OVERLOADED.value:
            vm_health = "red"
        if vm.status and vm.status.value in {ResourceStatus.PENDING.value, ResourceStatus.SCALING.value}:
            vm_health = "yellow"
        node_id = f"vm-{vm.id}"
        add_node(
            {
                "id": node_id,
                "type": "vm",
                "label": vm.name,
                "resource_kind": "vm",
                "status": vm.status.value if vm.status else "unknown",
                "health": vm_health,
                "x": _clamp(x),
                "y": _clamp(y),
                "details": {
                    "instance_id": vm.instance_id,
                    "cpu_utilization": round(float(vm.cpu_utilization or 0.0), 2),
                    "memory_utilization": round(float(vm.memory_utilization or 0.0), 2),
                    "vcpu": vm.vcpu,
                    "memory_gb": vm.memory_gb,
                    "security_groups": [group.name for group in vm.security_groups],
                },
            }
        )
        edges.append(
            {
                "id": f"edge-lb-vm-{vm.id}",
                "source": f"lb-{org_id}",
                "target": node_id,
                "kind": "dependency",
                "label": "routes",
            }
        )

    for index, database in enumerate(databases):
        x, y = db_positions[index]
        db_health = _status_health(database.status.value if database.status else None)
        db_cpu = float(database.cpu_utilization or 0.0)
        if database.status and database.status.value == ResourceStatus.RUNNING.value:
            if db_cpu >= 88.0:
                db_health = "red"
            elif db_cpu >= 65.0:
                db_health = "yellow"
        node_id = f"db-{database.id}"
        add_node(
            {
                "id": node_id,
                "type": "database",
                "label": database.name,
                "resource_kind": "database",
                "status": database.status.value if database.status else "unknown",
                "health": db_health,
                "x": _clamp(x),
                "y": _clamp(y),
                "details": {
                    "instance_id": database.instance_id,
                    "engine": database.engine,
                    "connections": database.database_connections,
                    "publicly_accessible": bool(database.publicly_accessible),
                },
            }
        )

    for index, group in enumerate(security_groups):
        x, y = sg_positions[index]
        rule_count = len(group.rules)
        vm_count = len(group.vms)
        health = "green"
        if rule_count == 0:
            health = "yellow"
        if active_threats > 0 and group.name == "default":
            health = "red"
        node_id = f"sg-{group.id}"
        add_node(
            {
                "id": node_id,
                "type": "security_group",
                "label": group.name,
                "resource_kind": "security_group",
                "status": "attached" if vm_count else "idle",
                "health": health,
                "x": _clamp(x),
                "y": _clamp(y),
                "details": {
                    "description": group.description,
                    "rule_count": rule_count,
                    "vm_count": vm_count,
                },
            }
        )

    db_default_sg_ids: dict[int, list[int]] = {}
    default_group_id = next((group.id for group in security_groups if group.name == "default"), None)
    for database in databases:
        db_default_sg_ids[database.id] = _parse_security_group_ids(database.vpc_security_groups)
        if not db_default_sg_ids[database.id] and default_group_id:
            db_default_sg_ids[database.id] = [default_group_id]

    for index, vm_id in enumerate(ordered_vm_ids):
        vm = vm_by_id[vm_id]
        group_ids = [group.id for group in vm.security_groups]
        if not group_ids and default_group_id:
            group_ids = [default_group_id]
        for group_id in group_ids:
            if group_id not in sg_by_id:
                continue
            edges.append(
                {
                    "id": f"edge-sg-vm-{group_id}-{vm.id}",
                    "source": f"sg-{group_id}",
                    "target": f"vm-{vm.id}",
                    "kind": "security",
                    "label": "protects",
                }
            )
        if databases:
            database = databases[index % len(databases)]
            edges.append(
                {
                    "id": f"edge-vm-db-{vm.id}-{database.id}",
                    "source": f"vm-{vm.id}",
                    "target": f"db-{database.id}",
                    "kind": "dependency",
                    "label": "queries",
                }
            )

    for index, database in enumerate(databases):
        group_ids = db_default_sg_ids.get(database.id, [])
        for group_id in group_ids:
            if group_id not in sg_by_id:
                continue
            edges.append(
                {
                    "id": f"edge-sg-db-{group_id}-{database.id}",
                    "source": f"sg-{group_id}",
                    "target": f"db-{database.id}",
                    "kind": "security",
                    "label": "guards",
                }
            )

    threat_targets = [node for node in nodes if node.get("health") == "red"]
    if not threat_targets:
        threat_targets = [node for node in nodes if node.get("type") in {"vm", "database"}][:2]

    active_threat_overlays: list[dict[str, Any]] = []
    for index, threat in enumerate(threat_nodes):
        x, y = threat_positions[index]
        threat_node_id = f"threat-{threat.get('id', index)}"
        affected_resources = threat.get("affected_resources") or []
        target_ids: list[str] = []
        for resource_id in affected_resources:
            candidate = str(resource_id)
            if candidate.isdigit() and int(candidate) in vm_by_id:
                target_ids.append(f"vm-{int(candidate)}")
            elif candidate.isdigit() and int(candidate) in db_by_id:
                target_ids.append(f"db-{int(candidate)}")
            else:
                vm_match = next((vm for vm in vms if vm.instance_id == candidate or vm.name == candidate), None)
                if vm_match:
                    target_ids.append(f"vm-{vm_match.id}")
        if not target_ids:
            target_ids = [node["id"] for node in threat_targets[:2]]

        add_node(
            {
                "id": threat_node_id,
                "type": "threat",
                "label": threat.get("threat_type", "threat"),
                "resource_kind": "threat",
                "status": threat.get("status", "active"),
                "health": "red",
                "x": _clamp(x),
                "y": _clamp(y),
                "details": {
                    "severity": threat.get("severity", "high"),
                    "confidence_score": threat.get("confidence_score", 0),
                    "affected_resources": affected_resources,
                },
            }
        )
        active_threat_overlays.append(
            {
                "id": threat_node_id,
                "source": threat_node_id,
                "targets": target_ids,
                "kind": "attack",
                "severity": threat.get("severity", "high"),
                "label": threat.get("threat_type", "threat"),
            }
        )
        for target_id in target_ids:
            edges.append(
                {
                    "id": f"edge-threat-{threat_node_id}-{target_id}",
                    "source": threat_node_id,
                    "target": target_id,
                    "kind": "attack",
                    "label": "attack",
                }
            )

    scaling_detail = {
        "direction": scaling_direction,
        "desired_capacity": int(snapshot.get("desired_capacity", snapshot.get("capacity", 0)) or 0),
        "running_capacity": int(snapshot.get("running_capacity", snapshot.get("running_vms", 0)) or 0),
        "bpi": round(float(snapshot.get("bpi", 0.0) or 0.0), 2),
        "target_bpi": round(float(snapshot.get("target_bpi", 0.0) or 0.0), 2),
    }

    scaling_health = "green"
    if scaling_direction == "scale_out":
        scaling_health = "yellow"
    elif scaling_direction == "pressure":
        scaling_health = "red"

    add_node(
        {
            "id": f"scale-{org_id}",
            "type": "scaling",
            "label": "Scaling",
            "resource_kind": "scaling",
            "status": scaling_direction,
            "health": scaling_health,
            "x": 50.0,
            "y": 88.0,
            "details": scaling_detail,
        }
    )

    topology_summary = {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "vm_count": len(vms),
        "database_count": len(databases),
        "security_group_count": len(security_groups),
        "active_threats": active_threats,
        "unhealthy_node_count": len(unhealthy_node_ids),
        "health": "red" if active_threats > 0 or any(node.get("health") == "red" for node in nodes) else "yellow" if any(node.get("health") == "yellow" for node in nodes) else "green",
    }

    return {
        "org_id": org_id,
        "fresh": bool(snapshot.get("snapshot_fresh", True)),
        "freshness_seconds": float(snapshot.get("snapshot_age_seconds", 0.0) or 0.0),
        "summary": topology_summary,
        "nodes": nodes,
        "edges": edges,
        "unhealthy_node_ids": unhealthy_node_ids,
        "active_threat_overlays": active_threat_overlays,
        "scaling": scaling_detail,
    }