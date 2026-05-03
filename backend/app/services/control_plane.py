"""Control plane service for organization resource snapshots."""

import time

from app import db
from app.models.resources import VirtualMachine, Database, ResourceStatus

# In-memory storage for CPU history per organization (max 5 entries)
cpu_history: dict[int, list] = {}

# EMA smoothing parameters
alpha = 0.3
ema_cpu: dict[int, float] = {}
ema_memory: dict[int, float] = {}

# Alert state storage (CloudWatch-style state transitions)
alert_states = {}  # org_id -> { alert_type: state }

# Scaling state storage for cooldown and capacity control
scaling_state = {}  # org_id -> { last_action_time, capacity }


def get_org_snapshot(org_id: int) -> dict:
    """Get current organization resource snapshot.
    
    Queries the database once for a consistent snapshot and computes metrics.
    
    Args:
        org_id: Organization ID
        
    Returns:
        Dict with keys:
            - total_vms: Total non-terminated VMs
            - running_vms: Total running VMs
            - cpu_avg: Weighted average CPU utilization of running VMs (0-100)
            - memory_avg: Average memory utilization of running VMs (0-100)
    """
    # Single DB query for all VMs in organization
    vms = VirtualMachine.query.filter_by(
        organization_id=org_id,
    ).filter(VirtualMachine.status != 'terminated').all()
    
    # Compute total_vms from queried list
    total_vms = len(vms)
    
    # Filter running VMs in memory (separate from valid_vms for accurate counting)
    running_vms = [vm for vm in vms if vm.status == ResourceStatus.RUNNING]
    running_vms_count = len(running_vms)
    
    # Filter VMs with valid metrics for aggregation (subset of running_vms)
    valid_vms = [
        vm for vm in running_vms
        if vm.cpu_utilization is not None and vm.memory_utilization is not None
    ]
    
    # DEBUG: VM counts
    print("DEBUG running_vms:", len(running_vms))
    print("DEBUG valid_vms:", len(valid_vms))
    
    # DEBUG: Raw VM values
    for vm in running_vms[:5]:
        print("DEBUG VM CPU:", vm.cpu_utilization, "Memory:", vm.memory_utilization)
    
    # Compute metrics only from valid VMs
    if valid_vms:
        # Weight CPU by vcpu for realistic cross-instance-type averaging
        total_vcpu = sum(float(vm.vcpu or 1) for vm in valid_vms)
        if total_vcpu > 0:
            weighted_cpu_sum = sum(
                float(vm.cpu_utilization or 0) * float(vm.vcpu or 1)
                for vm in valid_vms
            )
            cpu_avg = weighted_cpu_sum / total_vcpu
        else:
            cpu_avg = 0.0
        
        # Memory computed normally (unweighted)
        memory_avg = sum(float(vm.memory_utilization or 0) for vm in valid_vms) / len(valid_vms)
        
        # Clamp values to 0-100 range
        cpu_avg = max(0.0, min(100.0, cpu_avg))
        memory_avg = max(0.0, min(100.0, memory_avg))
        
        # DEBUG: Before EMA
        print("DEBUG cpu_avg BEFORE EMA:", cpu_avg)
        print("DEBUG memory_avg BEFORE EMA:", memory_avg)
        
        # EMA smoothing for CPU
        if org_id not in ema_cpu:
            ema_cpu[org_id] = cpu_avg
        else:
            ema_cpu[org_id] = (alpha * cpu_avg) + ((1 - alpha) * ema_cpu[org_id])
        smoothed_cpu = ema_cpu[org_id]
        
        # Replace cpu_avg with smoothed for all downstream usage
        cpu_avg = smoothed_cpu
        
        # EMA smoothing for memory
        if org_id not in ema_memory:
            ema_memory[org_id] = memory_avg
        else:
            ema_memory[org_id] = (alpha * memory_avg) + ((1 - alpha) * ema_memory[org_id])
        smoothed_memory = ema_memory[org_id]
        
        # Replace memory_avg with smoothed for all downstream usage
        memory_avg = smoothed_memory
        
        # DEBUG: After EMA
        print("DEBUG cpu_avg AFTER EMA:", cpu_avg)
        print("DEBUG memory_avg AFTER EMA:", memory_avg)
        
        # Initialize bottleneck variables
        raw_max_cpu = 0
        raw_max_memory = 0
        smoothed_max_cpu = 0
        smoothed_max_memory = 0
        
        # Bottleneck detection (hybrid: raw max + smoothed average)
        raw_max_cpu = max(float(vm.cpu_utilization or 0) for vm in valid_vms)
        raw_max_memory = max(float(vm.memory_utilization or 0) for vm in valid_vms)
        
        smoothed_max_cpu = (0.7 * raw_max_cpu) + (0.3 * smoothed_cpu)
        smoothed_max_memory = (0.7 * raw_max_memory) + (0.3 * smoothed_memory)
        
        cpu_bottleneck = smoothed_max_cpu > 85
        memory_bottleneck = smoothed_max_memory > 90
        
        max_cpu = raw_max_cpu
        max_memory = raw_max_memory
        
        # System pressure assessment
        if cpu_bottleneck or memory_bottleneck:
            system_pressure = "high"
        elif smoothed_cpu > 70:
            system_pressure = "moderate"
        else:
            system_pressure = "normal"
        
        # Trend detection
        history = cpu_history.get(org_id, [])

        if len(history) < 4:
            cpu_trend = "stable"
        else:
            recent = history[-3:]
            previous = history[-4:-1]

            recent_avg = sum(recent) / len(recent)
            previous_avg = sum(previous) / len(previous)

            if recent_avg > previous_avg + 3:
                cpu_trend = "increasing"
            elif recent_avg < previous_avg - 3:
                cpu_trend = "decreasing"
            else:
                cpu_trend = "stable"
        
        # Update CPU history (keep max 5 entries) - use smoothed value
        history.append(smoothed_cpu)
        if len(history) > 5:
            history.pop(0)
        cpu_history[org_id] = history
        
        # DEBUG: History
        print("DEBUG cpu_history:", cpu_history.get(org_id))
        
        # System risk assessment
        if cpu_trend == "increasing" and smoothed_cpu > 60:
            system_risk = "rising"
        else:
            system_risk = "normal"
        
        # Alert engine with CloudWatch-style state transitions
        prev_states = alert_states.get(org_id, {}).copy()
        org_alerts = {}
        
        # Define insufficient data conditions
        cpu_insufficient = (
            total_vms == 0
            or len(cpu_history.get(org_id, [])) < 3
        )
        memory_insufficient = (
            total_vms == 0
            or len(cpu_history.get(org_id, [])) < 3
        )
        
        # CPU alert state
        if cpu_insufficient:
            cpu_state = "INSUFFICIENT_DATA"
        elif cpu_bottleneck:
            cpu_state = "ALARM"
        else:
            cpu_state = "OK"
        org_alerts["cpu"] = cpu_state
        
        # Memory alert state
        if memory_insufficient:
            memory_state = "INSUFFICIENT_DATA"
        elif memory_bottleneck:
            memory_state = "ALARM"
        else:
            memory_state = "OK"
        org_alerts["memory"] = memory_state
        
        # Trend alert state
        if cpu_trend == "stable" and len(cpu_history.get(org_id, [])) < 3:
            trend_state = "INSUFFICIENT_DATA"
        elif system_risk == "rising":
            trend_state = "ALARM"
        else:
            trend_state = "OK"
        org_alerts["trend"] = trend_state
        
        # Track state transitions
        transitions = []
        for key, new_state in org_alerts.items():
            old_state = prev_states.get(key)
            if old_state and old_state != new_state:
                transitions.append({
                    "type": key,
                    "from": old_state,
                    "to": new_state
                })
        
        # Save state
        alert_states[org_id] = org_alerts
        
        # Action engine for auto-scaling simulation with cooldown and capacity
        state = scaling_state.get(org_id, {
            "last_action_time": 0,
            "capacity": 1
        })
        
        current_time = time.time()
        cooldown = 10
        target_cpu = 60  # desired utilization %
        
        if current_time - state["last_action_time"] < cooldown:
            actions = []
        else:
            actions = []
            action_taken = False
            
            # Use evaluation window for stable CloudWatch-style decisions
            history = cpu_history.get(org_id, [])
            
            if len(history) >= 3:
                recent_window = history[-3:]
                recent_avg = sum(recent_window) / len(recent_window)
                cpu_diff = recent_avg - target_cpu
                
                # Check if CPU alert is active or recently transitioned
                cpu_alarm_active = org_alerts.get("cpu") == "ALARM"
                recent_cpu_transition = any(
                    t["type"] == "cpu" and t["to"] == "ALARM"
                    for t in transitions
                )
                
                # Sustained pressure/relief based on window average
                sustained_pressure = recent_avg > target_cpu + 10
                sustained_relief = recent_avg < target_cpu - 10
                
                # Prevent scaling when system is stable
                if not cpu_alarm_active and abs(cpu_diff) < 10:
                    actions = []
                elif (
                    cpu_alarm_active
                    or recent_cpu_transition
                    or sustained_pressure
                    or sustained_relief
                ):
                    # Step scaling: determine scale-out step based on distance from target
                    if cpu_diff > 20:
                        step = 2
                    elif cpu_diff > 10:
                        step = 1
                    else:
                        step = 0
                    
                    # Apply scale-out with step
                    if step > 0 and state["capacity"] < 10:
                        state["capacity"] = min(10, state["capacity"] + step)
                        actions.append({
                            "type": "scale_up",
                            "capacity": state["capacity"],
                            "reason": f"CPU {recent_avg:.1f}% (3-cycle avg) above target {target_cpu}% (+{step})"
                        })
                        state["last_action_time"] = current_time
                        action_taken = True
                    
                    # Scale in with stability guard (only if system is not rising)
                    elif cpu_diff < -10 and system_risk != "rising":
                        if state["capacity"] > 1:
                            state["capacity"] -= 1
                            actions.append({
                                "type": "scale_down",
                                "capacity": state["capacity"],
                                "reason": f"CPU {recent_avg:.1f}% (3-cycle avg) below target {target_cpu}%"
                            })
                            state["last_action_time"] = current_time
                            action_taken = True
            else:
                # Insufficient data for window-based decision
                actions = []
        
        scaling_state[org_id] = state
        capacity = state["capacity"]
        
        # Build learning explanation based on actions
        if actions:
            action_type = actions[0].get("type")
            if action_type == "scale_up":
                learning_insight = {
                    "title": "System scaled up",
                    "what_happened": "CPU usage increased above safe level",
                    "why_it_happened": "System detected sustained pressure",
                    "system_thinking": "More capacity is needed to handle load"
                }
            elif action_type == "scale_down":
                learning_insight = {
                    "title": "System scaled down",
                    "what_happened": "CPU usage dropped below optimal level",
                    "why_it_happened": "System detected underutilization",
                    "system_thinking": "Reducing resources to optimize efficiency"
                }
            else:
                learning_insight = {
                    "title": "System stable",
                    "what_happened": "Metrics within target range",
                    "why_it_happened": "No scaling needed",
                    "system_thinking": "System is balanced"
                }
        else:
            learning_insight = {
                "title": "System stable",
                "what_happened": "Metrics within target range",
                "why_it_happened": "No scaling needed",
                "system_thinking": "System is balanced"
            }
        
        # Build alerts with state
        alerts = []
        
        if cpu_bottleneck:
            alerts.append({
                "type": "cpu",
                "state": cpu_state,
                "level": "critical" if cpu_state == "ALARM" else "normal",
                "message": "High CPU usage detected"
            })
        
        if memory_bottleneck:
            alerts.append({
                "type": "memory",
                "state": memory_state,
                "level": "critical" if memory_state == "ALARM" else "normal",
                "message": "High memory usage detected"
            })
        
        if system_risk == "rising":
            alerts.append({
                "type": "trend",
                "state": trend_state,
                "level": "warning" if trend_state == "ALARM" else "normal",
                "message": "CPU trend increasing"
            })
        
        alert_count = len(alerts)
    elif running_vms:
        # Running VMs exist but none have valid metrics
        cpu_avg = 0.0
        memory_avg = 0.0
        max_cpu = 0.0
        max_memory = 0.0
        smoothed_max_cpu = 0.0
        smoothed_max_memory = 0.0
        cpu_bottleneck = False
        memory_bottleneck = False
        system_pressure = "normal"
        cpu_trend = "stable"
        system_risk = "normal"
        alerts = []
        alert_count = 0
        transitions = []
        actions = []
        capacity = 1
        learning_insight = {
            "title": "System stable",
            "what_happened": "No valid metrics available",
            "why_it_happened": "Running VMs lack CPU/memory data",
            "system_thinking": "Waiting for metric collection"
        }
    else:
        cpu_avg = 0.0
        memory_avg = 0.0
        max_cpu = 0.0
        max_memory = 0.0
        smoothed_max_cpu = 0.0
        smoothed_max_memory = 0.0
        cpu_bottleneck = False
        memory_bottleneck = False
        system_pressure = "normal"
        cpu_trend = "stable"
        system_risk = "normal"
        alerts = []
        alert_count = 0
        transitions = []
        actions = []
        capacity = 1
        learning_insight = {
            "title": "System stable",
            "what_happened": "No resources detected",
            "why_it_happened": "No VMs running",
            "system_thinking": "System idle"
        }
    
    # DEBUG: Final snapshot CPU
    print("FINAL SNAPSHOT CPU:", cpu_avg)
    
    return {
        'total_vms': total_vms,
        'running_vms': running_vms_count,
        'cpu_avg': round(cpu_avg, 2),
        'memory_avg': round(memory_avg, 2),
        'max_cpu': round(max_cpu, 2),
        'max_memory': round(max_memory, 2),
        'smoothed_max_cpu': round(smoothed_max_cpu, 2),
        'smoothed_max_memory': round(smoothed_max_memory, 2),
        'cpu_bottleneck': cpu_bottleneck,
        'memory_bottleneck': memory_bottleneck,
        'system_pressure': system_pressure,
        'cpu_trend': cpu_trend,
        'system_risk': system_risk,
        'alerts': alerts,
        'alert_count': alert_count,
        'alert_transitions': transitions,
        'actions': actions,
        'capacity': capacity,
        'learning_insight': learning_insight,
    }


def run_control_plane_loop():
    """Background task to emit real-time dashboard updates for all organizations."""
    from app import socketio
    from app.models.organization import Organization
    import time

    while True:
        try:
            orgs = Organization.query.all()
            for org in orgs:
                snapshot = get_org_snapshot(org.id)
                snapshot['timestamp'] = time.time()
                print("EMIT CPU:", snapshot["cpu_avg"])
                socketio.emit(
                    "dashboard_update",
                    snapshot,
                    room=f"org_{org.id}",
                    namespace="/metrics"
                )
        except Exception:
            pass
        socketio.sleep(2)
