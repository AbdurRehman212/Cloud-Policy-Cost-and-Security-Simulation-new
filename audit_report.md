# Cloud Simulation System Audit

## 1. What is correct (The Backend is Solid)

* **Causal Logic & DES Engine**: 
  The core math in `des_engine.py` is logically sound. `VMDESSimulator` accurately models an M/M/c queue. It correctly orders `SERVICE_COMPLETE` before `REQUEST_ARRIVAL` within the same tick, ensuring latency is emergent from the actual queue depth rather than formulaic. 
* **Target-Tracking Autoscaling**: 
  `control_plane.py` perfectly implements AWS-style scaling. It dynamically computes `target_bpi = SLO / avg_service_time` and scales up/down proportionally based on `queue_total_ms`. Scaling actually executes DB operations (`_create_autoscale_vm` and `_terminate_autoscale_vm`), adding or removing tangible VM records.
* **API Layer Performance**: 
  Thanks to recent fixes, `/api/dashboard/summary` accurately uses `_snapshot_cache` populated by the background `run_control_plane_loop()`. It correctly returns rich simulation data (`bpi`, `capacity`, `queue_total_ms`, `latency_avg_ms`, `dropped_requests_total`) without blocking. Response times are well under 100ms.

## 2. What is still wrong (The Frontend is a Tangled Mess of Fake Data)

* **Data Flow is Compromised (Fake Data)**: 
  The frontend `Dashboard.jsx` relies heavily on `fetchSimulationDashboard()` from `simulationApi.js`, which calls `/api/simulation/dashboard`. These routes point to `simulation_engine.py`, which is an older, purely **synthetic/fake number generator** (using `numpy` and `dataset_loader` with hardcoded sine waves/noise). The real DES engine metrics are largely ignored.
* **UI Mismatches & Placeholders**:
  The dashboard has blatant UI rendering bugs. For instance, the **"Security Status"** KPI card literally displays `peaks.cpu_peak` (a fake CPU value) with the subtitle `Org memory peak`.
* **Chart Data is Fake**:
  The main "Organization-Wide Resource Trends" chart runs off `dashboard.metrics`, which is populated by the fake `simulation_engine.py` or the `resource_update` socket event (which itself uses `generate_metrics()` fake data).
* **Competing Socket Events**:
  The frontend listens to `dashboard_update` (which sends real cached `cpu_avg`), but also merges it with `resource_update` and `/api/simulation` REST calls, causing a confusing mix of real and fake telemetry.

## 3. What is missing (Visibility into Causal Logic)

* **No Visibility into Core Simulation Metrics**:
  The frontend completely fails to display the actual cloud mechanics. Even though the backend computes them perfectly, the dashboard UI hides:
  * Queue depth (`queue_total_ms`)
  * Average latency / p95 latency
  * Dropped requests / Overload status
  * Backlog Per Instance (BPI) vs Target BPI
  * Current Capacity vs Desired Capacity
* **No Visual Proof of Autoscaling**:
  Because BPI and Queue aren't shown, the user has no visual evidence that the causal chain (Workload → Queue → Latency → BPI → Scaling) is happening, even though the backend executes it flawlessly.

## 4. Priority Fixes (High → Low)

1. **[HIGH] Refactor Dashboard.jsx to use ONLY `/api/dashboard/summary` (Real Data)**:
   Remove all dependencies on `simulationApi.js` and `fetchSimulationDashboard()`. The dashboard should only read from the real `reduxSummary` provided by the control plane.
2. **[HIGH] Replace Fake KPI Cards with Real Cloud Metrics**:
   Fix the "Security Status" typo. Add new KPI cards specifically for the DES engine: **Queue Depth**, **P95 Latency**, **Dropped Requests**, and **Backlog per Instance (BPI)**. 
3. **[MEDIUM] Purge the Fake Simulation Engine**:
   Delete `simulation_routes.py` and `simulation_engine.py` entirely. Update `resources.py` (`_resource_update_loop`) to stop using `generate_metrics()` and instead rely strictly on the `resource_simulator.py` DES output.
4. **[LOW] Fix Chart Data Sources**:
   Update the Recharts area chart in `Dashboard.jsx` to map the `utilization_trend` array returned by `/api/dashboard/summary`, rather than the fake synthetic arrays.
