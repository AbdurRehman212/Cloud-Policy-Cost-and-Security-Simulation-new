# Decision Scoring and Failure Mechanics Design

## Overview
This document outlines the architecture for the "Decision Evaluation and Learning Feedback" module in the cloud simulator. It introduces a hybrid scoring engine that combines deterministic, mathematical metric normalization with scenario-specific weighting to accurately grade user infrastructure decisions.

## 1. Universal Metrics (The 4 Pillars) & Normalization Logic
Every simulation cycle evaluates four universal metrics. These are normalized to a strict `[0, 100]` float scale.

### 1.1 Latency (L)
Evaluated against a predefined acceptable P95 latency target (`T_latency` = 100ms).
* **Formula:** 
  - If `p95_latency <= T_latency`: `L = 100`
  - If `p95_latency > T_latency`: `L = max(0, 100 - ((p95_latency - T_latency) / T_latency) * 50)`
* **Edge Case (Zero Load):** If `requests_per_second == 0`, `L = 100` (system is perfectly responsive when idle).

### 1.2 Cost (C)
Evaluated against the organization's or scenario's hourly budget (`B`).
* **Formula:**
  - If `actual_cost <= B`: `C = 100`
  - If `actual_cost > B`: `C = max(0, 100 - ((actual_cost - B) / B) * 100)` (Linear harsh penalty; 2x budget = 0).
* **Edge Case (Zero Resources):** If `actual_cost == 0` and budget is > 0, `C = 100`.

### 1.3 Efficiency (E)
Evaluated by checking how close the system's average CPU is to an optimal band (e.g., 60-80%). Let `Target_Mid = 70`.
* **Formula:**
  - Distance `D = abs(cpu_avg - 70)`
  - `E = max(0, 100 - (D * 1.5))`
* **Edge Case (Overload/No Capacity):** If CPU hits 100%, `D = 30 -> E = 55`. However, if capacity is exactly 0 and load exists, CPU defaults to 100, dropping efficiency.

### 1.4 Reliability (R)
A strict boolean-driven stability check evaluating queue overflows and dropped requests.
* **Formula:** 
  - If `dropped_requests > 0`: `R = 0` (Downtime is heavily penalized).
  - If `queue_ms > 1000` (Queue threshold warning): `R = 50`
  - Otherwise: `R = 100`
* **Failure Mechanics Linkage:** High queues naturally degrade performance in `VMDESSimulator`. Dropped requests happen natively when `queue_ms > _MAX_QUEUE_MS`.

## 2. Scenario-Specific Weighting (The Hybrid Model)
Each scenario configuration dictates the relative importance of these metrics via weights (`wL, wC, wE, wR`). The sum of weights must equal 1.0.

* **Mathematical Definition:**
  `Final Score = (wL * L) + (wC * C) + (wE * E) + (wR * R)`
  
* **Weight Configurations (Examples):**
  - *Cost Optimization Scenario:* `wC=0.6, wL=0.2, wE=0.2, wR=0.0`
  - *Black Friday (High Traffic):* `wR=0.4, wL=0.4, wC=0.1, wE=0.1`
  - *Balanced System:* `wL=0.3, wC=0.3, wE=0.2, wR=0.2`

## 3. Feedback and Reasoning Engine (Gemini Integration)
The deterministic score is augmented by the Gemini CLI reasoning layer.
* **Input Schema sent to Gemini:**
  ```json
  {
    "scenario_weights": {"wL": 0.4, "wC": 0.1, "wE": 0.1, "wR": 0.4},
    "normalized_scores": {"L": 90, "C": 40, "E": 85, "R": 100},
    "raw_metrics": {"p95": 85.0, "cost": 150.0, "budget": 100.0, "cpu": 60.0, "dropped": 0},
    "final_score": 78
  }
  ```
* **Output Schema expected from Gemini:**
  ```json
  {
    "insight": "You maintained excellent reliability and latency during the spike, but overspent significantly. Try reducing instance count after the peak load passes.",
    "suggested_actions": ["Scale down resources", "Switch to smaller instance types"]
  }
  ```

## 4. Execution Flow and Integration Point
The scoring system integrates at the end of the simulation step within the Scenario module.
1. **Dataset → Simulation:** `dataset_loader.py` drives spikes. `resource_simulator.py` updates raw metrics (`p95`, `dropped`, `cost`).
2. **Action → Metrics:** User provisions VM. Simulator recalculates load distribution.
3. **Trigger:** User clicks "Evaluate" or "Next Step" in a scenario.
4. **Calculate:** `learning_engine.py` invokes `evaluate_scenario_decision(snapshot, scenario)` which normalizes the 4 metrics and applies weights.
5. **Reasoning:** `evaluate_scenario_decision` runs the Gemini subprocess to generate qualitative feedback.
6. **Delivery:** The `EvaluationReport` is sent back to the frontend.

## 5. Output Schema
The final output to the frontend `EvaluationReport` is fully structured:
```json
{
  "score": 78,
  "grade": "B",
  "breakdown": {
    "latency": 90,
    "cost": 40,
    "efficiency": 85,
    "reliability": 100
  },
  "feedback": "You maintained excellent reliability and latency during the spike, but overspent significantly...",
  "suggestions": ["Scale down resources"],
  "workload_explanation": "Traffic spiked to 800 RPS due to Black Friday dataset pattern."
}
```
