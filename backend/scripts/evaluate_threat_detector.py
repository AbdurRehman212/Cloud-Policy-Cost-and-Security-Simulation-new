"""Measure the threat detector honestly and reproducibly.

Run from backend/:  python scripts/evaluate_threat_detector.py

Two configurations are trained with the same RandomForest settings (seed 42):
  A  CICIDS-only      — the previous deployed model (baseline)
  B  CICIDS + SIM     — the current deployed model: CICIDS train split + synthetic simulator
                        telemetry generated with the TRAINING seed only

Evaluation data (never used for training):
  * CICIDS test split  — stratified 60/20/20 split of the CICIDS subset, test touched once
  * SIM in-band        — simulator telemetry, different seed (2000), same intensity band as training
  * SIM out-of-band    — different seed (3000) AND attack intensities above anything trained on
                         (scale 2.4–3.2 vs 0.8–2.4): checks extrapolation, not memorisation
  * the deterministic Simulate-Attack scenarios shown in the UI (near the training templates,
    so they are reported but are not independent evidence)

Nothing is hard-coded: every number is computed by this run.
"""
import os
import sys
from collections import Counter

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support
from sklearn.model_selection import train_test_split

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ai_models.simulator_dataset import (  # noqa: E402
    INTENSITY_SCALE, TRAIN_BAND, TRAIN_SEED, build_attack_scenario, simulator_frame,
)
from app.ai_models.threat_detector import THREAT_LABELS, ThreatDetector  # noqa: E402
from app.data_sources.real_datasets import dataset_catalog  # noqa: E402

SEED = 42
NAMES = [THREAT_LABELS[i] for i in range(4)]
IN_BAND_SEED, OUT_BAND_SEED, OUT_BAND = 2000, 3000, (2.4, 3.2)


def forest():
    return RandomForestClassifier(n_estimators=64, max_depth=8, min_samples_leaf=2,
                                  class_weight='balanced_subsample', random_state=SEED, n_jobs=1)


def report(title, y_true, y_pred):
    labels = list(range(4))
    p, r, f, support = precision_recall_fscore_support(y_true, y_pred, labels=labels, zero_division=0)
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    benign = cm[0].sum()
    fpr = (benign - cm[0, 0]) / benign if benign else float('nan')
    macro = f1_score(y_true, y_pred, average='macro', zero_division=0)
    print(f'\n{title}: n={len(y_true)} accuracy {accuracy_score(y_true, y_pred):.3f} '
          f'macro-F1 {macro:.3f} benign false-positive rate {fpr:.3f}')
    print(f'  {"class":<12}{"precision":>10}{"recall":>8}{"F1":>8}{"support":>9}')
    for i, name in enumerate(NAMES):
        print(f'  {name:<12}{p[i]:>10.3f}{r[i]:>8.3f}{f[i]:>8.3f}{support[i]:>9}')
    print('  confusion matrix (rows = true, cols = predicted: ' + ', '.join(NAMES) + ')')
    for name, row in zip(NAMES, cm):
        print(f'    {name:<12}{row.tolist()}')
    return macro


detector = ThreatDetector()  # the deployed configuration (B)
cols = detector.feature_columns
print(f'Deployed model version: {detector.version} | backend: {detector.backend}')
print(f'Features ({len(cols)}): {", ".join(cols)}')
print(f'Deployed training rows by source: {detector.model_info.get("rows_by_source")}')

cicids = dataset_catalog.load_security_frame()
X, y = cicids[cols].fillna(0.0).astype(float), cicids['label'].astype(int)
X_tr, X_rest, y_tr, y_rest = train_test_split(X, y, test_size=0.4, stratify=y, random_state=SEED)
X_val, X_te, y_val, y_te = train_test_split(X_rest, y_rest, test_size=0.5, stratify=y_rest, random_state=SEED)
print(f'CICIDS rows {len(cicids)}; split train {len(X_tr)} / validation {len(X_val)} / test {len(X_te)}')

sim_train = simulator_frame(TRAIN_SEED, band=TRAIN_BAND)
sim_in = simulator_frame(IN_BAND_SEED, band=TRAIN_BAND)
sim_out = simulator_frame(OUT_BAND_SEED, band=OUT_BAND)
print(f'SIM train seed {TRAIN_SEED} band {TRAIN_BAND}: {len(sim_train)} rows {sim_train["label"].value_counts().sort_index().to_dict()}')
print(f'SIM in-band test seed {IN_BAND_SEED}: {len(sim_in)} rows; out-of-band test seed {OUT_BAND_SEED} band {OUT_BAND}: {len(sim_out)} rows')

# Leakage checks: evaluation rows must not appear in training.
key = lambda f: set(map(tuple, f[cols].round(6).to_numpy()))  # noqa: E731
print(f'Exact duplicate rows train∩in-band: {len(key(sim_train) & key(sim_in))}, '
      f'train∩out-of-band: {len(key(sim_train) & key(sim_out))}, '
      f'CICIDS-train∩CICIDS-test: {len(set(map(tuple, X_tr.round(6).to_numpy())) & set(map(tuple, X_te.round(6).to_numpy())))}')

model_a = forest().fit(X_tr, y_tr)
model_b = forest().fit(pd.concat([X_tr, sim_train[cols].astype(float)]), pd.concat([y_tr, sim_train['label']]))

results = {}
for name, model in (('A CICIDS-only (previous)', model_a), ('B CICIDS + SIM (deployed)', model_b)):
    print('\n' + '=' * 70 + f'\n{name}')
    report('CICIDS VALIDATION', y_val, model.predict(X_val))
    results[(name, 'cicids')] = report('CICIDS TEST', y_te, model.predict(X_te))
    results[(name, 'in')] = report('SIM IN-BAND TEST', sim_in['label'], model.predict(sim_in[cols].astype(float)))
    results[(name, 'out')] = report('SIM OUT-OF-BAND TEST', sim_out['label'], model.predict(sim_out[cols].astype(float)))

print('\n' + '=' * 70 + '\nSummary (macro-F1)')
print(f'  {"configuration":<28}{"CICIDS test":>12}{"SIM in-band":>13}{"SIM out-band":>14}')
for name in ('A CICIDS-only (previous)', 'B CICIDS + SIM (deployed)'):
    print(f'  {name:<28}{results[(name, "cicids")]:>12.3f}{results[(name, "in")]:>13.3f}{results[(name, "out")]:>14.3f}')

# Stability of configuration B over different CICIDS split seeds and simulator seeds.
scores = []
for seed in range(5):
    a, b, c, d = train_test_split(X, y, test_size=0.2, stratify=y, random_state=seed)
    train_sim = simulator_frame(TRAIN_SEED + seed + 1, band=TRAIN_BAND)
    test_sim = simulator_frame(OUT_BAND_SEED + seed + 1, band=OUT_BAND)
    m = forest().fit(pd.concat([a, train_sim[cols].astype(float)]), pd.concat([c, train_sim['label']]))
    scores.append((f1_score(d, m.predict(b), average='macro', zero_division=0),
                   f1_score(test_sim['label'], m.predict(test_sim[cols].astype(float)), average='macro', zero_division=0)))
cic, sim = zip(*scores)
print(f'\nB over 5 seeds — CICIDS macro-F1 mean {np.mean(cic):.3f} (min {min(cic):.3f}); '
      f'SIM out-of-band macro-F1 mean {np.mean(sim):.3f} (min {min(sim):.3f})')

print('\nDeterministic Simulate-Attack scenarios scored by the DEPLOYED model (intended type / rows):')
for attack in ('ddos', 'port_scan', 'brute_force'):
    for intensity in INTENSITY_SCALE:
        rows = build_attack_scenario(attack, intensity)
        preds = [detector.real_time_monitor(r) for r in rows]
        hits = [p for p in preds if p['threat_type'] == attack]
        conf = np.mean([p['confidence'] for p in hits]) if hits else 0.0
        print(f'  {attack:<12} {intensity:<7} -> {len(hits)}/{len(rows)}  mean confidence {conf:.2f}  '
              f'predicted: {sorted(set(p["threat_type"] for p in preds))}')

normal_eval = sim_out[sim_out['label'] == 0]
counts = Counter(detector.real_time_monitor(r)['threat_type'] for r in normal_eval[cols].to_dict('records'))
print(f'\nHeld-out normal simulator telemetry ({len(normal_eval)} rows, seed {OUT_BAND_SEED}) classified by the deployed model: {dict(counts)}')
print('(all simulator rows are synthetic: labels come from the generator, not independent ground truth)')
