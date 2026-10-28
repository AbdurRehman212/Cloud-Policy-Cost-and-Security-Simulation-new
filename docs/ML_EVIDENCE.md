# AI/ML Evidence Note (Modules 1–9)

Everything below was read from the code or measured by running it. Re-run the measurement with
`cd backend && python scripts/evaluate_threat_detector.py` (prints all numbers; nothing is hard-coded).

## Summary

| Component | What it really is | Trained? | Evaluated? |
|---|---|---|---|
| Threat Detector (M6) | scikit-learn `RandomForestClassifier` (64 trees, depth 8) on 10 flow-derived features; falls back to a centroid classifier, then to fixed thresholds, if sklearn/data are unavailable | Yes, at start-up, on a 3,000-row CICIDS2017 subset | Yes: 60/20/20 split, scripted (`scripts/evaluate_threat_detector.py`) |
| Cost Forecaster (M8) | Linear trend (`LinearRegression`, or `numpy.polyfit`) on daily total cost; "range" = prediction ± 1.5 × residual std | Fit per request on the organization's own cost history | No (see limits) |
| Wastage / optimization (M8) | Explicit rules: IDLE (CPU < 10 %), UNDERUTILIZED (CPU < 30 % and memory < 40 %) | No — rule-based, not ML | Unit tests (`tests/test_cost.py`) |
| Policy Engine (M7) | Rule compiler: `key=value` rules plus a small set of fixed natural-language patterns | No — rule-based, not ML or an LLM | Unit tests (`tests/test_governance.py`) |
| Data Generator (M3) | Seeded statistical sampling (normal noise, exponential spikes, business-hour factor) around a baseline taken from the Alibaba trace subset | No — simulation, not a learned model | `tests/test_data_generator.py` |
| Help Assistant | Keyword matching against fixed answers (`routes/assistant.py`) | No — no LLM | — |

## Datasets (from `backend/data/README.md` and the files)
- `cicids_subset.csv` — 3,000 flows from CICIDS2017: 2,467 normal, 421 DDoS/DoS/bots, 96 port scan, 16 brute force/web attacks.
- `dataset-3k-final.csv` — 3,098 rows of Alibaba Cluster Trace 2018 utilisation, used as the baseline for the Data Generator and cost history.

## Threat detector — measured results (model `rf-863ed0be8a`, seed 42)

Retrained after the leakage finding below. The detector now uses **10 features**, all derived from CICIDS flow fields;
`cpu_utilization`, `memory_utilization` and `auth_failures` were removed (they were built from the class label) and
`error_rate` keeps only its flow-derived part. Deployed inputs = training inputs (enforced by `tests/test_threat_model.py`).
Protocol: stratified 60/20/20 train/validation/test; the test split is used once. Reproduce with `python scripts/evaluate_threat_detector.py`.

| Split | n | Accuracy | Macro-F1 | Benign false-positive rate |
|---|---|---|---|---|
| Validation | 600 | 0.985 | 0.862 | 0.008 |
| **Test** | 600 | **0.983** | **0.902** | **0.010** |

Test per-class results:

| Class | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| normal | 0.990 | 0.990 | 0.990 | 494 |
| ddos | 0.952 | 0.952 | 0.952 | 84 |
| port_scan | 1.000 | 1.000 | 1.000 | 19 |
| brute_force | 0.667 | 0.667 | 0.667 | **3** |

Test confusion matrix (rows = true; columns = normal, ddos, port_scan, brute_force):
normal [489, 4, 0, 1] · ddos [4, 80, 0, 0] · port_scan [0, 0, 19, 0] · brute_force [1, 0, 0, 2].
Macro-F1 over 5 different 80/20 splits: mean 0.944, min 0.922, max 0.993 (the spread comes from the rare classes).

### Version and what is running
Model version = hash of the exact training data plus feature list (`rf-863ed0be8a`), stored on each detected threat
(`model_version`) and returned by `GET /api/security/model-info` (algorithm, features, training rows, class counts,
scikit-learn version, training time). The running backend trains at start-up from `backend/data/cicids_subset.csv`;
no model file is persisted. If the dataset is missing it falls back to labelled fixed thresholds (`source: heuristic`).

### Limitations that remain (state them in the report, video and viva)
1. **The detector does not detect the simulator's attack scenarios.** Scored by the deployed model, DDoS, port-scan and brute-force
   scenarios (low and high intensity, 3 rows each) are all classified `normal` (0/3 in every case). Before the retraining,
   brute force scored 2/3 only because of the leaked `auth_failures` feature. The training data are network flows
   rescaled to "VM metrics"; the simulator's telemetry lives on different scales, so the model's CICIDS performance does not
   transfer. **No claim of accurate detection on simulator traffic can be made.**
2. **Simulate Attack is not a model prediction** (model version `simulation`); the UI labels it "Simulated (no model score)".
3. **Brute force has 16 rows in the whole dataset (3 in the test split)**; its metrics are not statistically meaningful.
   Random splits within one dataset (near-duplicate flows) make all figures optimistic relative to unseen traffic.
4. **Normal simulator telemetry** (600 Data Generator rows) was classified `normal` in all 600 cases, but that is the simulator's
   own notion of normal, not independent ground truth.
5. **Not production-ready.** No external validation, no drift monitoring, no calibration of the reported "confidence".
6. The `disk_*_iops` and `network_*_mbps` features are proxies computed from header lengths and byte rates; they carry
   the names of VM metrics but not their meaning.

### Previous (superseded) results — kept for the record
With the original 13 features the same protocol gave accuracy 1.000, which was **not valid**: four features were
constructed from the class label. Without them (an earlier 9-feature experiment) accuracy was 0.988.

### Why this model was used
A Random Forest is a standard, fast, explainable baseline for tabular intrusion data and trains in seconds without a GPU.
No comparison against other algorithms was run, so "best model" must not be claimed.

### Recommended next steps (not done)
- Train on simulator-generated, independently labelled scenarios (documented as synthetic) or map the simulator to the flow scales,
  then re-measure the scenario table; add per-class confidence intervals and a time/group-aware split.

## Cost forecaster — limits
- A straight-line fit on daily totals; it cannot model seasonality. With fewer than 2 days of data it falls back to the average (flat). The ±1.5 σ band is a heuristic range, not a statistical prediction interval.
- The cost history is itself simulated (cost records are produced by the simulator), so the forecast demonstrates the technique, not real billing accuracy.
- No backtest has been run: the available history is too short for a meaningful one. Do not quote an accuracy figure.

## Wording rules for report/video
- Say "rule-based" for policies, wastage and the help assistant; "statistical simulation" for the Data Generator; "Random Forest trained on a CICIDS2017 subset" for threat classification, together with the limitations above.
- Do not call the Help Assistant, policy compiler or wastage rules "AI" or "machine learning".
