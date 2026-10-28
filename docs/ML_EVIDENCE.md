# AI/ML Evidence Note (Modules 1–9)

Everything below was read from the code or measured by running it. Re-run the measurement with
`cd backend && python scripts/evaluate_threat_detector.py` (prints all numbers; nothing is hard-coded).

## Summary

| Component | What it really is | Trained? | Evaluated? |
|---|---|---|---|
| Threat Detector (M6) | scikit-learn `RandomForestClassifier` (64 trees, depth 8) on 13 features; falls back to a centroid classifier, then to fixed thresholds, if sklearn/data are unavailable | Yes, at start-up, on a 3,000-row CICIDS2017 subset | Now: `scripts/evaluate_threat_detector.py` (see below) |
| Cost Forecaster (M8) | Linear trend (`LinearRegression`, or `numpy.polyfit`) on daily total cost; "range" = prediction ± 1.5 × residual std | Fit per request on the organization's own cost history | No (see limits) |
| Wastage / optimization (M8) | Explicit rules: IDLE (CPU < 10 %), UNDERUTILIZED (CPU < 30 % and memory < 40 %) | No — rule-based, not ML | Unit tests (`tests/test_cost.py`) |
| Policy Engine (M7) | Rule compiler: `key=value` rules plus a small set of fixed natural-language patterns | No — rule-based, not ML or an LLM | Unit tests (`tests/test_governance.py`) |
| Data Generator (M3) | Seeded statistical sampling (normal noise, exponential spikes, business-hour factor) around a baseline taken from the Alibaba trace subset | No — simulation, not a learned model | `tests/test_data_generator.py` |
| Help Assistant | Keyword matching against fixed answers (`routes/assistant.py`) | No — no LLM | — |

## Datasets (from `backend/data/README.md` and the files)
- `cicids_subset.csv` — 3,000 flows from CICIDS2017: 2,467 normal, 421 DDoS/DoS/bots, 96 port scan, 16 brute force/web attacks.
- `dataset-3k-final.csv` — 3,098 rows of Alibaba Cluster Trace 2018 utilisation, used as the baseline for the Data Generator and cost history.

## Threat detector — measured results (this repository, seed 42, 80/20 stratified split)

| Experiment | Accuracy | Macro-F1 |
|---|---|---|
| A. Deployed 13 features | 1.000 | 1.000 |
| B. Same model without the 4 label-derived features (9 features) | 0.988 | 0.988 |

Per-class recall in B: normal 0.996, ddos 0.940, port_scan 1.000, brute_force 1.000.

### Findings (limitations that must be stated in the report, video and viva)
1. **Label leakage in the deployed feature set.** `_derive_security_frame_from_cicids` builds `error_rate`, `cpu_utilization`, `memory_utilization` and `auth_failures` from constants keyed on the class label/attack name. They are not real CICIDS signals, so experiment A (1.000) is **not** a valid accuracy figure. Experiment B is the more honest estimate.
2. **Very small minority classes.** Only 16 brute-force rows exist (≈3 in the test split), so brute-force recall of 1.000 is not statistically meaningful. The split is random within one dataset, so near-duplicate flows probably make B optimistic too.
3. **Domain mismatch with the simulator.** The model is trained on network-flow features rescaled to "VM metrics", but the simulator produces its own metric scales. Measured on the simulator's own attack scenarios (3 rows each): DDoS 0/3 (low) and 0/3 (high), port scan 0/3 and 0/3, brute force 2/3 and 2/3 flagged as the intended type.
4. **"Simulate Attack" is not a model prediction.** It creates a threat record directly (model version `simulation`). The UI now marks these rows "Simulated (no model score)" and the modal text no longer claims the AI detects them.
5. **Auto-detections on idle simulated VMs can be false positives** (seen during testing); live-metric detections have not been evaluated against ground truth.

### Why this model was used
A Random Forest is a standard, fast, explainable baseline for tabular intrusion data and trains in seconds without a GPU. No comparison against other algorithms was run, so "best model" must not be claimed.

### Recommended corrections (not done — they change detector behaviour and need retraining/validation)
- Remove or replace the four label-derived features, retrain, and re-measure.
- Calibrate or map simulator metrics to the training distribution, or train on simulator-generated labelled scenarios, then re-measure experiment C.
- Add a grouped/time-aware split and report per-class precision/recall with confidence intervals.

## Cost forecaster — limits
- A straight-line fit on daily totals; it cannot model seasonality. With fewer than 2 days of data it falls back to the average (flat). The ±1.5 σ band is a heuristic range, not a statistical prediction interval.
- The cost history is itself simulated (cost records are produced by the simulator), so the forecast demonstrates the technique, not real billing accuracy.
- No backtest has been run: the available history is too short for a meaningful one. Do not quote an accuracy figure.

## Wording rules for report/video
- Say "rule-based" for policies, wastage and the help assistant; "statistical simulation" for the Data Generator; "Random Forest trained on a CICIDS2017 subset" for threat classification, together with the limitations above.
- Do not call the Help Assistant, policy compiler or wastage rules "AI" or "machine learning".
