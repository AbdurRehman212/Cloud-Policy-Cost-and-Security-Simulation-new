"""scenario_runner.py — Scenario run coordinator.

The CloudSim-style per-org simulation loop has been removed.
Real simulation runs continuously via des_engine + resource_simulator.
ScenarioRunner now acknowledges scenario starts and provides state for
the frontend run status poll.  Workload patterns are informational only;
the MAPE loop in control_plane.py handles autoscaling based on live load.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List

logger = logging.getLogger(__name__)

SCENARIO_WORKLOAD_PATTERNS: Dict[int, List[Dict]] = {
    1: [{"rps": 80, "ticks": 4, "label": "Baseline"}, {"rps": 300, "ticks": 6, "label": "Traffic burst"},
        {"rps": 500, "ticks": 4, "label": "Peak overload"}, {"rps": 200, "ticks": 4, "label": "Cooldown"},
        {"rps": 80, "ticks": 2, "label": "Recovery"}],
    2: [{"rps": 20, "ticks": 6, "label": "Idle load"}, {"rps": 10, "ticks": 4, "label": "Near-zero"},
        {"rps": 50, "ticks": 4, "label": "Right-sized"}, {"rps": 30, "ticks": 6, "label": "Stable low"}],
    3: [{"rps": 60, "ticks": 5, "label": "Normal"}, {"rps": 75, "ticks": 5, "label": "Slightly elevated"},
        {"rps": 60, "ticks": 5, "label": "Normal"}, {"rps": 55, "ticks": 5, "label": "Baseline"}],
    4: [{"rps": 150, "ticks": 3, "label": "Pre-outage"}, {"rps": 0, "ticks": 4, "label": "Outage"},
        {"rps": 50, "ticks": 3, "label": "Recovery ramp"}, {"rps": 120, "ticks": 4, "label": "Restored"},
        {"rps": 150, "ticks": 6, "label": "Healthy steady"}],
}
_DEFAULT_PATTERN = [{"rps": 100, "ticks": 10, "label": "Default"}]

_active_runs: Dict[int, dict] = {}


def _expand_pattern(pattern: List[Dict]) -> List[int]:
    result: List[int] = []
    for seg in pattern:
        result.extend([seg["rps"]] * seg["ticks"])
    return result


class ScenarioRunner:
    """Coordinates scenario run state; real simulation is in des_engine + control_plane."""

    def start(self, scenario_id: int, org_id: int) -> dict:
        if _active_runs.get(org_id, {}).get('is_running'):
            return {"ok": False, "error": "A scenario is already running.", "code": "scenario_already_running"}

        pattern = SCENARIO_WORKLOAD_PATTERNS.get(scenario_id, _DEFAULT_PATTERN)
        rps_sequence = _expand_pattern(pattern)

        _active_runs[org_id] = {
            'is_running': True,
            'scenario_id': scenario_id,
            'total_ticks': len(rps_sequence),
            'current_tick': 0,
            'dropped_requests': 0,
            'vm_count': 0,
            'started_at': time.time(),
            'workload_pattern': pattern,
        }
        logger.info(
            '[scenario_runner] Scenario %s started for org %s '
            '(%d ticks, DES engine active)',
            scenario_id, org_id, len(rps_sequence),
        )
        return {
            "ok": True,
            "scenario_id": scenario_id,
            "org_id": org_id,
            "total_ticks": len(rps_sequence),
            "workload_pattern": pattern,
        }

    def stop(self, org_id: int) -> None:
        run = _active_runs.pop(org_id, None)
        if run:
            logger.info('[scenario_runner] Scenario %s stopped for org %s',
                        run.get('scenario_id'), org_id)

    def get_state(self, org_id: int) -> dict:
        return _active_runs.get(org_id, {
            'is_running': False,
            'scenario_id': None,
            'total_ticks': 0,
            'current_tick': 0,
            'dropped_requests': 0,
            'vm_count': 0,
        })


scenario_runner = ScenarioRunner()
