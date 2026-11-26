# AI/ML Evidence Note (Modules 1–12)

Everything below was read from the code or measured by running it. Re-run the measurement with
`cd backend && python scripts/evaluate_threat_detector.py` (prints all numbers; nothing is hard-coded).

## Summary

| Component | What it really is | Trained? | Evaluated? |
|---|---|---|---|
| Threat Detector (M6) | scikit-learn `RandomForestClassifier` (64 trees, depth 8) on 10 features; falls back to a centroid classifier, then to fixed thresholds, if sklearn/data are unavailable | Yes, at start-up, on a 3,000-row CICIDS2017 subset **plus 1,200 seeded synthetic simulator rows** (training seed only) | Yes: CICIDS 60/20/20 split + held-out simulator seeds + out-of-band intensities, scripted (`scripts/evaluate_threat_detector.py`) |
| Remediation Agent (M10) | Deterministic rules: each recommendation carries the rule that produced it; low-confidence detections (< 0.75) go to human review | No — rule-based (an untrained "Q-table" that never affected ranking was removed) | Chapter 6 UT-50..54 and 23 workflow tests (`tests/test_remediation.py`) |
| Cost Forecaster (M8) | Linear trend (`LinearRegression`, or `numpy.polyfit`) on daily total cost; "range" = prediction ± 1.5 × residual std | Fit per request on the organization's own cost history | No (see limits) |
| Wastage / optimization (M8) | Explicit rules: IDLE (CPU < 10 %), UNDERUTILIZED (CPU < 30 % and memory < 40 %) | No — rule-based, not ML | Unit tests (`tests/test_cost.py`) |
| Policy Engine (M7) | Rule compiler: `key=value` rules plus a small set of fixed natural-language patterns | No — rule-based, not ML or an LLM | Unit tests (`tests/test_governance.py`) |
| Data Generator (M3) | Seeded statistical sampling (normal noise, exponential spikes, business-hour factor) around a baseline taken from the Alibaba trace subset | No — simulation, not a learned model | `tests/test_data_generator.py` |
| Help Assistant | Keyword matching against fixed answers (`routes/assistant.py`) | No — no LLM | — |

## Datasets (from `backend/data/README.md` and the files)
- `cicids_subset.csv` — 3,000 flows from CICIDS2017: 2,467 normal, 421 DDoS/DoS/bots, 96 port scan, 16 brute force/web attacks.
- `dataset-3k-final.csv` — 3,098 rows of Alibaba Cluster Trace 2018 utilisation, used as the baseline for the Data Generator and cost history.

## Threat detector — measured results (Modules 10–12 update, model `rf-bb6037ab03`, seed 42)

**What changed and why.** Limitation 1 below (the detector classified every simulator attack as normal) had two causes:
(1) a **train/serve feature mismatch** — attack scenarios sent only 6 of the 10 model features, so `disk_*_iops` and
`network_*_mbps` reached the model as 0; (2) a **domain gap** — the model had only seen CICIDS flows rescaled to "VM
metrics". Fixes: scenarios now emit all ten features with the same derivations as live telemetry (one shared function,
`ai_models/simulator_dataset.py`), and training adds labelled *synthetic* simulator telemetry generated with a training
seed (1000; attack intensity scale 0.8–2.4, which covers every UI intensity).

**Protocol.** Configuration A = previous model (CICIDS only); B = deployed (CICIDS train split + simulator train rows).
Evaluated on: the CICIDS test split (stratified 60/20/20, unchanged); simulator rows from a **different seed** (2000);
and simulator rows from another seed (3000) whose attacks are **stronger than anything trained on** (scale 2.4–3.2).
Exact-duplicate check: 0 rows shared between simulator train and either test set (24 exact duplicates exist *inside* the
CICIDS subset between its own train and test splits — evidence for limitation 3).

| Macro-F1 | CICIDS test (n=600) | Simulator, held-out seed (n=1,200) | Simulator, out-of-band intensity (n=1,200) |
|---|---|---|---|
| A CICIDS-only (previous) | 0.902 | 0.167 (everything predicted normal) | 0.167 |
| **B CICIDS + simulator (deployed)** | **0.939** | **1.000** | **0.935** |

B over 5 further seeds: CICIDS macro-F1 mean 0.944 (min 0.922); out-of-band simulator macro-F1 mean 0.965 (min 0.934).

B, CICIDS test per class (precision / recall / F1 / support): normal 0.992/0.994/0.993/494 · ddos 0.964/0.964/0.964/84 ·
port_scan 1.000/1.000/1.000/19 · brute_force 1.000/0.667/0.800/**3**. Benign false-positive rate 0.006.
Confusion matrix (rows true; normal, ddos, port_scan, brute_force): [491,3,0,0] · [3,81,0,0] · [0,0,19,0] · [1,0,0,2].

B, out-of-band simulator test: normal 600/600 correct (false-positive rate 0.000); ddos recall 1.000; port_scan recall
0.865 (27 → ddos); brute_force recall 0.875 (24 → port_scan, 1 → ddos). Errors grow as intensity leaves the training range.

Deterministic Simulate-Attack scenarios (the rows the UI injects): ddos, port_scan and brute_force at low/medium/high are
all recognised 3/3 by the deployed model. These rows are close to the training templates, so this is a consistency check,
**not** independent evidence. Simulate Attack now stores the detector's agreement score as the threat confidence (it used
to store a fixed 0.95), so a weak detection is routed to human review by the Remediation Agent.

**How to read the simulator numbers.** All simulator rows are synthetic: the generator decides the label. In-band 1.000
mainly shows that the generator's classes are well separated, not that real attacks would be caught. The meaningful
simulator figure is the out-of-band result (0.935), which tests generalisation beyond the trained intensities.

### Superseded: CICIDS-only results (model `rf-863ed0be8a`, Modules 1–9)

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
Model version = hash of the exact training data plus feature list (now `rf-bb6037ab03`; previously `rf-863ed0be8a`),
stored on each detected threat (`model_version`) and returned by `GET /api/security/model-info` (algorithm, features,
training rows, rows by source, class counts, scikit-learn version, training time). The running backend trains at start-up
from `backend/data/cicids_subset.csv` plus the seeded simulator rows (identical every start); no model file is persisted. If the dataset is missing it falls back to labelled fixed thresholds (`source: heuristic`).

### Limitations that remain (state them in the report, video and viva)
1. **Addressed in the Modules 10–12 update (see above), with a caveat.** The CICIDS-only model detected 0/3 rows of every
   simulator attack. The deployed model now detects them, but its simulator evidence comes from synthetic data produced by
   the same templates; it shows the detector works *inside this simulator*, not on real traffic.
2. Threats created by Simulate Attack before this update carry model version `simulation` and show "Simulated (no model
   score)"; new ones carry the detector version and its agreement score and are tagged "simulated".
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
- Validate on attack traffic not produced by these templates (e.g. a second public dataset mapped through the same feature
  derivations); add per-class confidence intervals, probability calibration and a time/group-aware CICIDS split.

## Cost forecaster — limits
- A straight-line fit on daily totals; it cannot model seasonality. With fewer than 2 days of data it falls back to the average (flat). The ±1.5 σ band is a heuristic range, not a statistical prediction interval.
- The cost history is itself simulated (cost records are produced by the simulator), so the forecast demonstrates the technique, not real billing accuracy.
- No backtest has been run: the available history is too short for a meaningful one. Do not quote an accuracy figure.

## Wording rules for report/video
- Say "rule-based" for policies, wastage and the help assistant; "statistical simulation" for the Data Generator; "Random Forest trained on a CICIDS2017 subset" for threat classification, together with the limitations above.
- Do not call the Help Assistant, policy compiler or wastage rules "AI" or "machine learning".
