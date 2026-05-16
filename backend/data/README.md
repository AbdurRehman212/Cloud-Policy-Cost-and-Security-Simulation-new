# Real Dataset Staging

This project is configured to use **real public datasets only**.

Do not place synthetic or fabricated data here.

## Recommended datasets

- FinOps and utilization: Alibaba Cluster Trace v2018
- Security / threat detection: `cicids_subset.csv` (lightweight CICIDS2017 subset)
- Simulator core workload behavior: Alibaba Cluster Trace v2018

## Expected folder layout

```text
backend/data/
  finops/
    *.csv, *.tsv, *.json, *.jsonl
  cicids_subset.csv

If you need to regenerate the subset from the full CICIDS2017 export, use
`backend/scripts/reduce_cicids.py`.
```

## Staging schema expected by the app

The app reads preprocessed real dataset exports that should include these columns when available:

### FinOps / utilization

- `date`
- `total_cost`
- `cpu_utilization_avg`
- `memory_utilization_avg`
- `provisioned_resources`
- `idle_resources`

### Security / threat detection

- `label`
- `requests_per_minute`
- `avg_latency_ms`
- `error_rate`
- `bytes_in`
- `bytes_out`
- `active_connections`
- `cpu_utilization`
- `memory_utilization`
- `disk_read_iops`
- `disk_write_iops`
- `network_in_mbps`
- `network_out_mbps`
- `auth_failures`

If you download the raw public datasets, preprocess them into these staged exports before training the local modules.
