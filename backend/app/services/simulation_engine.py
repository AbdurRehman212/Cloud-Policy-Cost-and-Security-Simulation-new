"""simulation_engine.py — DISABLED (no-op stub).

This file is preserved to avoid ImportError in callers that have not been
migrated away from it. All real simulation logic lives in:

  - app.services.des_engine      — DES / M/M/c queue
  - app.services.resource_simulator — VM state + telemetry
  - app.services.control_plane   — MAPE loop, autoscaling, snapshot cache
"""
from __future__ import annotations


class _FakeHost:
    def __init__(self):
        self.vms = []


class SimulationEngine:
    """No-op stub — real simulation is handled by des_engine + control_plane."""

    def __init__(self):
        self._default_host = _FakeHost()

    def start(self, app=None):
        pass

    def stop(self):
        pass

    def add_vm(self, org_id, instance_id):
        pass

    def remove_vm(self, org_id, instance_id):
        pass

    def start_scenario(self, org_id, workload_pattern=None, scenario_id=None):
        return False

    def stop_scenario(self, org_id):
        pass

    def is_scenario_running(self, org_id):
        return False

    def get_state(self, org_id):
        return {
            'is_running': False,
            'total_ticks': 0,
            'current_tick': 0,
            'dropped_requests': 0,
            'vm_count': 0,
            'metrics': {},
        }
