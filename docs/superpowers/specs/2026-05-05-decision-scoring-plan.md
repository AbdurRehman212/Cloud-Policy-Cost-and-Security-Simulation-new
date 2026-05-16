# Implementation Plan: Decision Scoring System

## Phase 1: Core Engine & Normalization (Backend)
**File to create:** `backend/app/services/scoring_engine.py`
This module will be purely deterministic and mathematical, containing the `MetricNormalizer` and `DecisionScorer` classes.

*   **Step 1.1:** Implement `normalize_latency(p95, target, rps)`. Handles zero load edge cases and applies the mathematical penalty for exceeding the target.
*   **Step 1.2:** Implement `normalize_cost(actual, budget)`. Applies the linear penalty for overspending and handles the zero resources edge case.
*   **Step 1.3:** Implement `normalize_efficiency(cpu_avg, capacity)`. Calculates distance from the optimal 70% CPU band, handling 100% overload states.
*   **Step 1.4:** Implement `normalize_reliability(dropped, queue_ms)`. Applies the strict boolean `0` score for any dropped requests, and `50` for queue warnings.
*   **Step 1.5:** Implement `calculate_final_score(metrics_dict, weights)`. Performs the weighted aggregation `wL*L + wC*C + wE*E + wR*R` and maps it to a letter grade (A, B, C, D, F).

## Phase 2: Scenario Configuration Update
**File to modify:** `backend/app/data/scenarios.py`
We need to append the scenario-specific scoring weights and budget constraints to the existing scenarios without breaking the current structure.

*   **Step 2.1:** Add a `scoring_profile` dictionary to each scenario in `SCENARIOS`. 
    *   *Example:* `"scoring_profile": {"wL": 0.3, "wC": 0.3, "wE": 0.2, "wR": 0.2, "target_latency_ms": 100, "budget_hourly": 5.0}`.

## Phase 3: Integration with Learning Engine & Gemini
**File to modify:** `backend/app/services/learning_engine.py`
This connects the snapshot data, the scoring engine, and the reasoning layer.

*   **Step 3.1:** Create `evaluate_scenario_decision(scenario, snapshot)`. This function will:
    1. Extract raw metrics (`p95_latency`, `cost`, `cpu_avg`, `dropped_requests`, `queue_ms`) from the simulation `snapshot`.
    2. Extract the `scoring_profile` from the `scenario`.
    3. Pass both to `scoring_engine.py` to get the deterministic `score`, `grade`, and `breakdown`.
*   **Step 3.2:** Implement `_generate_gemini_insight(scenario_weights, scores, raw_metrics)`. This will construct the deterministic schema (defined in the spec) and call the Gemini API/CLI to get the causal feedback and suggestions.
*   **Step 3.3:** Return the final `EvaluationReport` dictionary.

## Phase 4: API Exposure & Failure Handling Integration
**File to modify:** `backend/app/routes/scenarios.py`
We need to expose the evaluation report to the frontend during step validation or scenario completion.

*   **Step 4.1:** In the `validate_step` and `complete_scenario` routes, ensure the simulation snapshot is fetched via `control_plane.get_org_snapshot()`.
*   **Step 4.2:** Pass the snapshot and the current scenario to `evaluate_scenario_decision()`.
*   **Step 4.3:** Append the returned `EvaluationReport` to the API response `data` payload. (e.g., `data["evaluation"] = report`).
*   **Step 4.4:** Ensure that queue overflows and dropped requests (which natively occur in `resource_simulator.py`) are strictly caught and bubbled up into the `EvaluationReport` payload.

## Order of Execution
1. Create `scoring_engine.py` (Isolated, easily unit testable).
2. Update `scenarios.py` (Data only).
3. Update `learning_engine.py` (Connects logic to reasoning).
4. Update API routes (Exposes to frontend).

This modular approach ensures clean separation of concerns and prevents any disruption to the existing simulation or dashboard logic.
