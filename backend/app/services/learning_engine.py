"""Scenario-based learning engine for the cloud simulator."""

from __future__ import annotations
import subprocess
import json
from functools import lru_cache
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.data.scenarios import SCENARIOS
from app.utils.dataset_loader import load_dataset
from app.services.scoring_engine import DecisionScorer


SCENARIO_MAP = {scenario["id"]: scenario for scenario in SCENARIOS}
CURRICULUM_SEQUENCE = [scenario["id"] for scenario in SCENARIOS]
ROLE_LABELS = {
    "viewer": "student",
    "member": "student",
    "student": "student",
    "owner": "organization",
    "organization": "organization",
    "admin": "admin",
    "superadmin": "admin",
}

ROLE_SYSTEM = {
    "student": {
        "title": "Student",
        "description": "Learns cloud concepts by solving guided scenarios.",
        "permissions": ["view scenarios", "run simulations", "track progress"],
    },
    "organization": {
        "title": "Organization",
        "description": "Manages shared infrastructure and team learning paths.",
        "permissions": ["manage organization", "share infra", "review progress"],
    },
    "admin": {
        "title": "Admin",
        "description": "Creates scenarios and manages the learning curriculum.",
        "permissions": ["create scenarios", "seed curriculum", "manage platform"],
    },
}

LEVELS = [
    {"level": 1, "title": "Beginner", "min_points": 0, "focus": "single-service basics"},
    {"level": 2, "title": "Foundation", "min_points": 100, "focus": "safe operations"},
    {"level": 3, "title": "Intermediate", "min_points": 250, "focus": "multi-service reasoning"},
    {"level": 4, "title": "Advanced", "min_points": 500, "focus": "failure recovery and optimization"},
    {"level": 5, "title": "Architect", "min_points": 800, "focus": "system design and tradeoffs"},
]

PROGRESSION_PATH = [
    {
        "level": level["level"],
        "title": level["title"],
        "focus": level["focus"],
        "scenario": next((scenario for scenario in SCENARIOS if scenario.get("recommended_for", "").lower() == level["title"].lower()), None),
    }
    for level in LEVELS
]

TRACK_LIMITS = {
    "beginner": 1,
    "intermediate": 3,
    "advanced": 4,
}

TRACK_ALIASES = {
    "foundation": "intermediate",
    "starter": "beginner",
    "expert": "advanced",
}


def resolve_learning_role(user=None, membership=None) -> str:
    """Map platform roles to the learning role requested by the product."""
    if getattr(user, "is_superadmin", False):
        return "admin"
    role = getattr(membership, "role", None) or getattr(membership, "my_role", None)
    if role in {"owner", "admin"}:
        return "organization"
    return "student"


def normalize_learning_level(level: str | None) -> str:
    """Normalize level labels to the supported learning tracks."""
    normalized = (level or "beginner").strip().lower()
    normalized = TRACK_ALIASES.get(normalized, normalized)
    if normalized not in TRACK_LIMITS:
        return "beginner"
    return normalized


def curriculum_limit(level: str | None) -> int:
    """Return the maximum scenario index unlocked for a learning track."""
    return TRACK_LIMITS.get(normalize_learning_level(level), 1)


def _scenario_id_list(limit: int) -> list[int]:
    return [scenario_id for scenario_id in CURRICULUM_SEQUENCE if scenario_id <= limit]


def next_unlocked_scenario(progress=None, level: str | None = None) -> dict[str, Any] | None:
    """Return the next scenario the learner can actually open."""
    limit = curriculum_limit(level)
    completed = set((getattr(progress, "scenarios_completed", None) or []))
    for scenario_id in _scenario_id_list(limit):
        if str(scenario_id) not in completed and scenario_id not in completed:
            return SCENARIO_MAP.get(scenario_id)
    return SCENARIO_MAP.get(_scenario_id_list(limit)[-1]) if _scenario_id_list(limit) else None


def scenario_unlock_state(progress=None, level: str | None = None) -> list[dict[str, Any]]:
    """Return scenario unlock metadata for the frontend."""
    limit = curriculum_limit(level)
    completed = set(str(item) for item in (getattr(progress, "scenarios_completed", None) or []))
    unlocked_ids = _scenario_id_list(limit)
    next_scenario = next_unlocked_scenario(progress=progress, level=level)
    next_scenario_id = next_scenario.get("id") if next_scenario else None
    states: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        scenario_id = scenario["id"]
        unlocked = scenario_id in unlocked_ids and (
            scenario_id == next_scenario_id or str(scenario_id) in completed
        )
        states.append({
            "id": scenario_id,
            "unlocked": unlocked,
            "locked": not unlocked,
            "completed": str(scenario_id) in completed,
            "unlock_limit": limit,
            "reason": (
                "Complete the current module first" if not unlocked else "Available now"
            ),
        })
    return states


@lru_cache(maxsize=1)
def dataset_workload_patterns() -> dict[str, Any]:
    """Derive realistic workload patterns from the staged dataset."""
    try:
        frame = load_dataset()
    except Exception:
        frame = pd.DataFrame()

    if frame.empty:
        return {
            "spikes": {"peak_cpu": 0, "peak_memory": 0, "count": 0},
            "seasonal": {"peak_window": [], "off_peak_window": []},
            "failures": [],
        }

    cpu = pd.to_numeric(frame["cpu_avg"], errors="coerce").fillna(0)
    mem = pd.to_numeric(frame["mem_avg"], errors="coerce").fillna(0)
    time_axis = pd.to_numeric(frame["time"], errors="coerce").fillna(0)
    high_cpu = cpu.quantile(0.9)
    low_cpu = cpu.quantile(0.1)
    peak_rows = frame.loc[cpu >= high_cpu, ["time", "cpu_avg", "mem_avg"]].head(5)
    trough_rows = frame.loc[cpu <= low_cpu, ["time", "cpu_avg", "mem_avg"]].head(5)

    def _rows_to_series(rows: pd.DataFrame) -> list[dict[str, Any]]:
        return [
            {
                "time": int(row["time"]),
                "cpu_avg": round(float(row["cpu_avg"]), 2),
                "mem_avg": round(float(row["mem_avg"]), 2),
            }
            for _, row in rows.iterrows()
        ]

    failure_rows = frame.loc[(cpu >= cpu.quantile(0.95)) | (mem >= mem.quantile(0.95)), ["time", "cpu_avg", "mem_avg"]].head(10)
    return {
        "spikes": {
            "peak_cpu": round(float(cpu.max()), 2),
            "peak_memory": round(float(mem.max()), 2),
            "count": int((cpu >= high_cpu).sum()),
        },
        "seasonal": {
            "peak_window": _rows_to_series(peak_rows),
            "off_peak_window": _rows_to_series(trough_rows),
            "time_span": [int(time_axis.min()), int(time_axis.max())],
        },
        "failures": _rows_to_series(failure_rows),
    }


def role_profile(role: str) -> dict[str, Any]:
    """Return a short role description for the learning UI."""
    return {
        "role": role,
        **ROLE_SYSTEM.get(role, ROLE_SYSTEM["student"]),
    }


def current_level(total_points: int | None) -> dict[str, Any]:
    points = int(total_points or 0)
    level = LEVELS[0]
    for candidate in LEVELS:
        if points >= candidate["min_points"]:
            level = candidate
    next_level = next((candidate for candidate in LEVELS if candidate["level"] > level["level"]), None)
    return {
        **level,
        "points": points,
        "points_to_next": max(0, (next_level["min_points"] - points) if next_level else 0),
        "next_level": next_level["title"] if next_level else None,
        "roadmap": PROGRESSION_PATH,
    }


def level_options() -> list[dict[str, Any]]:
    return [
        {
            "id": "beginner",
            "title": "Beginner",
            "description": "Focus on the first module and guided feedback.",
        },
        {
            "id": "intermediate",
            "title": "Intermediate",
            "description": "Unlock the first three modules in sequence.",
        },
        {
            "id": "advanced",
            "title": "Advanced",
            "description": "Unlock the full recovery and optimization path.",
        },
    ]


def explain_metric_change(scenario: dict[str, Any], snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a short causal explanation for why the metrics changed."""
    snapshot = snapshot or {}
    cause_effect = scenario.get("cause_effect", {})
    loop = scenario.get("learning_loop", {})
    return {
        "why": cause_effect.get("why", scenario.get("description", "")),
        "trigger": cause_effect.get("trigger", scenario.get("title", "Scenario trigger")),
        "result": cause_effect.get("result", "The simulator updated its state based on the chosen action."),
        "what_you_changed": loop.get("action", "A corrective action was applied."),
        "why_this_changes_metrics": cause_effect.get(
            "why",
            "The simulator responds to the selected action by changing workload, capacity, or risk.",
        ),
        "evidence": {
            "cpu_avg": snapshot.get("cpu_avg", 0),
            "memory_avg": snapshot.get("memory_avg", 0),
            "queue_total_ms": snapshot.get("workload", {}).get("queue_total_ms", 0),
            "p95_latency_ms": snapshot.get("workload", {}).get("p95_latency_ms", 0),
            "bpi": snapshot.get("bpi", 0),
            "target_bpi": snapshot.get("target_bpi", 0),
            "capacity": snapshot.get("capacity", 1),
        },
    }


def recommended_scenario(level_title: str | None = None, progress=None) -> dict[str, Any] | None:
    """Pick the next scenario the learner should see for the selected track."""
    next_scenario = next_unlocked_scenario(progress=progress, level=level_title)
    if next_scenario:
        return next_scenario
    return SCENARIOS[0] if SCENARIOS else None


def learning_loop_for_scenario(scenario: dict[str, Any], snapshot: dict[str, Any] | None = None, *, level: str | None = None, progress=None) -> dict[str, Any]:
    """Return the learning loop: user → scenario → action → simulation → result → explanation."""
    snapshot = snapshot or {}
    loop = scenario.get("learning_loop", {})
    explanation = explain_metric_change(scenario, snapshot)
    return {
        "user": loop.get("user", "student"),
        "scenario": loop.get("scenario", scenario.get("title")),
        "action": loop.get("action", "Take a corrective action"),
        "simulation": loop.get("simulation", "The simulator updates metrics and behavior."),
        "result": loop.get("result", "Observe what changed."),
        "explanation": explanation,
        "cause_effect": scenario.get("cause_effect", {}),
        "module": scenario.get("module"),
        "next_scenario": recommended_scenario(level, progress),
    }


def build_learning_profile(user=None, membership=None, progress=None, snapshot=None, level: str | None = None) -> dict[str, Any]:
    """Compose a scenario-based learning view for the dashboard and labs."""
    role = resolve_learning_role(user, membership)
    role_info = role_profile(role)
    progress_level = current_level(getattr(progress, "total_points", None) if progress else None)
    selected_level = normalize_learning_level(level or getattr(progress, "learning_stage", None))
    scenario = recommended_scenario(selected_level, progress=progress)
    loop = learning_loop_for_scenario(scenario, snapshot, level=selected_level, progress=progress) if scenario else None
    return {
        "role": role,
        "role_info": role_info,
        "level": progress_level,
        "learning_track": selected_level,
        "level_options": level_options(),
        "scenario_catalog": SCENARIOS,
        "recommended_scenario": scenario,
        "learning_loop": loop,
        "modules": [s.get("module", s.get("title")) for s in SCENARIOS],
        "progression_path": PROGRESSION_PATH,
        "curriculum_limit": curriculum_limit(selected_level),
        "unlock_state": scenario_unlock_state(progress=progress, level=selected_level),
        "next_scenario": next_unlocked_scenario(progress=progress, level=selected_level),
        "workload_patterns": dataset_workload_patterns(),
        "scenario_learning_map": [
            {
                "id": scenario_item["id"],
                "module": scenario_item.get("module"),
                "difficulty": scenario_item.get("difficulty"),
                "recommended_for": scenario_item.get("recommended_for"),
                "learning_loop": scenario_item.get("learning_loop", {}),
                "cause_effect": scenario_item.get("cause_effect", {}),
                "locked": scenario_item["id"] > curriculum_limit(selected_level),
            }
            for scenario_item in SCENARIOS
        ],
    }


def _generate_gemini_insight(payload: dict) -> dict:
    """Invoke Gemini CLI to get qualitative feedback."""
    breakdown = payload.get("normalized_scores", {})
    weakest_metric = min(breakdown.keys(), key=lambda k: breakdown[k]) if breakdown else "latency"

    prompt = (
        "As a cloud architect, evaluate these simulation results.\n"
        f"Scenario Type: {payload.get('scenario_type', 'General')}\n"
        f"Final Score: {payload.get('final_score')} (Grade: {payload.get('grade')})\n"
        f"Full Breakdown: {json.dumps(breakdown)}\n\n"
        "You MUST provide your response in JSON format with exactly two keys: 'insight' and 'suggested_actions'.\n"
        "Follow these instructions strictly:\n"
        "- Explain why this score was given (max 1 sentence).\n"
        "- Identify the weakest metric in your explanation.\n"
        "- Suggest one concrete action (max 1 action).\n"
    )

    if breakdown.get("cost", 100) < 60:
        prompt += "- The suggestion MUST mention cost reduction.\n"
    if breakdown.get("latency", 100) < 60:
        prompt += "- The suggestion MUST mention scaling/performance.\n"
    if breakdown.get("reliability", 100) < 100:
        prompt += "- The suggestion MUST mention preventing drops.\n"

    def deterministic_fallback():
        insight = f"Your final score is {payload.get('final_score')} ({payload.get('grade')}) due to low performance in {weakest_metric}."
        if breakdown.get("reliability", 100) < 100:
            action = "Prevent dropped requests by ensuring sufficient capacity."
        elif breakdown.get("latency", 100) < 60:
            action = "Scale out or improve performance to reduce latency."
        elif breakdown.get("cost", 100) < 60:
            action = "Implement cost reduction by right-sizing or removing idle instances."
        else:
            action = f"Optimize {weakest_metric} to improve your overall score."
        return {
            "insight": insight,
            "suggested_actions": [action]
        }

    try:
        # Use subprocess to call gemini CLI
        result = subprocess.check_output(["gemini", prompt], text=True, timeout=10)
        # Attempt to parse JSON from output
        start_idx = result.find("{")
        end_idx = result.rfind("}") + 1
        if start_idx != -1 and end_idx != -1:
            data = json.loads(result[start_idx:end_idx])
            insight = data.get("insight", "")
            actions = data.get("suggested_actions", [])
            action_text = actions[0] if actions else ""
            
            combined_text = (insight + " " + action_text).lower()
            
            # Rule 4: Discard and fallback if weakest metric is not referenced
            if weakest_metric.lower() not in combined_text:
                return deterministic_fallback()
                
            # Rule 3: Rule-based guards
            if breakdown.get("cost", 100) < 60 and "cost" not in combined_text:
                 return deterministic_fallback()
            if breakdown.get("latency", 100) < 60 and ("scal" not in combined_text and "performance" not in combined_text):
                 return deterministic_fallback()
            if breakdown.get("reliability", 100) < 100 and "drop" not in combined_text and "prevent" not in combined_text:
                 return deterministic_fallback()
                 
            return {
                "insight": insight,
                "suggested_actions": [action_text] if action_text else []
            }
        return deterministic_fallback()
    except Exception:
        return deterministic_fallback()


def evaluate_scenario_decision(scenario: dict, snapshot: dict, include_ai: bool = False) -> dict:
    """Calculate the decision score and generate feedback."""
    scoring_profile = scenario.get("scoring_profile", {
        "wL": 0.25, "wC": 0.25, "wE": 0.25, "wR": 0.25,
        "target_latency_ms": 100.0,
        "budget": 10.0
    })

    # Map snapshot to raw metrics expected by scorer
    workload = snapshot.get("workload", {})
    
    rps = workload.get("requests_per_second", 0.0)
    capacity = snapshot.get("capacity", 1.0)
    dropped = workload.get("dropped_recent_total", 0)
    
    # Idle system exploit fix: if scenario expects workload but system is down/idle
    if scenario.get("requires_load", True):
        if capacity == 0 or rps == 0:
            dropped = max(1, dropped) # Force failure state

    raw_metrics = {
        "p95_latency": workload.get("p95_latency_ms", 0.0),
        "rps": rps,
        "actual_cost": snapshot.get("current_hourly_cost", 0.0) * 720.0, # Projected monthly cost
        "cpu_avg": snapshot.get("cpu_avg", 0.0),
        "capacity": capacity,
        "dropped_requests": dropped,
        "queue_ms": workload.get("queue_total_ms", 0.0)
    }

    weights = {k: scoring_profile.get(k, 0.25) for k in ["wL", "wC", "wE", "wR"]}
    constraints = {
        "target_latency": scoring_profile.get("target_latency_ms", 100.0),
        "budget": scoring_profile.get("budget", 10.0)
    }

    report = DecisionScorer.calculate_score(raw_metrics, weights, constraints)

    if include_ai:
        import threading
        
        def run_ai():
            try:
                insight_payload = {
                    "scenario_weights": weights,
                    "normalized_scores": report["breakdown"],
                    "raw_metrics": raw_metrics,
                    "final_score": report["score"],
                    "grade": report["grade"],
                    "scenario_type": scenario.get("category", scenario.get("title", "general"))
                }
                _generate_gemini_insight(insight_payload)
            except Exception:
                pass

        # Non-blocking AI execution
        threading.Thread(target=run_ai, daemon=True).start()
        
        report.update({
            "insight": "AI feedback is being generated...",
            "suggested_actions": ["Generating suggestions..."]
        })
    else:
        report.update({
            "insight": "AI insight is optional. Request with include_ai=true to generate.",
            "suggested_actions": ["Review metrics to optimize performance and cost."]
        })

    report["workload_explanation"] = f"Traffic behavior driven by scenario workload patterns for {scenario.get('title')}."

    return report


@dataclass(frozen=True)
class ValidationPredicate:
    """Single deterministic predicate used by state-driven lab validation."""

    field: str
    operator: str
    expected: Any
    source: str = 'snapshot'

    def evaluate(self, state: dict[str, Any]) -> dict[str, Any]:
        actual = state.get(self.field)
        operator = (self.operator or '').strip().lower()
        comparisons = {
            'greater_than': lambda a, b: a > b,
            'greater_than_or_equal': lambda a, b: a >= b,
            'less_than': lambda a, b: a < b,
            'less_than_or_equal': lambda a, b: a <= b,
            'equal': lambda a, b: a == b,
            'equals': lambda a, b: a == b,
        }
        comparator = comparisons.get(operator)
        passed = bool(comparator(actual, self.expected)) if comparator else False
        return {
            'field': self.field,
            'operator': self.operator,
            'expected': self.expected,
            'actual': actual,
            'source': self.source,
            'passed': passed,
        }


class LabValidationEngine:
    """State-driven validation engine for Lab 3 security progression only."""

    LAB3_SCENARIO_ID = 3
    DEFAULT_SECURITY_TARGET = 90
    DEFAULT_COMPLIANCE_THRESHOLD = 80

    @staticmethod
    def _count_insecure_rules(org_id: int) -> tuple[int, list[dict[str, Any]]]:
        from app.models.resources import SecurityGroup, SecurityGroupRule, Database

        open_cidrs = {'0.0.0.0/0', '::/0', '*', 'any', 'all'}
        rules = SecurityGroupRule.query.join(SecurityGroup).filter(SecurityGroup.org_id == org_id).all()
        insecure_details: list[dict[str, Any]] = []

        for rule in rules:
            direction = (rule.direction or '').strip().lower()
            action = (rule.action or '').strip().lower()
            source_cidr = (rule.source_cidr or '').strip().lower()
            protocol = (rule.protocol or '').strip().lower()
            if action != 'allow' or direction != 'inbound':
                continue
            if source_cidr in open_cidrs or protocol == 'all':
                insecure_details.append({
                    'kind': 'security_rule',
                    'security_group_id': rule.group_id,
                    'rule_id': rule.id,
                    'source_cidr': rule.source_cidr,
                    'protocol': rule.protocol,
                    'port_range': rule.port_range,
                })

        public_databases = Database.query.filter_by(organization_id=org_id, publicly_accessible=True).all()
        for database in public_databases:
            insecure_details.append({
                'kind': 'public_database',
                'resource_id': database.instance_id,
                'name': database.name,
            })

        return len(insecure_details), insecure_details

    @classmethod
    def snapshot_state_for_org(cls, org_id: int, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        snapshot = snapshot or {}
        security_block = snapshot.get('security', {})
        governance_block = snapshot.get('governance', {})
        runtime_block = snapshot.get('runtime', {})
        insecure_rules, insecure_rule_details = cls._count_insecure_rules(org_id)
        active_threats = int(snapshot.get('active_threats', security_block.get('active_threats', 0)) or 0)
        security_score = float(snapshot.get('security_score', security_block.get('security_score', 0)) or 0)
        compliance_score = float(snapshot.get('compliance_score', governance_block.get('compliance_score', 100)) or 0)
        return {
            'organization_id': org_id,
            'active_threats': active_threats,
            'security_score': security_score,
            'compliance_score': compliance_score,
            'insecure_rules': insecure_rules,
            'insecure_rule_details': insecure_rule_details,
            'running_vms': int(snapshot.get('running_vms', runtime_block.get('vm_count', 0)) or 0),
            'total_vms': int(snapshot.get('total_vms', 0) or 0),
        }

    @staticmethod
    def _compile_predicates(step: dict[str, Any]) -> tuple[str, list[ValidationPredicate], dict[str, Any]]:
        validation_value = step.get('validation_value') or {}
        mode = (validation_value.get('mode') or 'all').strip().lower()
        predicates = [
            ValidationPredicate(
                field=item.get('field', ''),
                operator=item.get('operator', 'equal'),
                expected=item.get('value'),
                source=item.get('source', 'snapshot'),
            )
            for item in validation_value.get('predicates', [])
            if item.get('field')
        ]
        return mode, predicates, validation_value

    @staticmethod
    def _posture_score(state: dict[str, Any]) -> tuple[float, dict[str, float]]:
        threats_penalty = min(40.0, float(state.get('active_threats', 0)) * 20.0)
        security_gap_penalty = max(0.0, 90.0 - float(state.get('security_score', 0))) * 0.5
        insecure_rule_penalty = min(30.0, float(state.get('insecure_rules', 0)) * 15.0)
        compliance_gap_penalty = max(0.0, 80.0 - float(state.get('compliance_score', 0))) * 0.5
        score = max(0.0, 100.0 - threats_penalty - security_gap_penalty - insecure_rule_penalty - compliance_gap_penalty)
        return round(score, 1), {
            'threats': round(100.0 - threats_penalty, 1),
            'security': round(max(0.0, 100.0 - security_gap_penalty), 1),
            'infrastructure': round(max(0.0, 100.0 - insecure_rule_penalty), 1),
            'compliance': round(max(0.0, 100.0 - compliance_gap_penalty), 1),
        }

    @staticmethod
    def _grade_for(score: float) -> str:
        if score >= 90:
            return 'A'
        if score >= 80:
            return 'B'
        if score >= 70:
            return 'C'
        if score >= 60:
            return 'D'
        return 'F'

    def evaluate_lab3_step(
        self,
        org_id: int,
        scenario: dict[str, Any],
        step: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        state = self.snapshot_state_for_org(org_id, snapshot)
        mode, predicates, validation_value = self._compile_predicates(step)
        predicate_results = [predicate.evaluate(state) for predicate in predicates]

        if not predicate_results:
            predicate_results = []
        if mode == 'any':
            valid = any(result['passed'] for result in predicate_results)
        else:
            valid = all(result['passed'] for result in predicate_results) if predicate_results else False

        failed = next((result for result in predicate_results if not result['passed']), None)
        score, breakdown = self._posture_score(state)
        target_security = int(validation_value.get('target_security_score', self.DEFAULT_SECURITY_TARGET))
        compliance_threshold = int(validation_value.get('compliance_threshold', self.DEFAULT_COMPLIANCE_THRESHOLD))

        if valid:
            message = 'Lab 3 security posture satisfies the current state predicates.'
        elif failed:
            message = f"{failed['field']} failed {failed['operator']} {failed['expected']}"
        else:
            message = 'Lab 3 security posture does not satisfy the state predicates.'

        return {
            'valid': valid,
            'message': message,
            'state': state,
            'predicates': predicate_results,
            'targets': {
                'security_score': target_security,
                'compliance_score': compliance_threshold,
            },
            'evaluation': {
                'score': score,
                'grade': self._grade_for(score),
                'breakdown': breakdown,
                'state': state,
                'predicates': predicate_results,
            },
        }


lab_validation_engine = LabValidationEngine()
