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
    assert a.model_info['training_rows'] == len(dataset_catalog.load_security_frame())
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
