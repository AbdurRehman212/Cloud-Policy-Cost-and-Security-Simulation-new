import React, { useEffect, useRef, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import {
  ArrowPathIcon,
  BoltIcon,
  BuildingOfficeIcon,
  ChartBarIcon,
  ClockIcon,
  CpuChipIcon,
  CurrencyDollarIcon,
  ServerStackIcon,
  ShieldCheckIcon,
} from "@heroicons/react/24/outline";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  fetchDashboardSummary,
  normalizeDashboardSnapshot,
  updateDashboardState,
} from "../../store/slices/dashboardSlice";
import {
  fetchDatabases,
  fetchVMs,
  upsertVM,
  removeVM,
} from "../../store/slices/resourceSlice";
import { createSocket } from "../../services/api";

const formatPercent = (value, digits = 2) =>
  `${Number(value || 0).toFixed(digits)}%`;

const formatChartTime = (value) => {
  if (!value) return "";
  // Check if value is HH:MM string (backend returns this)
  if (typeof value === "string" && value.includes(":")) return value;
  const d = new Date(value);
  if (isNaN(d.getTime())) return value;
  return d.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
};

const formatCost = (value) => `$${Number(value || 0).toFixed(4)}`;

const formatActivityDetails = (value) => {
  if (!value) return "";
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value)) return value.filter(Boolean).join(", ");
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch (_error) {
      return "";
    }
  }
  return String(value);
};

/* ── Improved StatCard ── */
const StatCard = ({ title, value, subtitle, icon: Icon, accentClass }) => (
  <div className="card group">
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0 flex-1">
        <p className="section-label">{title}</p>
        <p className="mt-2 text-2xl font-bold tabular-nums text-gray-900 dark:text-white tracking-tight">
          {value}
        </p>
        {subtitle && (
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
            {subtitle}
          </p>
        )}
      </div>
      <div className={`shrink-0 rounded-xl p-3 ${accentClass} shadow-sm transition-transform duration-200 group-hover:scale-110`}>
        <Icon className="h-5 w-5 text-white" />
      </div>
    </div>
  </div>
);


/* ── Chart Tooltips (CSS-var aware for dark mode) ── */
const ChartTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: "var(--tooltip-bg)", border: "1px solid var(--tooltip-border)", color: "var(--tooltip-text)" }}
         className="rounded-lg px-3 py-2 text-sm shadow-lg">
      <p className="font-semibold mb-1" style={{ color: "var(--tooltip-text)" }}>
        {formatChartTime(label)}
      </p>
      {payload.map((item) => (
        <p key={item.dataKey} className="flex items-center gap-2">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: item.color }} />
          <span style={{ color: "var(--tooltip-muted)" }}>{item.name}:</span>
          <span className="font-medium" style={{ color: item.color }}>{Number(item.value || 0).toFixed(2)}%</span>
        </p>
      ))}
    </div>
  );
};

const SEVERITY_BADGE = {
  low: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
  medium: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-200",
  high: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-200",
  critical: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-200",
};
const severityBadge = (s) => SEVERITY_BADGE[s?.toLowerCase()] || SEVERITY_BADGE.low;

const API_URL = process.env.REACT_APP_API_URL || "/api";

const Dashboard = () => {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const activeOrgId = useSelector(
    (state) => state.organization?.currentOrganization?.id ?? null,
  );
  const activeOrgName = useSelector(
    (state) => state.organization?.currentOrganization?.name ?? null,
  );
  const { token } = useSelector((state) => state.auth);
  const { summary: reduxSummary, loading } = useSelector((state) => state.dashboard || { summary: {}, loading: false });
  const reduxVms = useSelector((state) => state.resources?.vms ?? []);
  const [costByResource, setCostByResource] = useState([]);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [realtimeStatus, setRealtimeStatus] = useState("connecting");
  const activeOrgIdRef = useRef(activeOrgId);

  useEffect(() => {
    activeOrgIdRef.current = activeOrgId;
  }, [activeOrgId]);

  const summary = reduxSummary || {};
  const costPerfRecommendations = (summary.cost_performance || {}).recommendations || [];
  const recentThreats = summary.security?.recent_threats || [];
  const recentActivity = summary.recent_activity || [];
  const reduxDatabases = useSelector((state) => state.resources?.databases ?? []);
  const inventoryResources = [...reduxVms, ...reduxDatabases];
  const snapshotAgeSeconds = Number(summary.snapshot_age_seconds ?? 0);
  const snapshotFresh = summary.snapshot_fresh !== false;
  const snapshotUpdatedAt =
    lastUpdated ||
    (Number.isFinite(Number(summary.snapshot_timestamp))
      ? new Date(Number(summary.snapshot_timestamp) * 1000)
      : null);

  useEffect(() => {
    if (!activeOrgId || !token) return;
    dispatch(fetchDashboardSummary(activeOrgId));
    dispatch(fetchVMs(activeOrgId));
    dispatch(fetchDatabases(activeOrgId));
    axios
      .get(`${API_URL}/dashboard/cost-by-resource`, {
        headers: { Authorization: `Bearer ${token}` },
        params: { org_id: activeOrgId },
      })
      .then((res) => setCostByResource(res.data?.data || []))
      .catch(() => setCostByResource([]));
  }, [activeOrgId, token, dispatch]);

  useEffect(() => {
    setCostByResource([]);
    setError(null);
    setLastUpdated(null);
  }, [activeOrgId]);

  useEffect(() => {
    if (!activeOrgId) return;

    setRealtimeStatus("connecting");
    const newSocket = createSocket("/metrics");
    if (!newSocket) return;

    const onConnect = () => {
      setRealtimeStatus("connected");
      const latestOrgId = activeOrgIdRef.current;
      if (!latestOrgId) return;
      newSocket.emit("join_room", { org_id: latestOrgId });
      console.log("[SOCKET] Connected to /metrics and joined room:", `org_${latestOrgId}`);
    };

    const onDashboardUpdate = (data) => {
      console.log("[SOCKET] Received dashboard_update:", data);
      const latestOrgId = activeOrgIdRef.current;
      if (data?.org_id !== latestOrgId && data?.organization_id !== latestOrgId) return;
      const normalized = normalizeDashboardSnapshot(data, latestOrgId);
      if (normalized) {
        dispatch(updateDashboardState(normalized));
        setLastUpdated(new Date(data.timestamp ? data.timestamp * 1000 : Date.now()));
        return;
      }
      if (latestOrgId) {
        dispatch(fetchDashboardSummary(latestOrgId));
      }
    };

    const onVmCreated = (resource) => {
      console.log("[SOCKET] Received vm_created:", resource);
      if (!resource?.id) return;
      const latestOrgId = activeOrgIdRef.current;
      const resourceOrgId = resource.org_id ?? resource.organization_id ?? null;
      if (resourceOrgId !== null && resourceOrgId !== latestOrgId) return;
      dispatch(upsertVM(resource));
      if (latestOrgId) {
        dispatch(fetchDashboardSummary(latestOrgId));
      }
    };

    const onVmUpdated = (resource) => {
      console.log("[SOCKET] Received vm_updated:", resource);
      if (!resource?.id) return;
      const latestOrgId = activeOrgIdRef.current;
      const resourceOrgId = resource.org_id ?? resource.organization_id ?? null;
      if (resourceOrgId !== null && resourceOrgId !== latestOrgId) return;
      dispatch(upsertVM(resource));
      if (latestOrgId) {
        dispatch(fetchDashboardSummary(latestOrgId));
      }
    };

    const onVmDeleted = (data) => {
      console.log("[SOCKET] Received vm_deleted:", data);
      const id = data.id || data.instance_id;
      if (!id) return;
      const latestOrgId = activeOrgIdRef.current;
      const dataOrgId = data.org_id ?? data.organization_id ?? null;
      if (dataOrgId !== null && dataOrgId !== latestOrgId) return;
      dispatch(removeVM(id));
      if (latestOrgId) {
        dispatch(fetchDashboardSummary(latestOrgId));
      }
    };

    const onDisconnect = () => setRealtimeStatus("disconnected");
    const onConnectError = () => setRealtimeStatus("disconnected");
    const onError = (message) => {
      setError(
        message?.error?.message ||
          "Live metrics stream is temporarily unavailable.",
      );
    };

    newSocket.on("connect", onConnect);
    newSocket.on("dashboard_update", onDashboardUpdate);
    newSocket.on("vm_created", onVmCreated);
    newSocket.on("vm_updated", onVmUpdated);
    newSocket.on("vm_deleted", onVmDeleted);
    newSocket.on("metrics:error", onError);
    newSocket.on("disconnect", onDisconnect);
    newSocket.on("connect_error", onConnectError);

    if (newSocket.connected) onConnect();

    return () => {
      newSocket.off("connect", onConnect);
      newSocket.off("dashboard_update", onDashboardUpdate);
      newSocket.off("vm_created", onVmCreated);
      newSocket.off("vm_updated", onVmUpdated);
      newSocket.off("vm_deleted", onVmDeleted);
      newSocket.off("metrics:error", onError);
      newSocket.off("disconnect", onDisconnect);
      newSocket.off("connect_error", onConnectError);
    };
  }, [activeOrgId, dispatch]);

  const chartData = summary.utilization_trend || [];

  const currentQueueMs = summary.workload?.queue_total_ms || 0;
  let systemStatus = "System Stable";
  let statusColor = "bg-success-50 text-success-600 dark:bg-success-900/20 dark:text-success-400";
  if (currentQueueMs > 1800) {
    systemStatus = "Approaching Saturation";
    statusColor = "bg-danger-50 text-danger-600 dark:bg-danger-900/20 dark:text-danger-400";
  } else if ((summary.bpi || 0) > (summary.target_bpi || 0) && (summary.bpi || 0) > 0) {
    systemStatus = "Scaling Triggered";
    statusColor = "bg-purple-50 text-purple-600 dark:bg-purple-900/20 dark:text-purple-400";
  } else if (currentQueueMs > 50) {
    systemStatus = "System Under Load";
    statusColor = "bg-warning-50 text-warning-600 dark:bg-warning-900/20 dark:text-warning-400";
  }
  
  if (loading) {
    return (
      <div className="space-y-6 animate-fade-up">
        <div className="skeleton h-16 w-full rounded-xl" />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="card p-5">
              <div className="skeleton h-3 w-24 mb-3" />
              <div className="skeleton h-8 w-16 mb-2" />
              <div className="skeleton h-3 w-32" />
            </div>
          ))}
        </div>
        <div className="card">
          <div className="skeleton h-4 w-40 mb-4" />
          <div className="skeleton h-56 w-full" />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">

      {/* ── 1. Organization Workspace Banner ── */}
      <div className="animate-fade-up flex flex-wrap items-center justify-between gap-3 rounded-xl bg-gradient-to-r from-blue-800 via-indigo-700 to-violet-700 px-5 py-4 shadow-lg">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-white/15">
            <BuildingOfficeIcon className="h-5 w-5 text-white" />
          </div>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-white/60">Organization Workspace</p>
            <p className="text-sm font-bold text-white leading-tight mt-0.5">
              {activeOrgName || "Select an organization"}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white/15 px-3 py-1 text-xs font-semibold text-white">
            <ClockIcon className="h-3.5 w-3.5" />Control Loop: 2s
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white/15 px-3 py-1 text-xs font-semibold text-white">
            <ShieldCheckIcon className="h-3.5 w-3.5" />Multi-Tenant
          </span>
          {realtimeStatus === "connected" ? (
            <span className="inline-flex items-center gap-2 rounded-full bg-emerald-500/20 px-3 py-1 text-xs font-bold text-emerald-300">
              <span className="live-dot h-2 w-2 rounded-full bg-emerald-400" />
              Live
            </span>
          ) : (
            <span className="inline-flex items-center gap-2 rounded-full bg-amber-500/20 px-3 py-1 text-xs font-bold text-amber-300">
              <span className="h-2 w-2 rounded-full bg-amber-400" />
              Reconnecting
            </span>
          )}
        </div>
      </div>

      {/* ── Dashboard header ── */}
      <div className="animate-fade-up-1 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-white tracking-tight">
            Resource Operations Dashboard
          </h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <span className="text-xs text-gray-400 dark:text-gray-500">
              {snapshotUpdatedAt
                ? `Updated ${snapshotUpdatedAt.toLocaleTimeString()}`
                : "Awaiting metrics"}
            </span>
            <span className="text-gray-300 dark:text-gray-600">·</span>
            <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${statusColor}`}>
              {systemStatus}
            </span>
            <span
              className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-medium ${
                snapshotFresh
                  ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300"
                  : "bg-amber-100 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300"
              }`}
            >
              {snapshotFresh ? "Fresh snapshot" : "Stale snapshot"} {snapshotAgeSeconds.toFixed(1)}s
            </span>
          </div>
        </div>
        <button
          type="button"
          onClick={() => activeOrgId && dispatch(fetchDashboardSummary(activeOrgId))}
          className="btn-secondary"
        >
          <ArrowPathIcon className="h-4 w-4" />
          Refresh
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-danger-100 bg-danger-50 px-4 py-3 text-sm text-danger-700 dark:border-danger-800 dark:bg-danger-900/20 dark:text-danger-100">
          {error}
        </div>
      )}

      {/* ── Security alert banner ── */}
      {(reduxSummary?.security?.total_unresolved ?? 0) > 0 && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 dark:border-red-800 dark:bg-red-900/20">
          <p className="text-sm font-medium text-red-700 dark:text-red-300">
            ⚠ {reduxSummary.security.total_unresolved} unresolved security threat(s)
          </p>
          <button
            type="button"
            onClick={() => navigate("/security")}
            className="shrink-0 text-sm font-semibold text-red-700 underline hover:text-red-900 dark:text-red-300 dark:hover:text-red-100"
          >
            Go to Security →
          </button>
        </div>
      )}

      {/* ── 2. Summary Metric Cards ── */}
      <div className="animate-fade-up-2 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">

        {/* Org CPU Health */}
        <div className={`card group border-l-4 ${(summary.cpu_avg ?? 0) >= 85 ? "border-red-500" : (summary.cpu_avg ?? 0) >= 65 ? "border-amber-500" : "border-emerald-500"}`}>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="section-label">Org CPU Health</p>
              <p className="mt-2 text-3xl font-bold tabular-nums text-gray-900 dark:text-white tracking-tight">
                {formatPercent(summary.cpu_avg ?? 0, 1)}
              </p>
              <p className="section-sub">{summary.total_vms ?? 0} VMs · {summary.running_vms ?? 0} running</p>
            </div>
            <div className={`shrink-0 rounded-xl p-3 shadow-sm transition-transform duration-200 group-hover:scale-110 ${(summary.cpu_avg ?? 0) >= 85 ? "bg-red-500" : (summary.cpu_avg ?? 0) >= 65 ? "bg-amber-500" : "bg-emerald-500"}`}>
              <CpuChipIcon className="h-5 w-5 text-white" />
            </div>
          </div>
        </div>

        {/* Org Memory Status */}
        <div className={`card group border-l-4 ${(summary.memory_avg ?? 0) >= 85 ? "border-red-500" : (summary.memory_avg ?? 0) >= 65 ? "border-amber-500" : "border-emerald-500"}`}>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="section-label">Org Memory Status</p>
              <p className="mt-2 text-3xl font-bold tabular-nums text-gray-900 dark:text-white tracking-tight">
                {formatPercent(summary.memory_avg ?? 0, 1)}
              </p>
              <p className="section-sub">Mean across running VMs</p>
            </div>
            <div className={`shrink-0 rounded-xl p-3 shadow-sm transition-transform duration-200 group-hover:scale-110 ${(summary.memory_avg ?? 0) >= 85 ? "bg-red-500" : (summary.memory_avg ?? 0) >= 65 ? "bg-amber-500" : "bg-emerald-500"}`}>
              <ServerStackIcon className="h-5 w-5 text-white" />
            </div>
          </div>
        </div>

        {/* Security Status */}
        {(() => {
          const score = summary.security_score ?? 0;
          const good = score >= 80;
          return (
            <div className={`card group border-l-4 ${good ? "border-emerald-500" : "border-red-500"}`}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <p className="section-label">Security Status</p>
                  <p className={`mt-2 text-3xl font-bold tabular-nums tracking-tight ${good ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
                    {score}<span className="text-base font-medium text-gray-400">/100</span>
                  </p>
                  <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-gray-100 dark:bg-gray-700">
                    <div className={`h-1.5 rounded-full transition-all duration-500 ${good ? "bg-emerald-500" : "bg-red-500"}`} style={{ width: `${score}%` }} />
                  </div>
                </div>
                <div className={`shrink-0 rounded-xl p-3 shadow-sm transition-transform duration-200 group-hover:scale-110 ${good ? "bg-emerald-500" : "bg-red-500"}`}>
                  <ShieldCheckIcon className="h-5 w-5 text-white" />
                </div>
              </div>
            </div>
          );
        })()}

        {/* Monthly Cost */}
        <div className="card group border-l-4 border-violet-500">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="section-label">Monthly Cost</p>
              <p className="mt-2 text-3xl font-bold tabular-nums text-violet-600 dark:text-violet-400 tracking-tight">
                {formatCost(summary.monthly_spend ?? 0)}
              </p>
              <p className="section-sub">Cumulative this session</p>
            </div>
            <div className="shrink-0 rounded-xl bg-violet-500 p-3 shadow-sm transition-transform duration-200 group-hover:scale-110">
              <CurrencyDollarIcon className="h-5 w-5 text-white" />
            </div>
          </div>
        </div>

      </div>

      {/* ── 3. DES Simulation Metrics ── */}
      <div className="animate-fade-up-2">
        <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500">
          DES Simulation Metrics
        </p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            title="Queue Depth"
            value={`${Number(summary.workload?.queue_total_ms || 0).toFixed(0)} ms`}
            subtitle="Pending work backlog (M/M/c queue)"
            icon={ServerStackIcon}
            accentClass="bg-warning-500"
          />
          <StatCard
            title="P95 Latency"
            value={`${Number(summary.workload?.p95_latency_ms || 0).toFixed(0)} ms`}
            subtitle="95th percentile response time"
            icon={BoltIcon}
            accentClass="bg-primary-500"
          />
          <StatCard
            title="Backlog Per Instance"
            value={`${Number(summary.bpi || 0).toFixed(1)} ms`}
            subtitle={`Target: ${Number(summary.target_bpi || 0).toFixed(1)} ms`}
            icon={ChartBarIcon}
            accentClass="bg-purple-500"
          />
          <StatCard
            title="Auto-Scaling Capacity"
            value={`${summary.capacity || 1} VM${(summary.capacity || 1) !== 1 ? "s" : ""}`}
            subtitle={`Running: ${summary.running_capacity || summary.workload?.vm_count || 0}`}
            icon={CpuChipIcon}
            accentClass="bg-success-500"
          />
        </div>
      </div>

      {/* ── 4. Resource Utilization Charts ── */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        {/* CPU + Memory trend */}
        <div className="card xl:col-span-2">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                CPU &amp; Memory Trend
              </h2>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Live utilization across the cloud organisation (DES-derived)
              </p>
            </div>
            <ChartBarIcon className="h-6 w-6 text-gray-400" />
          </div>
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" vertical={false} />
                <XAxis dataKey="name" tickFormatter={formatChartTime} minTickGap={32} tick={{ fill: "var(--tooltip-muted)" }} axisLine={false} tickLine={false} />
                <YAxis tickFormatter={(v) => `${v}%`} width={48} tick={{ fill: "var(--tooltip-muted)" }} axisLine={false} tickLine={false} />
                <Tooltip content={<ChartTooltip />} cursor={{ stroke: "var(--chart-grid)", strokeWidth: 1 }} />
                <Line type="monotone" dataKey="cpu" name="CPU" stroke="#3b82f6" strokeWidth={2.5} dot={false} activeDot={{ r: 5, strokeWidth: 0 }} />
                <Line type="monotone" dataKey="memory" name="Memory" stroke="#10b981" strokeWidth={2.5} dot={false} activeDot={{ r: 5, strokeWidth: 0 }} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-[300px] items-center justify-center rounded-xl border border-dashed border-gray-200 text-sm text-gray-400 dark:border-gray-700 dark:text-gray-500">
              No utilization history yet.
            </div>
          )}
        </div>

        {/* Network / Memory pressure */}
        <div className="card">
          <h2 className="mb-4 text-lg font-semibold text-gray-900 dark:text-white">
            Memory Pressure
          </h2>
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="memFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" vertical={false} />
                <XAxis dataKey="name" tickFormatter={formatChartTime} hide />
                <YAxis tickFormatter={(v) => `${v}%`} width={44} tick={{ fill: "var(--tooltip-muted)" }} axisLine={false} tickLine={false} />
                <Tooltip content={<ChartTooltip />} />
                <Area type="monotone" dataKey="memory" name="Memory" stroke="#10b981" strokeWidth={2} fill="url(#memFill)" />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-[240px] items-center justify-center rounded-xl border border-dashed border-gray-200 text-sm text-gray-400 dark:border-gray-700 dark:text-gray-500">
              No utilization history yet.
            </div>
          )}
          <div className="mt-4 space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-gray-500 dark:text-gray-400">Avg CPU</span>
              <span className="font-medium text-gray-900 dark:text-white">{formatPercent(summary.cpu_avg)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-gray-500 dark:text-gray-400">Avg Memory</span>
              <span className="font-medium text-gray-900 dark:text-white">{formatPercent(summary.memory_avg)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Cost trend */}
      {Array.isArray(summary.cost_trend) && summary.cost_trend.length > 0 && (
        <div className="card">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Cost Trend</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400">Cumulative spend over the current simulation window</p>
            </div>
            <CurrencyDollarIcon className="h-6 w-6 text-gray-400" />
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={summary.cost_trend}>
              <defs>
                <linearGradient id="costFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" vertical={false} />
              <XAxis dataKey="name" minTickGap={40} tick={{ fill: "var(--tooltip-muted)" }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={(v) => `$${Number(v || 0).toFixed(3)}`} width={64} tick={{ fill: "var(--tooltip-muted)" }} axisLine={false} tickLine={false} />
              <Tooltip
                content={({ active, payload, label }) =>
                  active && payload?.length ? (
                    <div style={{ background: "var(--tooltip-bg)", border: "1px solid var(--tooltip-border)", color: "var(--tooltip-text)" }} className="rounded-lg px-3 py-2 text-sm shadow-lg">
                      <p className="font-semibold mb-1">{label}</p>
                      {payload.map((item) => (
                        <p key={item.dataKey} className="flex items-center gap-2">
                          <span className="inline-block h-2 w-2 rounded-full" style={{ background: item.color }} />
                          <span>{item.name}:</span>
                          <span className="font-medium">{formatCost(item.value)}</span>
                        </p>
                      ))}
                    </div>
                  ) : null
                }
              />
              <Area type="monotone" dataKey="cost" name="Cost" stroke="#8b5cf6" fill="url(#costFill)" strokeWidth={2.5} dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── 5. Resource Inventory Table ── */}
      <div className="card">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            Resource Inventory
          </h2>
          <button
            type="button"
            onClick={() => navigate("/resources")}
            className="text-sm font-medium text-primary-600 hover:text-primary-800 dark:text-primary-400 dark:hover:text-primary-200"
          >
            View all →
          </button>
        </div>
        {inventoryResources.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-700">
              <thead>
                <tr className="text-left text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  <th className="pb-2 pr-4">Name</th>
                  <th className="pb-2 pr-4">Type</th>
                  <th className="pb-2 pr-4">Status</th>
                  <th className="pb-2 pr-4 min-w-[120px]">CPU %</th>
                  <th className="pb-2 pr-4">Memory %</th>
                  <th className="pb-2">Cost/hr</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {inventoryResources.slice(0, 8).map((vm, index) => {
                  const cpu = Number(vm.cpu_utilization ?? vm.cpu ?? 0);
                  const mem = Number(vm.memory_utilization ?? vm.memory ?? 0);
                  const resourceType = vm.resource_type || vm.type || (vm.instance_type ? "vm" : "database");
                  return (
                    <tr
                      key={`${resourceType}-${vm.id ?? vm.instance_id ?? index}`}
                      onClick={() => navigate("/resources")}
                      className="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/40"
                    >
                      <td className="py-2 pr-4 font-medium text-gray-900 dark:text-white">{vm.name}</td>
                      <td className="py-2 pr-4">
                        <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${resourceType === "database" ? "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300" : "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"}`}>
                          {vm.resource_type || vm.instance_type || resourceType || "vm"}
                        </span>
                      </td>
                      <td className="py-2 pr-4">
                        <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${vm.status === "running" ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" : vm.status === "stopped" ? "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300" : "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400"}`}>
                          {vm.status || "unknown"}
                        </span>
                      </td>
                      <td className="py-2 pr-4">
                        <div className="flex items-center gap-2">
                          <div className="h-2 w-20 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
                            <div className={`h-2 rounded-full ${cpu > 80 ? "bg-red-500" : "bg-blue-500"}`} style={{ width: `${Math.min(cpu, 100)}%` }} />
                          </div>
                          <span className="text-xs text-gray-500 dark:text-gray-400">{cpu.toFixed(1)}%</span>
                        </div>
                      </td>
                      <td className="py-2 pr-4">
                        <div className="flex items-center gap-2">
                          <div className="h-2 w-20 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
                            <div className={`h-2 rounded-full ${mem > 80 ? "bg-red-500" : "bg-emerald-500"}`} style={{ width: `${Math.min(mem, 100)}%` }} />
                          </div>
                          <span className="text-xs text-gray-500 dark:text-gray-400">{mem.toFixed(1)}%</span>
                        </div>
                      </td>
                      <td className="py-2 text-gray-700 dark:text-gray-300">${Number(vm.hourly_rate ?? 0).toFixed(4)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-gray-400 dark:text-gray-500">
            No resources found — provision a VM or database to see it here.
          </p>
        )}
      </div>

      {/* ── 6. Security Section ── */}
      <div className="card border-l-4 border-red-500">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Security Overview</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400">Recent threats, severity, and remediation status</p>
          </div>
          <button
            type="button"
            onClick={() => navigate("/security")}
            className="text-sm font-medium text-primary-600 hover:text-primary-800 dark:text-primary-400 dark:hover:text-primary-200"
          >
            View all →
          </button>
        </div>
        {recentThreats.length > 0 ? (
          <div className="space-y-3">
            {recentThreats.slice(0, 5).map((threat, idx) => (
              <div key={threat.id ?? idx} className="rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-800/60">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-gray-900 dark:text-white">{threat.event_type || threat.title || "Security event"}</p>
                    <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">{threat.description || threat.source_ip || "—"}</p>
                  </div>
                  <span className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${severityBadge(threat.severity)}`}>
                    {threat.severity || "low"}
                  </span>
                </div>
                <div className="mt-2 flex items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
                  {threat.acknowledged !== undefined && (
                    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 ${threat.acknowledged ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300" : "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300"}`}>
                      {threat.acknowledged ? "Remediated" : "Unresolved"}
                    </span>
                  )}
                  {threat.timestamp && <span>{new Date(threat.timestamp).toLocaleTimeString()}</span>}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-400 dark:text-gray-500">No recent threats detected.</p>
        )}
      </div>

      {/* ── 7. Cost Section ── */}
      <div className="card border-l-4 border-emerald-500">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Cost Optimisation</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400">Forecast-driven right-sizing recommendations</p>
          </div>
          <button
            type="button"
            onClick={() => navigate("/cost")}
            className="text-sm font-medium text-primary-600 hover:text-primary-800 dark:text-primary-400 dark:hover:text-primary-200"
          >
            Full analysis →
          </button>
        </div>

        {/* Cost by resource bar chart */}
        {costByResource.length > 0 && (
          <div className="mb-5">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Cost by Resource</p>
            <ResponsiveContainer width="100%" height={Math.max(100, costByResource.length * 34)}>
              <BarChart layout="vertical" data={costByResource} margin={{ top: 0, right: 16, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" horizontal={false} />
                <XAxis type="number" tickFormatter={(v) => `$${Number(v).toFixed(3)}`} tick={{ fontSize: 11 }} />
                <YAxis type="category" dataKey="name" width={140} tick={{ fontSize: 12 }} />
                <Tooltip
                  content={({ active, payload }) => {
                    if (!active || !payload?.length) return null;
                    const d = payload[0]?.payload || {};
                    return (
                      <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm shadow-sm dark:border-gray-700 dark:bg-gray-800">
                        <p className="font-semibold text-gray-900 dark:text-white">{d.name}</p>
                        <p className="text-gray-500 dark:text-gray-400 capitalize">{d.type}</p>
                        <p className="mt-1 font-medium text-gray-900 dark:text-white">${Number(d.cost).toFixed(4)}</p>
                      </div>
                    );
                  }}
                />
                <Bar dataKey="cost" radius={[0, 4, 4, 0]}>
                  {costByResource.map((entry, i) => (
                    <Cell key={`cell-${i}`} fill={entry.type === "database" ? "#f59e0b" : "#6366f1"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Optimisation recommendations */}
        <div className="space-y-3">
          {costPerfRecommendations.length > 0 ? (
            costPerfRecommendations.slice(0, 4).map((item) => (
              <div key={`${item.resource_kind}-${item.resource_id || item.title}`} className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-800/60">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-gray-900 dark:text-white">{item.title}</p>
                    <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">{item.message}</p>
                  </div>
                  <span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-gray-700 shadow-sm dark:bg-gray-900 dark:text-gray-200">
                    {item.action}
                  </span>
                </div>
                {(item.estimated_monthly_savings || item.savings_pct !== null) && (
                  <div className="mt-2 flex flex-wrap gap-2 text-xs">
                    {item.savings_pct != null && (
                      <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-100">
                        Saves {Number(item.savings_pct).toFixed(0)}%
                      </span>
                    )}
                    {item.estimated_monthly_savings && (
                      <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-100">
                        {formatCost(item.estimated_monthly_savings)}/mo
                      </span>
                    )}
                  </div>
                )}
              </div>
            ))
          ) : (
            <p className="text-sm text-gray-400 dark:text-gray-500">No optimisation recommendations at this time.</p>
          )}
        </div>
      </div>

      {/* ── 8. Recent Activity Log ── */}
      <div className="card">
        <h2 className="mb-4 text-lg font-semibold text-gray-900 dark:text-white">Recent Activity</h2>
        {recentActivity.length > 0 ? (
          <ul className="space-y-2">
            {recentActivity.slice(0, 8).map((event, idx) => {
              const activityDetails = formatActivityDetails(event.details);
              return (
                <li key={event.id ?? idx} className="flex items-start gap-3 rounded-lg bg-gray-50 px-3 py-2 dark:bg-gray-700/40">
                  <ClockIcon className="mt-0.5 h-4 w-4 shrink-0 text-gray-400" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="truncate text-sm font-medium text-gray-900 dark:text-white">
                        {event.title || event.type || "Operational event"}
                      </p>
                      {event.severity && (
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${severityBadge(event.severity)}`}>
                          {event.severity}
                        </span>
                      )}
                    </div>
                    {activityDetails && (
                      <p className="mt-0.5 truncate text-xs text-gray-500 dark:text-gray-400">
                        {activityDetails}
                      </p>
                    )}
                    {event.timestamp && (
                      <p className="mt-0.5 text-[10px] uppercase tracking-wide text-gray-400 dark:text-gray-500">
                        {new Date(event.timestamp).toLocaleTimeString()}
                      </p>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-sm text-gray-400 dark:text-gray-500">No recent activity recorded yet.</p>
        )}
      </div>

    </div>
  );
};

export default Dashboard;
