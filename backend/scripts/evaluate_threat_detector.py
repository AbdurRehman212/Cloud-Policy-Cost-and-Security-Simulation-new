"""Measure the threat detector honestly and reproducibly.

Run from backend/:  python scripts/evaluate_threat_detector.py

Protocol (seed 42, stratified): 60 % train / 20 % validation / 20 % test.
  * validation is used only to pick nothing automatically; it is reported to show the train/val gap
  * the test split is touched once, after the configuration is fixed
Reports accuracy, macro-F1, per-class precision/recall/F1, the confusion matrix and the benign
false-positive rate on both splits, then how the deployed model scores the simulator's own attack
scenarios. Nothing is hard-coded: every number is computed by this run.
"""
import os
import sys

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support
from sklearn.model_selection import train_test_split

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ai_models.threat_detector import THREAT_LABELS, ThreatDetector  # noqa: E402
from app.data_sources.real_datasets import dataset_catalog  # noqa: E402

SEED = 42
NAMES = [THREAT_LABELS[i] for i in range(4)]


def forest():
    return RandomForestClassifier(n_estimators=64, max_depth=8, min_samples_leaf=2,
                                  class_weight='balanced_subsample', random_state=SEED, n_jobs=1)


def report(title, y_true, y_pred):
    labels = list(range(4))
    p, r, f, support = precision_recall_fscore_support(y_true, y_pred, labels=labels, zero_division=0)
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    benign = cm[0].sum()
    fpr = (benign - cm[0, 0]) / benign if benign else float('nan')
    print(f'\n{title}: n={len(y_true)} accuracy {accuracy_score(y_true, y_pred):.3f} '
          f'macro-F1 {f1_score(y_true, y_pred, average="macro", zero_division=0):.3f} benign false-positive rate {fpr:.3f}')
    print(f'  {"class":<12}{"precision":>10}{"recall":>8}{"F1":>8}{"support":>9}')
    for i, name in enumerate(NAMES):
        print(f'  {name:<12}{p[i]:>10.3f}{r[i]:>8.3f}{f[i]:>8.3f}{support[i]:>9}')
    print('  confusion matrix (rows = true, cols = predicted: ' + ', '.join(NAMES) + ')')
    for name, row in zip(NAMES, cm):
        print(f'    {name:<12}{row.tolist()}')


detector = ThreatDetector()
frame = dataset_catalog.load_security_frame()
cols = detector.feature_columns
print(f'Model version: {detector.version} | backend: {detector.backend}')
print(f'Features ({len(cols)}): {", ".join(cols)}')
print(f'Dataset rows: {len(frame)}; class counts: {frame["label"].value_counts().sort_index().to_dict()}')

X, y = frame[cols].fillna(0.0).astype(float), frame['label'].astype(int)
X_tr, X_rest, y_tr, y_rest = train_test_split(X, y, test_size=0.4, stratify=y, random_state=SEED)
X_val, X_te, y_val, y_te = train_test_split(X_rest, y_rest, test_size=0.5, stratify=y_rest, random_state=SEED)
print(f'Split: train {len(X_tr)} / validation {len(X_val)} / test {len(X_te)}')

model = forest().fit(X_tr, y_tr)
report('VALIDATION', y_val, model.predict(X_val))
report('TEST', y_te, model.predict(X_te))

# Stability: repeat with different split seeds to show how fragile the rare classes are.
scores = []
for seed in range(5):
    a, b, c, d = train_test_split(X, y, test_size=0.2, stratify=y, random_state=seed)
    scores.append(f1_score(d, forest().fit(a, c).predict(b), average='macro', zero_division=0))
print(f'\nMacro-F1 over 5 different 80/20 splits: mean {np.mean(scores):.3f}, min {min(scores):.3f}, max {max(scores):.3f}')

# Simulator attack scenarios scored by the deployed model
from app import create_app  # noqa: E402

create_app('testing')
from app.routes.security import build_attack_scenario  # noqa: E402

print('\nSimulator attack scenarios scored by the deployed model (rows flagged as the intended type / rows):')
for attack in ('ddos', 'port_scan', 'brute_force'):
    for intensity in ('low', 'high'):
        rows = build_attack_scenario(attack, intensity)
        preds = [detector.real_time_monitor(r)['threat_type'] for r in rows]
        print(f'  {attack:<12} {intensity:<5} -> {sum(p == attack for p in preds)}/{len(rows)}  predicted: {sorted(set(preds))}')

# Normal simulator telemetry (Data Generator + traffic model) -> how often is it flagged?
from collections import Counter  # noqa: E402
from datetime import datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from app.ai_models.data_generator import SyntheticDataGenerator  # noqa: E402
from app.services.resource_simulator import ResourceSimulator  # noqa: E402

generator, simulator, counts, total = SyntheticDataGenerator(seed=1), ResourceSimulator(), Counter(), 0
for cpu in (20, 40, 60, 75):
    vm = SimpleNamespace(instance_type='t2.small', vcpu=1, memory_gb=2, memory_utilization=40.0, cpu_utilization=cpu,
                         network_in_mbps=0, network_out_mbps=0, requests_per_second=100, disk_read_iops=0, disk_write_iops=0)
    for hour in (3, 12, 20):
        for _ in range(50):
            sample = generator.generate_vm_metrics(vm, datetime(2026, 10, 28, hour))
            vm.__dict__.update(sample)
            row = {**sample, **simulator._build_vm_traffic_metrics(vm)}
            counts[detector.real_time_monitor(row)['threat_type']] += 1
            total += 1
print(f'\nNormal simulator telemetry ({total} rows from the Data Generator) classified as: {dict(counts)}')
print('(the simulator\'s own "normal" is not independent ground truth)')
