"""Performance test against a running backend on an ISOLATED database (never the real one).

Usage (from backend/):
  PERF_DB_URL=postgresql://<user>:<password>@localhost/cloud_sim_perf PERF_API=http://127.0.0.1:5000/api \
      python scripts/perf_test.py

Acceptance criteria (Chapter 6, Table 6.29):
  ST-19 dashboard summary with 50 VMs < 2 s
  ST-20 100 consecutive resource-list requests (20 VMs) succeed in < 10 s total
  ST-21 cost CSV and PDF over 5,000 cost records, each < 10 s
Also reports p50/p95/p99 per module, throughput and error rate at 1/5/10/20 concurrent users,
backend CPU and memory, and simulation tick times. Stops early if free RAM drops below 1 GB.
"""
import json
import os
import random
import statistics
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import psutil
import requests
from sqlalchemy import create_engine, text

# 127.0.0.1, not localhost: on Windows, Python clients try IPv6 ::1 first and add ~2 s per new connection.
API = os.environ.get('PERF_API', 'http://127.0.0.1:5000/api')
DB_URL = os.environ['PERF_DB_URL']
assert 'cloud_sim_perf' in DB_URL, 'refusing to seed anything but the isolated perf database'
MIN_FREE_RAM = 1.0 * 1024 ** 3
results = {}


def pct(values, p):
    values = sorted(values)
    if not values:
        return None
    k = (len(values) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def summary(times_ms, errors=0):
    return {'n': len(times_ms), 'p50_ms': round(pct(times_ms, 50), 1), 'p95_ms': round(pct(times_ms, 95), 1),
            'p99_ms': round(pct(times_ms, 99), 1), 'max_ms': round(max(times_ms), 1), 'errors': errors}


def timed(session, method, path, **kw):
    t = time.perf_counter()
    r = session.request(method, API + path, timeout=60, **kw)
    return (time.perf_counter() - t) * 1000, r


def free_ram():
    return psutil.virtual_memory().available


def backend_process():
    for c in psutil.net_connections(kind='tcp'):
        if c.laddr and c.laddr.port == int(API.split(':')[2].split('/')[0]) and c.status == 'LISTEN':
            return psutil.Process(c.pid)
    raise RuntimeError('backend not found')


# ── seed ──────────────────────────────────────────────────────────────────────
s = requests.Session()
email = f'perf_{uuid.uuid4().hex[:8]}@example.com'
pw = 'Perf!Passw0rd1'
assert s.post(API + '/auth/register', json={'email': email, 'password': pw, 'first_name': 'Perf', 'last_name': 'User'}).status_code == 201
tok = s.post(API + '/auth/login', json={'email': email, 'password': pw}).json()['data']['access_token']
s.headers['Authorization'] = f'Bearer {tok}'
org50 = s.get(API + '/org/').json()['data']['organizations'][0]['id']
org20 = s.post(API + '/org/', json={'name': f'Perf20 {uuid.uuid4().hex[:4]}'}).json()['data']['organization']['id']

engine = create_engine(DB_URL)
with engine.begin() as conn:
    def add_vms(org, n, prefix):
        for i in range(n):
            cpu = 5.0 if i < 10 else random.uniform(20, 80)  # 10 idle VMs give remediation work
            conn.execute(text(
                "INSERT INTO virtual_machines (organization_id, name, instance_id, instance_type, status, vcpu, memory_gb,"
                " storage_gb, cpu_utilization, memory_utilization, disk_read_iops, disk_write_iops, network_in_mbps,"
                " network_out_mbps, hourly_rate, total_runtime_hours, requests_per_second, workload_pattern, created_at,"
                " launched_at) VALUES (:o, :n, :iid, 't2.small', 'running', 1, 2, 8, :c, 40, 120, 60, 30, 20,"
                " 0.023, 10, 50, 'steady', now(), now())"),  # every column the API would set
                {'o': org, 'n': f'{prefix}-{i}', 'iid': f'i-{prefix}{i:03d}{uuid.uuid4().hex[:6]}', 'c': cpu})
    conn.execute(text('UPDATE organizations SET max_resources = 200 WHERE id IN (:a, :b)'), {'a': org50, 'b': org20})
    add_vms(org50, 50, 'p50')
    add_vms(org20, 20, 'p20')
    today = date.today()
    rows = [{'o': org50, 'r': f'i-p50-{i % 50}', 'd': today - timedelta(days=i % 30), 'h': i % 24,
             'c': round(random.uniform(0.01, 0.5), 4)} for i in range(5000)]
    conn.execute(text("INSERT INTO cost_records (organization_id, resource_id, resource_type, date, hour, compute_cost,"
                      " storage_cost, network_cost, total_cost) VALUES (:o, :r, 'vm', :d, :h, :c, 0, 0, :c)"), rows)
print(f'seeded org {org50}: 50 VMs + 5,000 cost records; org {org20}: 20 VMs')
proc = backend_process()

# ── ST-19 / ST-20 / ST-21 ─────────────────────────────────────────────────────
dash = [timed(s, 'GET', f'/dashboard/summary?organization_id={org50}')[0] for _ in range(20)]
results['ST-19 dashboard summary, 50 VMs'] = {**summary(dash), 'limit_ms': 2000, 'pass': max(dash) < 2000}

t0 = time.perf_counter()
codes = [timed(s, 'GET', f'/resources?organization_id={org20}')[1].status_code for _ in range(100)]
total = time.perf_counter() - t0
results['ST-20 100 consecutive resource lists, 20 VMs'] = {'total_s': round(total, 2), 'all_ok': all(c == 200 for c in codes),
                                                         'limit_s': 10, 'pass': total < 10 and all(c == 200 for c in codes)}
for fmt in ('csv', 'pdf'):
    ms, r = timed(s, 'GET', f'/reports/cost.{fmt}?organization_id={org50}')
    results[f'ST-21 cost {fmt.upper()}, 5,000 records'] = {'ms': round(ms, 1), 'bytes': len(r.content),
                                                            'status': r.status_code, 'limit_ms': 10000,
                                                            'pass': r.status_code == 200 and ms < 10000}

# ── per-module latency (sequential) ───────────────────────────────────────────
def series(name, n, method, path, **kw):
    times, errs = [], 0
    for _ in range(n):
        ms, r = timed(s, method, path, **kw)
        times.append(ms)
        errs += r.status_code >= 400
    results[name] = summary(times, errs)

series('Auth: login (scrypt)', 10, 'POST', '/auth/login', json={'email': email, 'password': pw})
series('M5 resource list (50 VMs)', 30, 'GET', f'/resources?organization_id={org50}')
series('M6 threat detection (/security/analyze)', 30, 'POST', '/security/analyze',
       json={'organization_id': org50, 'requests_per_minute': 1200, 'avg_latency_ms': 60, 'error_rate': 0.01})
series('M6 threat list', 30, 'GET', f'/security/threats?organization_id={org50}')
series('M7 compliance check', 5, 'POST', '/governance/compliance/check', json={'organization_id': org50})
series('M8 cost summary (5,000 records)', 30, 'GET', f'/cost/summary?organization_id={org50}&days=30')
series('M8 cost forecast (30 days)', 30, 'GET', f'/cost/forecast?organization_id={org50}&days=30')
series('M10 remediation issues', 30, 'GET', f'/remediation/issues?organization_id={org50}')
# Threats are not changed by the simulator (idle VMs are: it raises their CPU), so remediation is
# measured on simulated DDoS attacks against 8 VMs: isolate + scale up, verified.
vms = s.get(API + f'/resources/vm?organization_id={org50}').json()['data'][:8]
attack_times, plan_times, exec_times, exec_err = [], [], [], 0
for vm in vms:
    ms, r = timed(s, 'POST', '/security/simulate-attack', json={'organization_id': org50, 'attack_type': 'ddos',
                                                                  'target_resource': vm['instance_id']})
    attack_times.append(ms)
    key = f"threat:{r.json()['threat_id']}"
    plan_times.append(timed(s, 'POST', '/remediation/plan', json={'organization_id': org50, 'issue_key': key})[0])
    ms, r = timed(s, 'POST', '/remediation/execute', json={'organization_id': org50, 'issue_key': key,
                                                             'actions': ['isolate_resource', 'scale_up'], 'approved': True})
    exec_times.append(ms)
    exec_err += r.status_code != 200
results['M6 simulate attack (scored by the detector)'] = summary(attack_times)
results['M10 remediation plan'] = summary(plan_times)
results['M10 remediation execute (verified)'] = summary(exec_times, exec_err)
series('M11 audit trail page (25 events)', 30, 'GET', f'/audit/events?organization_id={org50}&per_page=25')
series('M11 audit trail filtered', 30, 'GET', f'/audit/events?organization_id={org50}&category=remediation')
series('M12 settings', 30, 'GET', '/settings')
series('M12 alert feed', 30, 'GET', f'/settings/alerts?organization_id={org50}')
series('M9 security PDF', 5, 'GET', f'/reports/security.pdf?organization_id={org50}')

# ── concurrency ───────────────────────────────────────────────────────────────
MIX = [f'/dashboard/summary?organization_id={org50}', f'/resources?organization_id={org50}',
       f'/audit/events?organization_id={org50}', f'/cost/summary?organization_id={org50}&days=30',
       f'/remediation/issues?organization_id={org50}', f'/security/threats?organization_id={org50}']
samples, stop = [], threading.Event()


def sampler():
    proc.cpu_percent(None)
    while not stop.is_set():
        time.sleep(0.5)
        samples.append((proc.cpu_percent(None), proc.memory_info().rss / 2 ** 20))


conc = {}
for users in (1, 5, 10, 20):
    if free_ram() < MIN_FREE_RAM:
        conc[users] = 'skipped: free RAM below 1 GB'
        break
    samples.clear(); stop.clear()
    th = threading.Thread(target=sampler, daemon=True); th.start()
    n = 120 if users == 1 else 300
    lock, times, errors = threading.Lock(), [], [0]

    local = threading.local()

    def worker(i):
        if not hasattr(local, 'sess'):  # one keep-alive connection per simulated user, like a browser
            local.sess = requests.Session(); local.sess.headers['Authorization'] = f'Bearer {tok}'
        ms, r = timed(local.sess, 'GET', MIX[i % len(MIX)])
        with lock:
            times.append(ms)
            errors[0] += r.status_code >= 400

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=users) as pool:
        list(pool.map(worker, range(n)))
    wall = time.perf_counter() - t0
    stop.set(); th.join()
    conc[users] = {**summary(times, errors[0]), 'throughput_rps': round(n / wall, 1),
                   'error_rate': round(errors[0] / n, 4),
                   'backend_cpu_avg_pct': round(statistics.mean(c for c, _ in samples), 1) if samples else None,
                   'backend_rss_max_mb': round(max(m for _, m in samples), 1) if samples else None,
                   'free_ram_gb': round(free_ram() / 2 ** 30, 2)}
results['Concurrency (mixed read workload)'] = conc
results['Backend RSS after test (MB)'] = round(proc.memory_info().rss / 2 ** 20, 1)
print(json.dumps(results, indent=1, default=str))
