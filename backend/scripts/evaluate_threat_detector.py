"""Measure the threat detector honestly.

Run from backend/:  python scripts/evaluate_threat_detector.py

Reports, on the bundled CICIDS2017 subset (data/cicids_subset.csv):
  A. the deployed 13-feature model on a stratified hold-out split
  B. the same model with the features that are derived from the class label removed
  C. how the deployed model classifies the simulator's own attack scenarios
No numbers are hard-coded: everything printed is computed by this run.
"""
import os
import sys

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, recall_score
from sklearn.model_selection import train_test_split

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ai_models.threat_detector import THREAT_LABELS, ThreatDetector  # noqa: E402
from app.data_sources.real_datasets import dataset_catalog  # noqa: E402

# Built in _derive_security_frame_from_cicids from constants keyed on the class label
# (or on the attack name), so they leak the answer into training and are not real signals.
LABEL_DERIVED = ['error_rate', 'cpu_utilization', 'memory_utilization', 'auth_failures']
SEED = 42


def forest():
    return RandomForestClassifier(n_estimators=64, max_depth=8, min_samples_leaf=2,
                                  class_weight='balanced_subsample', random_state=SEED, n_jobs=1)


def evaluate(frame, columns):
    X, y = frame[columns].fillna(0.0).astype(float), frame['label'].astype(int)
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, stratify=y, random_state=SEED)
    pred = forest().fit(X_tr, y_tr).predict(X_te)
    return {
        'rows_train': len(X_tr), 'rows_test': len(X_te),
        'accuracy': accuracy_score(y_te, pred),
        'macro_f1': f1_score(y_te, pred, average='macro'),
        'recall': dict(zip((THREAT_LABELS[i] for i in sorted(y.unique())),
                           recall_score(y_te, pred, average=None, labels=sorted(y.unique())))),
    }


def show(title, r):
    print(f'\n{title}\n  train/test rows: {r["rows_train"]}/{r["rows_test"]}')
    print(f'  accuracy {r["accuracy"]:.3f} | macro-F1 {r["macro_f1"]:.3f}')
    print('  per-class recall: ' + ', '.join(f'{k} {v:.3f}' for k, v in r['recall'].items()))


detector = ThreatDetector()
frame = dataset_catalog.load_security_frame()
print(f'Dataset rows: {len(frame)}; class counts: {frame["label"].value_counts().sort_index().to_dict()}')
print(f'Deployed backend: {detector.backend}')

all_cols = detector.feature_columns
clean_cols = [c for c in all_cols if c not in LABEL_DERIVED]
show('A. deployed features (13), hold-out split', evaluate(frame, all_cols))
show(f'B. without label-derived features ({", ".join(LABEL_DERIVED)}) -> {len(clean_cols)} features', evaluate(frame, clean_cols))

# C. simulator attack scenarios scored by the deployed model
from app import create_app  # noqa: E402

create_app('testing')
from app.routes.security import build_attack_scenario  # noqa: E402

print('\nC. simulator attack scenarios scored by the deployed model (rows flagged as the intended type / rows):')
for attack in ('ddos', 'port_scan', 'brute_force'):
    for intensity in ('low', 'high'):
        rows = build_attack_scenario(attack, intensity)
        preds = [detector.real_time_monitor(r)['threat_type'] for r in rows]
        print(f'  {attack:<12} {intensity:<5} -> {sum(p == attack for p in preds)}/{len(rows)}  predicted: {sorted(set(preds))}')
