import pandas as pd

from app.ai_models.threat_detector import THREAT_LABELS, ThreatDetector
from app.data_sources.real_datasets import dataset_catalog

LABEL_DERIVED = {'cpu_utilization', 'memory_utilization', 'auth_failures'}


def test_deployed_features_match_training_and_exclude_label_derived_columns():
    detector = ThreatDetector()
    frame = dataset_catalog.load_security_frame()
    assert detector.backend == 'sklearn' and detector.version.startswith('rf-')
    assert set(detector.feature_columns) <= set(frame.columns)  # every input exists in the training data
    assert not LABEL_DERIVED & set(detector.feature_columns)
    assert not LABEL_DERIVED & set(frame.columns)  # the training frame no longer carries them


def test_no_feature_is_a_deterministic_function_of_the_label():
    frame = dataset_catalog.load_security_frame()
    for column in ThreatDetector().feature_columns:
        # a leaked column has (almost) one value per class; a real signal varies inside each class
        distinct_per_class = frame.groupby('label')[column].nunique()
        assert distinct_per_class.max() > 4, f'{column} looks label-derived'


def test_training_is_reproducible_and_versioned():
    a, b = ThreatDetector(), ThreatDetector()
    row = {c: 100.0 for c in a.feature_columns}
    assert a.version == b.version  # same data + features -> same version id
    assert a.real_time_monitor(row)['threat_type'] == b.real_time_monitor(row)['threat_type']
    by_source = a.model_info['rows_by_source']
    assert by_source['cicids2017'] == len(dataset_catalog.load_security_frame())
    assert a.model_info['training_rows'] == by_source['cicids2017'] + by_source['simulator_synthetic']
    assert set(a.model_info['class_counts']) == set(THREAT_LABELS.values())


def test_heuristic_fallback_is_labelled_when_no_data():
    detector = ThreatDetector()
    detector.backend, detector.model, detector.version = 'heuristic', None, 'heuristic'  # as when no dataset is staged
    result = detector.real_time_monitor({'requests_per_minute': 9000})
    assert result['source'] == 'heuristic' and result['is_threat']


def test_model_info_endpoint_reports_the_loaded_model(client, world):
    info = client.get('/api/security/model-info', headers=world['viewer']).get_json()
    assert info['backend'] == 'sklearn' and info['version'].startswith('rf-') and 'features' in info
    assert client.get('/api/security/model-info').status_code in (401, 422)


# ── Simulator-domain evidence (ML_EVIDENCE.md, limitation 1 addressed) ─────────

def test_attack_scenarios_supply_every_model_feature():
    from app.ai_models.simulator_dataset import build_attack_scenario
    from app.ai_models.threat_detector import threat_detector
    for attack in ('ddos', 'port_scan', 'brute_force'):
        for row in build_attack_scenario(attack, 'medium'):
            missing = [c for c in threat_detector.feature_columns if c not in row]
            assert missing == [], (attack, missing)
            assert row['network_in_mbps'] > 0 and row['disk_read_iops'] > 0


def test_live_simulator_uses_the_same_telemetry_formula():
    import random
    from types import SimpleNamespace
    from app.ai_models.simulator_dataset import vm_traffic_metrics
    from app.services.resource_simulator import ResourceSimulator
    vm = SimpleNamespace(cpu_utilization=40, memory_utilization=50, network_in_mbps=60, network_out_mbps=40,
                         disk_read_iops=100, disk_write_iops=50)
    simulator = ResourceSimulator()
    simulator._rng = random.Random(7)
    expected = vm_traffic_metrics(vm, random.Random(7))
    assert simulator._build_vm_traffic_metrics(vm) == expected


def test_deployed_detector_recognises_ui_attack_scenarios():
    from app.ai_models.simulator_dataset import build_attack_scenario
    from app.ai_models.threat_detector import threat_detector
    for attack in ('ddos', 'port_scan', 'brute_force'):
        for intensity in ('low', 'medium', 'high'):
            preds = [threat_detector.real_time_monitor(r)['threat_type'] for r in build_attack_scenario(attack, intensity)]
            assert preds.count(attack) >= 2, (attack, intensity, preds)


def test_training_and_evaluation_simulator_data_do_not_overlap():
    from app.ai_models.simulator_dataset import TRAIN_SEED, simulator_frame
    from app.ai_models.threat_detector import threat_detector
    cols = threat_detector.feature_columns
    train, held_out = simulator_frame(TRAIN_SEED), simulator_frame(2000)
    rows = lambda f: set(map(tuple, f[cols].round(6).to_numpy()))  # noqa: E731
    assert not rows(train) & rows(held_out)
    assert simulator_frame(TRAIN_SEED).equals(train)  # reproducible
    assert threat_detector.model_info['rows_by_source']['simulator_synthetic'] == len(train)


def test_simulated_attack_confidence_comes_from_the_model(client, world):
    from app.models.security import ThreatDetection
    resp = client.post('/api/security/simulate-attack', json={'organization_id': world['org_a'], 'attack_type': 'ddos'},
                       headers=world['owner'])
    assert resp.status_code == 201
    threat = ThreatDetection.query.get(resp.get_json()['threat_id'])
    assert threat.status == 'active' and threat.model_version != 'simulation'
    assert resp.get_json()['detections'] >= 2 and threat.confidence_score >= 0.75
