from datetime import datetime
from statistics import mean
from types import SimpleNamespace

import pytest

from app.ai_models.data_generator import SyntheticDataGenerator

NOON, NIGHT = datetime(2026, 10, 28, 12), datetime(2026, 10, 28, 3)


def vm(instance_type='t2.small', vcpu=1, memory_gb=2, memory_utilization=40.0):
    return SimpleNamespace(instance_type=instance_type, vcpu=vcpu, memory_gb=memory_gb, memory_utilization=memory_utilization)


def db():
    return SimpleNamespace(instance_class='db.t2.small', allocated_storage_gb=20, free_storage_space=15.0)


@pytest.fixture(scope='module')
def gen_cls():
    return SyntheticDataGenerator


def series(gen, n=300, moment=NOON, **kw):
    return [gen.generate_vm_metrics(vm(**kw), moment) for _ in range(n)]


def test_same_seed_is_reproducible_and_different_seed_differs(gen_cls):  # M3 determinism
    a = [gen_cls(seed=7).generate_vm_metrics(vm(), NOON) for _ in range(1)]
    b = [gen_cls(seed=7).generate_vm_metrics(vm(), NOON) for _ in range(1)]
    c = [gen_cls(seed=8).generate_vm_metrics(vm(), NOON) for _ in range(1)]
    assert a == b and a != c


def test_vm_metrics_are_bounded_and_complete(gen_cls):
    rows = series(gen_cls(seed=1))
    expected = {'cpu_utilization', 'memory_utilization', 'disk_read_iops', 'disk_write_iops', 'network_in_mbps', 'network_out_mbps'}
    for r in rows:
        assert set(r) == expected
        assert 0 <= r['cpu_utilization'] <= 100 and 0 <= r['memory_utilization'] <= 100
        assert all(v >= 0 for v in r.values())
    assert len({r['cpu_utilization'] for r in rows}) > 50  # genuinely varying, not constant


def test_business_hours_load_exceeds_night_load(gen_cls):
    gen = gen_cls(seed=2)
    assert mean(r['cpu_utilization'] for r in series(gen, moment=NOON)) > mean(r['cpu_utilization'] for r in series(gen, moment=NIGHT))


def test_baseline_comes_from_dataset_not_constants(gen_cls):
    gen = gen_cls(seed=3)
    assert not gen.finops_frame.empty or not gen.core_frame.empty
    assert 0 < gen.baseline['cpu_mean'] < 100
    observed = mean(r['cpu_utilization'] for r in series(gen, n=500))
    assert observed > 0


def test_database_metrics_and_cost_estimate(gen_cls):
    gen = gen_cls(seed=4)
    d = gen.generate_database_metrics(db(), NOON)
    assert 0 <= d['cpu_utilization'] <= 100 and isinstance(d['database_connections'], int) and d['database_connections'] >= 0
    assert 0 <= d['free_storage_space'] <= 15.0
    low = gen.generate_cost_estimate({'cpu_utilization': 10, 'memory_utilization': 10})
    high = gen.generate_cost_estimate({'cpu_utilization': 90, 'memory_utilization': 90})
    assert high > low > 0


def test_summarize_history_shapes_chart_series(gen_cls):
    out = gen_cls(seed=5).summarize_history([{'label': 'a', 'cpu': '12.345', 'memory': None, 'cost': 1.234}])
    assert out == [{'name': 'a', 'cpu': 12.35, 'memory': 0.0, 'cost': 1.23}]
