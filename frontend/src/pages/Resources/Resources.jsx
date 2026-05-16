import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useSelector } from "react-redux";
import axios from "axios";
import { createSocket } from "../../services/api";
import LearningPanel from "../../components/Learning/LearningPanel";
import {
  PlusIcon,
  CircleStackIcon,
  StopIcon,
  TrashIcon,
  ServerIcon,
  PlayIcon,
  ArrowPathIcon,
  XMarkIcon,
  ChevronDownIcon,
  ChevronUpIcon,
} from "@heroicons/react/24/outline";
import toast from "react-hot-toast";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  AreaChart,
  Area,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
} from "recharts";

const API_URL = process.env.REACT_APP_API_URL || "/api";

const statusClass = (status) => {
  const normalized = (status || "").toLowerCase();
  if (normalized === "running")
    return "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400";
  if (normalized === "stopped")
    return "bg-gray-100 text-gray-800 dark:bg-gray-900/30 dark:text-gray-400";
  if (normalized === "pending" || normalized === "creating")
    return "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400";
  return "bg-gray-100 text-gray-800 dark:bg-gray-900/30 dark:text-gray-400";
};

const INSTANCE_TYPE_CATALOG = {
  "t2.micro": {
    vcpu: 1,
    memory_gb: 1,
    network: "Low to moderate",
    storage: "EBS-only",
    hourly_rate: 0.0116,
  },
  "t2.small": {
    vcpu: 1,
    memory_gb: 2,
    network: "Moderate",
    storage: "EBS-only",
    hourly_rate: 0.023,
  },
  "t2.medium": {
    vcpu: 2,
    memory_gb: 4,
    network: "Moderate",
    storage: "EBS-only",
    hourly_rate: 0.0464,
  },
  "t2.large": {
    vcpu: 2,
    memory_gb: 8,
    network: "Moderate to high",
    storage: "EBS-only",
    hourly_rate: 0.0928,
  },
  "t2.xlarge": {
    vcpu: 4,
    memory_gb: 16,
    network: "High",
    storage: "EBS-only",
    hourly_rate: 0.1856,
  },
};

const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

const formatCurrency = (value) =>
  currencyFormatter.format(Number.isFinite(Number(value)) ? Number(value) : 0);

const formatDateTime = (value) => {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
};

const formatUptime = (createdAt) => {
  if (!createdAt) return "—";
  const startedAt = new Date(createdAt).getTime();
  if (Number.isNaN(startedAt)) return "—";
  const totalMinutes = Math.max(0, Math.floor((Date.now() - startedAt) / 60000));
  const days = Math.floor(totalMinutes / (60 * 24));
  const hours = Math.floor((totalMinutes % (60 * 24)) / 60);
  const minutes = totalMinutes % 60;
  const segments = [];
  if (days > 0) segments.push(`${days}d`);
  if (hours > 0 || days > 0) segments.push(`${hours}h`);
  segments.push(`${minutes}m`);
  return segments.join(" ");
};

const roundValue = (value, digits = 2) =>
  Number(Number(value || 0).toFixed(digits));

const buildVmChartData = (metrics, hourlyRate) => {
  let cumulativeCost = 0;
  return metrics.map((point, index) => {
    const timestamp = point?.timestamp ? new Date(point.timestamp) : new Date();
    const previousTimestamp =
      index > 0 && metrics[index - 1]?.timestamp
        ? new Date(metrics[index - 1].timestamp)
        : null;
    if (previousTimestamp && !Number.isNaN(previousTimestamp.getTime())) {
      const deltaHours = Math.max(
        0,
        (timestamp.getTime() - previousTimestamp.getTime()) / 3600000,
      );
      cumulativeCost += deltaHours * Number(hourlyRate || 0);
    }

    const cpu = Number(point?.cpu || 0);
    const memory = Number(point?.memory || 0);
    const networkIn = Number(point?.network_in || 0) * 125;
    const networkOut = Number(point?.network_out || 0) * 125;

    return {
      ...point,
      label: point?.name || formatDateTime(timestamp.toISOString()),
      cpu: roundValue(cpu, 2),
      memory: roundValue(memory, 2),
      cumulative_cost: roundValue(cumulativeCost, 4),
      network_in_kbps: roundValue(networkIn, 2),
      network_out_kbps: roundValue(networkOut, 2),
    };
  });
};

const VmDetailModal = ({
  vm,
  open,
  onClose,
  securityGroups,
  authHeaders,
  currentOrganizationId,
  currentRole,
  onResourceUpdated,
  onResourceDeleted,
}) => {
  const [metrics, setMetrics] = useState([]);
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [metricsError, setMetricsError] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [learningContent, setLearningContent] = useState(null);
  const [learningLoading, setLearningLoading] = useState(false);
  const [learningError, setLearningError] = useState("");
  const [resizeTarget, setResizeTarget] = useState(vm?.instance_type || "t2.micro");
  const [tagKey, setTagKey] = useState("");
  const [tagValue, setTagValue] = useState("");
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [busyAction, setBusyAction] = useState("");

  useEffect(() => {
    if (!open || !vm) return;
    setResizeTarget(vm.instance_type || "t2.micro");
    setTagKey("");
    setTagValue("");
    setDeleteConfirmation("");
    setSidebarOpen(true);
  }, [open, vm]);

  useEffect(() => {
    if (!open || !vm?.id) return undefined;

    let cancelled = false;

    const loadMetrics = async () => {
      setMetricsLoading(true);
      setMetricsError("");
      try {
        const response = await axios.get(
          `${API_URL}/resources/vms/${vm.id}/metrics`,
          {
            headers: authHeaders,
            params: { organization_id: currentOrganizationId },
          },
        );
        if (cancelled) return;
        const payload = response?.data?.data || {};
        setMetrics(Array.isArray(payload.metrics) ? payload.metrics : []);
      } catch (error) {
        if (!cancelled) {
          setMetrics([]);
          setMetricsError(
            error?.response?.data?.error?.message ||
              "Unable to load VM metrics.",
          );
        }
      } finally {
        if (!cancelled) {
          setMetricsLoading(false);
        }
      }
    };

    loadMetrics();
    // TASK 5: Poll every 30 s instead of 10 s — live data arrives via WebSocket;
    // this interval is only a safety-net fallback for the metrics history chart.
    const interval = window.setInterval(loadMetrics, 30000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [authHeaders, currentOrganizationId, open, vm?.id]);

  useEffect(() => {
    if (!open) return undefined;

    let cancelled = false;

    const loadLearningContent = async () => {
      setLearningLoading(true);
      setLearningError("");
      try {
        const response = await axios.get(`${API_URL}/learning/content/vm_detail`);
        if (!cancelled) {
          setLearningContent(response?.data?.data || null);
        }
      } catch (error) {
        if (!cancelled) {
          setLearningContent(null);
          setLearningError(
            error?.response?.data?.error?.message ||
              "Learning content unavailable.",
          );
        }
      } finally {
        if (!cancelled) {
          setLearningLoading(false);
        }
      }
    };

    loadLearningContent();

    return () => {
      cancelled = true;
    };
  }, [open]);

  const chartData = useMemo(
    () => buildVmChartData(metrics, vm?.hourly_rate),
    [metrics, vm?.hourly_rate],
  );

  const attachedSecurityGroups = useMemo(() => {
    const attachedIds = new Set((vm?.security_groups || []).map((group) => group.id));
    return securityGroups.filter((group) => attachedIds.has(group.id));
  }, [securityGroups, vm?.security_groups]);

  const currentSpec = INSTANCE_TYPE_CATALOG[vm?.instance_type] || INSTANCE_TYPE_CATALOG["t2.micro"];
  const selectedSpec = INSTANCE_TYPE_CATALOG[resizeTarget] || currentSpec;
  const canManage = currentRole && currentRole !== "viewer";
  const canResize = canManage && resizeTarget && resizeTarget !== vm?.instance_type;
  const canDelete = (currentRole === "admin" || currentRole === "owner") &&
    deleteConfirmation.trim() === (vm?.name || "");

  if (!open || !vm) {
    return null;
  }

  const mergeResource = (updated) => {
    if (!updated) return;
    onResourceUpdated?.(updated);
  };

  const runResourceAction = async (action, successMessage) => {
    setBusyAction(action);
    try {
      const response = await axios.post(
        `${API_URL}/resources/${vm.id}/${action}`,
        {},
        {
          headers: authHeaders,
          params: { organization_id: currentOrganizationId },
        },
      );
      const updated = response?.data?.data || null;
      mergeResource(updated);
      toast.success(successMessage);
    } catch (error) {
      toast.error(
        error?.response?.data?.error?.message || "Something went wrong",
      );
    } finally {
      setBusyAction("");
    }
  };

  const handleResize = async () => {
    if (!canResize) return;
    setBusyAction("resize");
    try {
      const response = await axios.put(
        `${API_URL}/resources/vms/${vm.id}/resize`,
        { instance_type: resizeTarget },
        {
          headers: authHeaders,
          params: { organization_id: currentOrganizationId },
        },
      );
      mergeResource(response?.data?.data || null);
      toast.success("VM resized successfully");
    } catch (error) {
      toast.error(
        error?.response?.data?.error?.message || "Unable to resize VM.",
      );
    } finally {
      setBusyAction("");
    }
  };

  const handleAddTag = async () => {
    if (!canManage || !tagKey.trim()) {
      toast.error("Tag key is required");
      return;
    }
    setBusyAction("tag");
    try {
      const response = await axios.put(
        `${API_URL}/resources/vms/${vm.id}/tags`,
        { tags: { [tagKey]: tagValue } },
        {
          headers: authHeaders,
          params: { organization_id: currentOrganizationId },
        },
      );
      mergeResource(response?.data?.data || null);
      setTagKey("");
      setTagValue("");
      toast.success("Tag saved");
    } catch (error) {
      toast.error(
        error?.response?.data?.error?.message || "Unable to save tag.",
      );
    } finally {
      setBusyAction("");
    }
  };

  const handleDelete = async () => {
    if (!canDelete) {
      toast.error("Type the VM name to confirm deletion");
      return;
    }
    setBusyAction("delete");
    try {
      await axios.delete(`${API_URL}/resources/${vm.id}`, {
        headers: authHeaders,
        params: { organization_id: currentOrganizationId },
      });
      onResourceDeleted?.(vm.id);
      onClose();
      toast.success("VM deleted");
    } catch (error) {
      toast.error(
        error?.response?.data?.error?.message || "Unable to delete VM.",
      );
    } finally {
      setBusyAction("");
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm">
      <button
        type="button"
        aria-label="Close VM detail modal"
        className="absolute inset-0 cursor-default"
        onClick={onClose}
      />
      <div className="relative flex h-full w-full flex-col bg-slate-950/90 text-white xl:flex-row">
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden border-slate-800 bg-slate-950/95">
          <div className="flex items-start justify-between border-b border-slate-800 px-6 py-5">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.3em] text-cyan-300">
                VM Detail
              </p>
              <h2 className="mt-2 text-3xl font-bold text-white">{vm.name}</h2>
              <div className="mt-3 flex flex-wrap gap-2 text-xs font-medium text-slate-300">
                <span className={`rounded-full px-3 py-1 ${statusClass(vm.status)}`}>
                  {(vm.status || "unknown").toLowerCase()}
                </span>
                <span className="rounded-full bg-white/10 px-3 py-1 text-white">
                  {vm.instance_type || "Unknown type"}
                </span>
                <span className="rounded-full bg-white/10 px-3 py-1 text-white">
                  {vm.region || "us-east-1"}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setSidebarOpen((prev) => !prev)}
                className="rounded-full border border-slate-700 bg-slate-900/80 p-2 text-slate-200 transition-colors hover:border-cyan-400 hover:text-white"
                aria-label={sidebarOpen ? "Collapse learning sidebar" : "Expand learning sidebar"}
              >
                {sidebarOpen ? (
                  <ChevronUpIcon className="h-5 w-5 xl:hidden" />
                ) : (
                  <ChevronDownIcon className="h-5 w-5 xl:hidden" />
                )}
                <span className="hidden xl:inline">{sidebarOpen ? "Hide learning" : "Show learning"}</span>
              </button>
              <button
                type="button"
                onClick={onClose}
                className="rounded-full border border-slate-700 bg-slate-900/80 p-2 text-slate-200 transition-colors hover:border-white hover:text-white"
                aria-label="Close"
              >
                <XMarkIcon className="h-5 w-5" />
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-6 py-6">
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-6">
              <div className="rounded-2xl border border-slate-800 bg-white/5 p-4 xl:col-span-2">
                <p className="text-xs uppercase tracking-wide text-slate-400">Private IP</p>
                <p className="mt-2 text-xl font-semibold text-white">{vm.private_ip || "—"}</p>
              </div>
              <div className="rounded-2xl border border-slate-800 bg-white/5 p-4 xl:col-span-2">
                <p className="text-xs uppercase tracking-wide text-slate-400">Uptime</p>
                <p className="mt-2 text-xl font-semibold text-white">{formatUptime(vm.launched_at ?? vm.created_at)}</p>
              </div>
              <div className="rounded-2xl border border-slate-800 bg-white/5 p-4 xl:col-span-2">
                <p className="text-xs uppercase tracking-wide text-slate-400">Total Cost Accrued</p>
                <p className="mt-2 text-xl font-semibold text-white">{formatCurrency(vm.current_cost ?? vm.hourly_rate ?? 0)}</p>
              </div>
            </div>

            <section className="mt-6 space-y-4">
              <div className="flex items-end justify-between gap-3">
                <div>
                  <h3 className="text-lg font-semibold text-white">Metrics</h3>
                  <p className="text-sm text-slate-400">Live metrics refresh every 30 seconds (real-time events via WebSocket).</p>
                </div>
                {metricsLoading && <span className="text-sm text-slate-400">Refreshing...</span>}
              </div>
              {metricsError && (
                <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
                  {metricsError}
                </div>
              )}
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
                  <p className="mb-3 text-sm font-semibold text-slate-200">CPU Usage %</p>
                  <div className="h-64">
                    {chartData.length > 0 ? (
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={chartData}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                          <XAxis dataKey="label" stroke="#94a3b8" tick={{ fontSize: 12 }} />
                          <YAxis stroke="#94a3b8" domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 12 }} />
                          <Tooltip
                            contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1f2937", color: "#fff" }}
                            formatter={(value) => `${Number(value).toFixed(1)}%`}
                          />
                          <ReferenceLine y={80} stroke="#ef4444" strokeDasharray="6 6" />
                          <Line type="monotone" dataKey="cpu" stroke="#ef4444" strokeWidth={2} dot={false} />
                        </LineChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-slate-700 text-sm text-slate-400">
                        No CPU history available.
                      </div>
                    )}
                  </div>
                </div>

                <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
                  <p className="mb-3 text-sm font-semibold text-slate-200">Memory Usage %</p>
                  <div className="h-64">
                    {chartData.length > 0 ? (
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={chartData}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                          <XAxis dataKey="label" stroke="#94a3b8" tick={{ fontSize: 12 }} />
                          <YAxis stroke="#94a3b8" domain={[0, 100]} tick={{ fontSize: 12 }} />
                          <Tooltip
                            contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1f2937", color: "#fff" }}
                            formatter={(value) => `${Number(value).toFixed(1)}%`}
                          />
                          <ReferenceLine y={85} stroke="#f97316" strokeDasharray="6 6" />
                          <Line type="monotone" dataKey="memory" stroke="#f97316" strokeWidth={2} dot={false} />
                        </LineChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-slate-700 text-sm text-slate-400">
                        No memory history available.
                      </div>
                    )}
                  </div>
                </div>

                <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
                  <p className="mb-3 text-sm font-semibold text-slate-200">Network In/Out (KB/s)</p>
                  <div className="h-64">
                    {chartData.length > 0 ? (
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={chartData}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                          <XAxis dataKey="label" stroke="#94a3b8" tick={{ fontSize: 12 }} />
                          <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} />
                          <Tooltip
                            contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1f2937", color: "#fff" }}
                          />
                          <Area type="monotone" dataKey="network_in_kbps" stroke="#3b82f6" fill="rgba(59,130,246,0.3)" strokeWidth={2} name="Network In" />
                          <Area type="monotone" dataKey="network_out_kbps" stroke="#22c55e" fill="rgba(34,197,94,0.3)" strokeWidth={2} name="Network Out" />
                        </AreaChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-slate-700 text-sm text-slate-400">
                        No network history available.
                      </div>
                    )}
                  </div>
                </div>

                <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
                  <p className="mb-3 text-sm font-semibold text-slate-200">Cost Accrual</p>
                  <div className="h-64">
                    {chartData.length > 0 ? (
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={chartData}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                          <XAxis dataKey="label" stroke="#94a3b8" tick={{ fontSize: 12 }} />
                          <YAxis stroke="#94a3b8" tickFormatter={(value) => `$${Number(value).toFixed(2)}`} tick={{ fontSize: 12 }} />
                          <Tooltip
                            formatter={(value) => formatCurrency(value)}
                            contentStyle={{ backgroundColor: "#0f172a", borderColor: "#1f2937", color: "#fff" }}
                          />
                          <Area type="monotone" dataKey="cumulative_cost" stroke="#8b5cf6" fill="rgba(139,92,246,0.2)" strokeWidth={2} />
                        </AreaChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-slate-700 text-sm text-slate-400">
                        No cost history available.
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </section>

            <section className="mt-8 grid grid-cols-1 gap-6 xl:grid-cols-2">
              <div className="rounded-3xl border border-slate-800 bg-slate-900/60 p-5">
                <h3 className="text-lg font-semibold text-white">Configuration</h3>
                <div className="mt-4 overflow-hidden rounded-2xl border border-slate-800">
                  <table className="min-w-full divide-y divide-slate-800 text-sm">
                    <thead className="bg-slate-950/80 text-slate-300">
                      <tr>
                        <th className="px-4 py-3 text-left font-medium">Instance type</th>
                        <th className="px-4 py-3 text-left font-medium">vCPU</th>
                        <th className="px-4 py-3 text-left font-medium">RAM</th>
                        <th className="px-4 py-3 text-left font-medium">Network</th>
                        <th className="px-4 py-3 text-left font-medium">Storage</th>
                        <th className="px-4 py-3 text-left font-medium">$/hr</th>
                        <th className="px-4 py-3 text-left font-medium">$/month</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800 text-slate-200">
                      {Object.entries(INSTANCE_TYPE_CATALOG).map(([type, spec]) => {
                        const isCurrent = type === vm.instance_type;
                        const isSelected = type === resizeTarget;
                        return (
                          <tr key={type} className={isSelected ? "bg-cyan-500/10" : ""}>
                            <td className="px-4 py-3 font-medium text-white">
                              <div className="flex items-center gap-2">
                                <span>{type}</span>
                                {isCurrent && <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] uppercase tracking-wide text-emerald-200">current</span>}
                                {isSelected && !isCurrent && <span className="rounded-full bg-cyan-500/20 px-2 py-0.5 text-[10px] uppercase tracking-wide text-cyan-200">selected</span>}
                              </div>
                            </td>
                            <td className="px-4 py-3">{spec.vcpu}</td>
                            <td className="px-4 py-3">{spec.memory_gb} GB</td>
                            <td className="px-4 py-3">{spec.network}</td>
                            <td className="px-4 py-3">{spec.storage}</td>
                            <td className="px-4 py-3">{formatCurrency(spec.hourly_rate)}</td>
                            <td className="px-4 py-3">{formatCurrency(spec.hourly_rate * 730)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                <div className="mt-5 grid gap-4 lg:grid-cols-2">
                  <div>
                    <label className="mb-2 block text-sm font-medium text-slate-300">Resize instance type</label>
                    <select
                      value={resizeTarget}
                      onChange={(event) => setResizeTarget(event.target.value)}
                      className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none transition-colors focus:border-cyan-400"
                    >
                      {Object.keys(INSTANCE_TYPE_CATALOG).map((type) => (
                        <option key={type} value={type}>{type}</option>
                      ))}
                    </select>
                  </div>
                  <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-300">
                    <p className="text-xs uppercase tracking-wide text-slate-500">Cost comparison</p>
                    <p className="mt-2 text-white">Current: {formatCurrency(currentSpec.hourly_rate)} / hr</p>
                    <p className="text-white">Selected: {formatCurrency(selectedSpec.hourly_rate)} / hr</p>
                    <p className={`mt-2 font-medium ${selectedSpec.hourly_rate > currentSpec.hourly_rate ? "text-amber-300" : "text-emerald-300"}`}>
                      Delta: {formatCurrency(selectedSpec.hourly_rate - currentSpec.hourly_rate)} / hr
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={handleResize}
                    disabled={!canResize || busyAction === "resize"}
                    className="rounded-xl bg-cyan-500 px-4 py-3 font-semibold text-slate-950 transition-colors hover:bg-cyan-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                  >
                    {busyAction === "resize" ? "Resizing..." : "Resize VM"}
                  </button>
                </div>

                <div className="mt-5 grid gap-4 lg:grid-cols-2">
                  <div>
                    <label className="mb-2 block text-sm font-medium text-slate-300">Add tag key</label>
                    <input
                      value={tagKey}
                      onChange={(event) => setTagKey(event.target.value)}
                      className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none transition-colors focus:border-cyan-400"
                      placeholder="Environment"
                    />
                  </div>
                  <div>
                    <label className="mb-2 block text-sm font-medium text-slate-300">Add tag value</label>
                    <input
                      value={tagValue}
                      onChange={(event) => setTagValue(event.target.value)}
                      className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none transition-colors focus:border-cyan-400"
                      placeholder="Production"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={handleAddTag}
                    disabled={!canManage || !tagKey.trim() || busyAction === "tag"}
                    className="rounded-xl bg-white px-4 py-3 font-semibold text-slate-950 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                  >
                    {busyAction === "tag" ? "Saving..." : "Add Tag"}
                  </button>
                </div>

                <div className="mt-5">
                  <p className="text-sm font-semibold text-slate-200">Tags</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {(vm.tags || []).length > 0 ? (
                      vm.tags.map((tag) => (
                        <span key={`${tag.key}-${tag.value}`} className="rounded-full bg-white/10 px-3 py-1 text-sm text-white">
                          {tag.key}:{tag.value || ""}
                        </span>
                      ))
                    ) : (
                      <span className="text-sm text-slate-400">No tags yet.</span>
                    )}
                  </div>
                </div>

                <div className="mt-5 grid gap-4 sm:grid-cols-2">
                  <div>
                    <p className="text-xs uppercase tracking-wide text-slate-500">Created at</p>
                    <p className="mt-2 text-white">{formatDateTime(vm.created_at)}</p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-wide text-slate-500">Launched at</p>
                    <p className="mt-2 text-white">{formatDateTime(vm.launched_at)}</p>
                  </div>
                </div>
              </div>

              <div className="rounded-3xl border border-slate-800 bg-slate-900/60 p-5">
                <h3 className="text-lg font-semibold text-white">Attached security groups</h3>
                <div className="mt-4 space-y-4">
                  {attachedSecurityGroups.length > 0 ? (
                    attachedSecurityGroups.map((group) => (
                      <div key={group.id} className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-base font-semibold text-white">{group.name}</p>
                            <p className="text-sm text-slate-400">{group.description || "No description"}</p>
                          </div>
                          <span className="rounded-full bg-cyan-500/20 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-cyan-200">
                            {group.rules?.length || 0} rules
                          </span>
                        </div>
                        <div className="mt-4 space-y-2">
                          {(group.rules || []).map((rule) => (
                            <div key={rule.id} className="rounded-xl border border-slate-800 bg-white/5 px-3 py-2 text-sm text-slate-300">
                              <span className="font-semibold text-white">{rule.direction}</span>
                              <span className="mx-2 text-slate-500">|</span>
                              <span>{rule.protocol}</span>
                              <span className="mx-2 text-slate-500">|</span>
                              <span>port {rule.port_range}</span>
                              <span className="mx-2 text-slate-500">|</span>
                              <span>{rule.source_cidr}</span>
                              <span className="mx-2 text-slate-500">|</span>
                              <span className={rule.action === "allow" ? "text-emerald-300" : "text-rose-300"}>
                                {rule.action}
                              </span>
                            </div>
                          ))}
                          {(group.rules || []).length === 0 && (
                            <p className="text-sm text-slate-400">No rules defined yet.</p>
                          )}
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="text-sm text-slate-400">No security groups attached.</p>
                  )}
                </div>

                <div className="mt-6 rounded-2xl border border-rose-500/30 bg-rose-500/10 p-4">
                  <h4 className="text-sm font-semibold uppercase tracking-wide text-rose-200">Delete VM</h4>
                  <p className="mt-2 text-sm text-rose-100">Type the VM name exactly to confirm deletion.</p>
                  <input
                    value={deleteConfirmation}
                    onChange={(event) => setDeleteConfirmation(event.target.value)}
                    className="mt-3 w-full rounded-xl border border-rose-400/30 bg-slate-950 px-4 py-3 text-white outline-none transition-colors focus:border-rose-300"
                    placeholder={vm.name}
                  />
                  <button
                    type="button"
                    onClick={handleDelete}
                    disabled={!canDelete || busyAction === "delete"}
                    className="mt-3 w-full rounded-xl bg-rose-500 px-4 py-3 font-semibold text-white transition-colors hover:bg-rose-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                  >
                    {busyAction === "delete" ? "Deleting..." : "Delete VM"}
                  </button>
                </div>

                <div className="mt-6 grid grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => runResourceAction("stop", "VM stopped")}
                    disabled={!canManage || vm.status === "stopped" || busyAction === "stop"}
                    className="rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 font-semibold text-white transition-colors hover:border-rose-400 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {busyAction === "stop" ? "Stopping..." : "Stop"}
                  </button>
                  <button
                    type="button"
                    onClick={() => runResourceAction("start", "VM started")}
                    disabled={!canManage || vm.status === "running" || busyAction === "start"}
                    className="rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 font-semibold text-white transition-colors hover:border-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {busyAction === "start" ? "Starting..." : "Start"}
                  </button>
                  <button
                    type="button"
                    onClick={() => runResourceAction("restart", "VM restarting...")}
                    disabled={!canManage || busyAction === "restart"}
                    className="col-span-2 rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 font-semibold text-white transition-colors hover:border-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {busyAction === "restart" ? "Restarting..." : "Restart"}
                  </button>
                </div>
              </div>
            </section>
          </div>
        </div>

        {sidebarOpen ? (
          <aside className="w-full border-t border-slate-800 bg-slate-900/95 px-5 py-5 xl:w-[24rem] xl:border-l xl:border-t-0 xl:px-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.3em] text-cyan-300">Learning Sidebar</p>
                <h3 className="mt-2 text-xl font-bold text-white">VM Detail</h3>
              </div>
              <button
                type="button"
                onClick={() => setSidebarOpen(false)}
                className="rounded-full border border-slate-700 bg-slate-950/80 p-2 text-slate-300 transition-colors hover:border-white hover:text-white"
                aria-label="Collapse learning sidebar"
              >
                <ChevronDownIcon className="h-5 w-5" />
              </button>
            </div>
            <div className="mt-5 max-h-[calc(100vh-8.5rem)] overflow-y-auto pr-1">
              {learningLoading && (
                <div className="rounded-2xl border border-dashed border-slate-700 px-4 py-6 text-sm text-slate-400">
                  Loading learning content...
                </div>
              )}
              {!learningLoading && learningError && (
                <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
                  {learningError}
                </div>
              )}
              {!learningLoading && learningContent && (
                <div className="space-y-4">
                  <div className="flex flex-wrap gap-2">
                    <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-950">AWS</span>
                    <span className="rounded-full bg-sky-500 px-3 py-1 text-xs font-semibold text-white">Azure</span>
                    <span className="rounded-full bg-cyan-500/20 px-3 py-1 text-xs font-semibold text-cyan-100">
                      {String(learningContent.difficulty || "beginner").replace(/^\w/, (char) => char.toUpperCase())}
                    </span>
                  </div>
                  <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4">
                    <p className="text-xs uppercase tracking-wide text-slate-500">AWS Equivalent</p>
                    <p className="mt-1 text-sm font-semibold text-white">{learningContent.aws_equivalent}</p>
                    <p className="mt-4 text-xs uppercase tracking-wide text-slate-500">Azure Equivalent</p>
                    <p className="mt-1 text-sm font-semibold text-white">{learningContent.azure_equivalent}</p>
                  </div>
                  <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4">
                    <p className="text-xs uppercase tracking-wide text-slate-500">What You Just Did</p>
                    <p className="mt-2 text-sm text-slate-200">{learningContent.what_you_just_did}</p>
                  </div>
                  <div className="rounded-2xl border border-cyan-500/30 bg-cyan-500/10 p-4">
                    <p className="text-xs uppercase tracking-wide text-cyan-200">Key Concept</p>
                    <p className="mt-2 text-sm text-cyan-50">{learningContent.key_concept}</p>
                  </div>
                  <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4">
                    <p className="text-xs uppercase tracking-wide text-amber-200">Best Practice</p>
                    <p className="mt-2 text-sm text-amber-50">{learningContent.best_practice}</p>
                  </div>
                  <div className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4">
                    <p className="text-xs uppercase tracking-wide text-slate-500">Next Step</p>
                    <p className="mt-2 text-sm text-slate-200">{learningContent.next_step}</p>
                  </div>
                </div>
              )}
            </div>
          </aside>
        ) : (
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            className="absolute right-0 top-1/2 -translate-y-1/2 rounded-l-2xl border border-slate-700 bg-slate-900 px-3 py-4 text-sm font-semibold text-slate-200 shadow-xl transition-colors hover:border-cyan-400 hover:text-white"
          >
            Learning
          </button>
        )}
      </div>
    </div>
  );
};

const Resources = () => {
  const { token } = useSelector((state) => state.auth);
  const { currentOrganization } = useSelector((state) => state.organization);

  const [resources, setResources] = useState([]);
  const [securityGroups, setSecurityGroups] = useState([]);
  const [loading, setLoading] = useState(false);
  const [securityGroupsLoading, setSecurityGroupsLoading] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createMode, setCreateMode] = useState("vm");
  const [selectedVM, setSelectedVM] = useState(null);
  const [activeTab, setActiveTab] = useState("resources");
  const [selectedSecurityGroupIds, setSelectedSecurityGroupIds] = useState([]);
  const [newVM, setNewVM] = useState({
    name: "",
    engine: "PostgreSQL",
    instance_type: "t2.micro",
  });
  const [newSecurityGroup, setNewSecurityGroup] = useState({
    name: "",
    description: "",
  });
  const [newSecurityRule, setNewSecurityRule] = useState({
    direction: "inbound",
    protocol: "TCP",
    port_range: "22",
    source_cidr: "0.0.0.0/0",
    action: "allow",
    description: "",
    group_id: "",
  });
  const [editingSecurityRule, setEditingSecurityRule] = useState(null);
  const [wasteCandidateVmIds, setWasteCandidateVmIds] = useState([]);
  const [learningActionKey, setLearningActionKey] = useState(null);
  const pollTimerRef = useRef(null);
  const fastPollUntilRef = useRef(0);
  const cleanedOrgIdRef = useRef(null);
  const socketRef = useRef(null);
  const activeOrgIdRef = useRef(currentOrganization?.id ?? null);

  const authHeaders = useMemo(
    () => (token ? { Authorization: `Bearer ${token}` } : {}),
    [token],
  );

  const defaultSecurityGroupIds = useMemo(() => {
    const defaults = securityGroups.filter(
      (group) => group?.name === "default",
    );
    if (defaults.length > 0) {
      return defaults.map((group) => group.id);
    }
    return securityGroups.length > 0 ? [securityGroups[0].id] : [];
  }, [securityGroups]);

  useEffect(() => {
    activeOrgIdRef.current = currentOrganization?.id ?? null;
  }, [currentOrganization?.id]);

  const loadResources = useCallback(
    async (cacheBust = Date.now()) => {
      if (!token) {
        setResources([]);
        return;
      }

      setLoading(true);
      try {
        const response = await axios.get(`${API_URL}/resources`, {
          headers: authHeaders,
          params: {
            organization_id: currentOrganization?.id,
            _ts: cacheBust,
          },
        });
        const payload = response?.data?.data;
        setResources(Array.isArray(payload) ? payload : []);
      } catch (error) {
        setResources([]);
        toast.error(
          error?.response?.data?.error?.message || "Something went wrong",
        );
      } finally {
        setLoading(false);
      }
    },
    [authHeaders, currentOrganization?.id, token],
  );

  const loadSecurityGroups = useCallback(
    async (cacheBust = Date.now()) => {
      if (!token) {
        setSecurityGroups([]);
        return;
      }

      setSecurityGroupsLoading(true);
      try {
        const response = await axios.get(
          `${API_URL}/resources/security-groups`,
          {
            headers: authHeaders,
            params: {
              organization_id: currentOrganization?.id,
              _ts: cacheBust,
            },
          },
        );
        const payload = response?.data?.data;
        setSecurityGroups(Array.isArray(payload) ? payload : []);
      } catch (error) {
        setSecurityGroups([]);
        toast.error(
          error?.response?.data?.error?.message || "Something went wrong",
        );
      } finally {
        setSecurityGroupsLoading(false);
      }
    },
    [authHeaders, currentOrganization?.id, token],
  );

  const updateResourceInState = useCallback((updatedResource) => {
    if (!updatedResource) return;
    setResources((prev) =>
      prev.map((resource) =>
        resource?.id === updatedResource.id ? updatedResource : resource,
      ),
    );
    setSelectedVM((prev) =>
      prev?.id === updatedResource.id ? updatedResource : prev,
    );
  }, []);

  const removeResourceFromState = useCallback((resourceId) => {
    setResources((prev) => prev.filter((resource) => resource?.id !== resourceId));
    setSelectedVM((prev) => (prev?.id === resourceId ? null : prev));
  }, []);

  useEffect(() => {
    if (!token) return undefined;
    let cancelled = false;

    const scheduleNext = async () => {
      await loadResources();
      if (cancelled) return;
      const delay = Date.now() < fastPollUntilRef.current ? 2000 : 5000;
      pollTimerRef.current = window.setTimeout(scheduleNext, delay);
    };

    scheduleNext();

    return () => {
      cancelled = true;
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
      }
    };
  }, [loadResources, token]);

  useEffect(() => {
    if (!token) return undefined;
    loadSecurityGroups();
    return undefined;
  }, [loadSecurityGroups, token]);

  useEffect(() => {
    if (!token || !currentOrganization?.id) return undefined;

    const socket = createSocket("/metrics");
    if (!socket) return undefined;

    socketRef.current = socket;

    const handleConnect = () => {
      const latestOrgId = activeOrgIdRef.current;
      if (!latestOrgId) return;
      socket.emit("join_room", { org_id: latestOrgId });
    };

    const handleVmCreated = (resource) => {
      const latestOrgId = activeOrgIdRef.current;
      const resourceOrgId = resource?.org_id ?? resource?.organization_id ?? null;
      if (resourceOrgId !== null && resourceOrgId !== latestOrgId) return;
      if (!resource?.id) return;
      updateResourceInState(resource);
    };

    const handleVmUpdated = (resource) => {
      const latestOrgId = activeOrgIdRef.current;
      const resourceOrgId = resource?.org_id ?? resource?.organization_id ?? null;
      if (resourceOrgId !== null && resourceOrgId !== latestOrgId) return;
      if (!resource?.id) return;
      updateResourceInState(resource);
    };

    const handleVmDeleted = (resource) => {
      const latestOrgId = activeOrgIdRef.current;
      const resourceOrgId = resource?.org_id ?? resource?.organization_id ?? null;
      if (resourceOrgId !== null && resourceOrgId !== latestOrgId) return;
      const resourceId = resource?.id ?? resource?.instance_id ?? null;
      if (!resourceId) return;
      removeResourceFromState(resourceId);
    };

    socket.on("connect", handleConnect);
    socket.on("vm_created", handleVmCreated);
    socket.on("vm_updated", handleVmUpdated);
    socket.on("vm_deleted", handleVmDeleted);
    if (socket.connected) {
      handleConnect();
    }

    return () => {
      socket.off("connect", handleConnect);
      socket.off("vm_created", handleVmCreated);
      socket.off("vm_updated", handleVmUpdated);
      socket.off("vm_deleted", handleVmDeleted);
      socketRef.current = null;
    };
  }, [
    currentOrganization?.id,
    loadResources,
    loadSecurityGroups,
    removeResourceFromState,
    token,
    updateResourceInState,
  ]);

  useEffect(() => {
    if (
      !token ||
      !currentOrganization?.id ||
      cleanedOrgIdRef.current === currentOrganization.id
    )
      return undefined;
    cleanedOrgIdRef.current = currentOrganization.id;

    const cleanupPending = async () => {
      try {
        await axios.post(
          `${API_URL}/resources/cleanup-pending`,
          {},
          {
            headers: authHeaders,
            params: { organization_id: currentOrganization.id },
          },
        );
      } catch (error) {
        toast.error(
          error?.response?.data?.error?.message || "Something went wrong",
        );
      } finally {
        await loadResources(Date.now());
      }
    };

    cleanupPending();
    return undefined;
  }, [authHeaders, currentOrganization?.id, loadResources, token]);

  useEffect(() => {
    setWasteCandidateVmIds((prev) =>
      prev.filter((vmId) =>
        resources.some((resource) => resource?.id === vmId),
      ),
    );
  }, [resources]);

  useEffect(() => {
    if (!showCreateModal || createMode !== "vm") return;
    if (
      selectedSecurityGroupIds.length === 0 &&
      defaultSecurityGroupIds.length > 0
    ) {
      setSelectedSecurityGroupIds(defaultSecurityGroupIds);
    }
  }, [
    createMode,
    defaultSecurityGroupIds,
    selectedSecurityGroupIds.length,
    showCreateModal,
  ]);

  const handleCreateResource = async (e) => {
    e.preventDefault();

    try {
      if (createMode === "vm" && selectedSecurityGroupIds.length === 0) {
        toast.error("Select at least one security group");
        return;
      }

      const payload = {
        name: newVM?.name,
        type: createMode,
        organization_id: currentOrganization?.id,
      };

      if (createMode === "database") {
        payload.engine = newVM?.engine;
      } else {
        payload.instance_type = newVM?.instance_type;
        payload.security_group_ids = selectedSecurityGroupIds;
      }

      const response = await axios.post(
        `${API_URL}/resources/create?type=${createMode}`,
        payload,
        { headers: authHeaders },
      );

      const created = response?.data?.data || {};
      fastPollUntilRef.current = Date.now() + 30000;
      await loadResources(Date.now());
      await loadSecurityGroups(Date.now());
      setSelectedVM(created);
      setLearningActionKey(createMode === "vm" ? "vm_created" : null);
      setShowCreateModal(false);
      setNewVM({ name: "", engine: "PostgreSQL", instance_type: "t2.micro" });
      setSelectedSecurityGroupIds([]);

      // Award XP for resource creation (backend defines points via XP_RULES)
      const actionType = createMode === "vm" ? "vm_created" : "db_created";
      try {
        await axios.post(
          `${API_URL}/progress/award`,
          { action: actionType, org_id: currentOrganization?.id },
          { headers: authHeaders },
        );
      } catch (awardError) {
        console.error("Failed to award XP:", awardError);
      }

      toast.success(
        createMode === "database"
          ? "Database created successfully"
          : "VM created successfully",
      );
    } catch (error) {
      toast.error(
        error?.response?.data?.error?.message || "Something went wrong",
      );
    }
  };

  const handleDeleteVM = async (resource) => {
    const resourceId = selectedVM?.id || resource?.id;
    if (!resourceId) return;

    try {
      await axios.delete(`${API_URL}/resources/${resourceId}`, {
        headers: authHeaders,
      });
      setResources((prev) => prev.filter((item) => item?.id !== resourceId));
      if (selectedVM?.id === resourceId) {
        setSelectedVM(null);
      }
      // Award XP for resource deletion (backend defines points via XP_RULES)
      try {
        await axios.post(
          `${API_URL}/progress/award`,
          { action: "resource_deleted", org_id: currentOrganization?.id },
          { headers: authHeaders },
        );
      } catch (awardError) {
        console.error("Failed to award XP:", awardError);
      }
      toast.success("VM deleted");
    } catch (error) {
      toast.error(
        error?.response?.data?.error?.message || "Something went wrong",
      );
    }
  };

  const handleStopVM = async (resource) => {
    const resourceId = selectedVM?.id || resource?.id;
    if (!resourceId) return;

    try {
      const response = await axios.post(
        `${API_URL}/resources/${resourceId}/stop`,
        {},
        { headers: authHeaders },
      );

      const updated = response?.data?.data || {};
      setResources((prev) =>
        prev.map((item) => (item?.id === resourceId ? updated : item)),
      );
      if (selectedVM?.id === resourceId) {
        setSelectedVM(updated);
      }
      toast.success("VM stopped");
    } catch (error) {
      toast.error(
        error?.response?.data?.error?.message || "Something went wrong",
      );
    }
  };

  const handleStartVM = async (resource) => {
    const resourceId = resource?.id;
    if (!resourceId) return;

    try {
      const response = await axios.post(
        `${API_URL}/resources/${resourceId}/start`,
        {},
        { headers: authHeaders },
      );

      const updated = response?.data?.data || {};
      setResources((prev) =>
        prev.map((item) => (item?.id === resourceId ? updated : item)),
      );
      if (selectedVM?.id === resourceId) {
        setSelectedVM(updated);
      }
      toast.success("Resource started");
    } catch (error) {
      toast.error(
        error?.response?.data?.error?.message || "Something went wrong",
      );
    }
  };

  const handleRestartVM = async (resource) => {
    const resourceId = resource?.id;
    if (!resourceId) return;

    try {
      const response = await axios.post(
        `${API_URL}/resources/${resourceId}/restart`,
        {},
        { headers: authHeaders },
      );

      const updated = response?.data?.data || {};
      setResources((prev) =>
        prev.map((item) => (item?.id === resourceId ? updated : item)),
      );
      if (selectedVM?.id === resourceId) {
        setSelectedVM(updated);
      }
      toast.success("Resource restarting...");
    } catch (error) {
      toast.error(
        error?.response?.data?.error?.message || "Something went wrong",
      );
    }
  };

  const handleCreateSecurityGroup = async (e) => {
    e.preventDefault();
    if (!newSecurityGroup.name.trim()) {
      toast.error("Security group name is required");
      return;
    }

    try {
      await axios.post(
        `${API_URL}/resources/security-groups`,
        {
          organization_id: currentOrganization?.id,
          name: newSecurityGroup.name,
          description: newSecurityGroup.description,
        },
        { headers: authHeaders },
      );
      setNewSecurityGroup({ name: "", description: "" });
      await loadSecurityGroups(Date.now());
      setLearningActionKey("security_group_created");
      toast.success("Security group created");
    } catch (error) {
      toast.error(
        error?.response?.data?.error?.message || "Something went wrong",
      );
    }
  };

  const handleAddSecurityGroupRule = async (e) => {
    e.preventDefault();
    if (!newSecurityRule.group_id) {
      toast.error("Choose a security group");
      return;
    }
    try {
      await axios.post(
        `${API_URL}/resources/security-groups/${newSecurityRule.group_id}/rules`,
        {
          direction: newSecurityRule.direction,
          protocol: newSecurityRule.protocol,
          port_range: newSecurityRule.port_range,
          source_cidr: newSecurityRule.source_cidr,
          action: newSecurityRule.action,
          description: newSecurityRule.description,
        },
        { headers: authHeaders },
      );
      setNewSecurityRule({
        direction: "inbound",
        protocol: "TCP",
        port_range: "22",
        source_cidr: "0.0.0.0/0",
        action: "allow",
        description: "",
        group_id: newSecurityRule.group_id,
      });
      await loadSecurityGroups(Date.now());
      toast.success("Rule added");
    } catch (error) {
      toast.error(
        error?.response?.data?.error?.message || "Something went wrong",
      );
    }
  };

  const handleUpdateSecurityGroupRule = async (e) => {
    e.preventDefault();
    if (!editingSecurityRule) return;

    try {
      await axios.put(
        `${API_URL}/resources/security-groups/${editingSecurityRule.group_id}/rules/${editingSecurityRule.id}`,
        {
          direction: editingSecurityRule.direction,
          protocol: editingSecurityRule.protocol,
          port_range: editingSecurityRule.port_range,
          source_cidr: editingSecurityRule.source_cidr,
          action: editingSecurityRule.action,
          description: editingSecurityRule.description,
        },
        { headers: authHeaders },
      );
      setEditingSecurityRule(null);
      localStorage.setItem("scenario:security_group_rule_modified", "true");
      await loadSecurityGroups(Date.now());
      toast.success("Rule updated");
    } catch (error) {
      toast.error(
        error?.response?.data?.error?.message || "Something went wrong",
      );
    }
  };

  const handleDeleteSecurityGroupRule = async (groupId, ruleId) => {
    try {
      await axios.delete(
        `${API_URL}/resources/security-groups/${groupId}/rules/${ruleId}`,
        { headers: authHeaders },
      );
      await loadSecurityGroups(Date.now());
      toast.success("Rule deleted");
    } catch (error) {
      toast.error(
        error?.response?.data?.error?.message || "Something went wrong",
      );
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Resources
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Selected VM: {selectedVM?.name || "None"} ({selectedVM?.id || "n/a"}
            )
          </p>
        </div>
        {currentOrganization?.my_role !== "viewer" && (
          <>
            <button
              onClick={() => {
                setCreateMode("database");
                setShowCreateModal(true);
                setSelectedSecurityGroupIds([]);
              }}
              className="btn-secondary flex items-center space-x-2"
            >
              <CircleStackIcon className="w-5 h-5" />
              <span>Create DB</span>
            </button>
            <button
              onClick={() => {
                setCreateMode("vm");
                setShowCreateModal(true);
                setSelectedSecurityGroupIds(defaultSecurityGroupIds);
              }}
              className="btn-primary flex items-center space-x-2"
            >
              <PlusIcon className="w-5 h-5" />
              <span>Create VM</span>
            </button>
          </>
        )}
      </div>

      <div className="flex items-center space-x-2 border-b border-gray-200 dark:border-gray-700">
        <button
          type="button"
          onClick={() => setActiveTab("resources")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "resources"
              ? "border-primary-600 text-primary-600"
              : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
          }`}
        >
          Resources
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("security-groups")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeTab === "security-groups"
              ? "border-primary-600 text-primary-600"
              : "border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
          }`}
        >
          Security Groups
        </button>
      </div>

      {activeTab === "resources" ? (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {resources?.map((resource) => {
              const safeId = resource?.id || "fallback-id";
              const status = (resource?.status || "").toLowerCase();
              const cpuPercent = Number(
                resource?.cpu_percent ?? resource?.cpu ?? 0,
              );
              const memoryPercent = Number(
                resource?.memory_percent ?? resource?.memory ?? 0,
              );
              const isAutoScaled = (resource?.name || "").includes("-scaled-");
              const isWasteCandidate = wasteCandidateVmIds.includes(
                resource?.id,
              );

              return (
                <div
                  key={safeId}
                  className={`card p-6 flex flex-col hover:border-primary-500 transition-colors border border-transparent ${resource?.type === "vm" ? "cursor-pointer" : "cursor-default"}`}
                  onClick={() => {
                    if (resource?.type === "vm") {
                      setSelectedVM(resource || null);
                    }
                  }}
                >
                  <div className="flex justify-between items-start mb-4">
                    <div className="flex items-center">
                      <ServerIcon className="w-6 h-6 text-gray-400 mr-3" />
                      <div>
                        <h3 className="text-lg font-medium text-gray-900 dark:text-white">
                          {resource?.name || "Unnamed resource"}
                        </h3>
                        <p className="text-sm text-gray-500 dark:text-gray-400">
                          {resource?.type === "database"
                            ? `Database (${resource?.engine || "DB"})`
                            : "Virtual Machine"}
                        </p>
                      </div>
                    </div>
                    <div className="flex flex-wrap justify-end gap-2">
                      <span
                        className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${statusClass(status)}`}
                      >
                        {status || "unknown"}
                      </span>
                      {isAutoScaled && (
                        <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400">
                          Auto Scaled
                        </span>
                      )}
                      {isWasteCandidate && (
                        <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400">
                          Low utilization - consider stopping
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="space-y-4 mb-4 flex-1 mt-2">
                    <div>
                      <div className="flex justify-between text-sm mb-1 text-gray-700 dark:text-gray-300">
                        <span>CPU Usage</span>
                        <span className="font-medium">{cpuPercent}%</span>
                      </div>
                      <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
                        <div
                          className="bg-primary-600 h-2 rounded-full"
                          style={{ width: `${cpuPercent}%` }}
                        />
                      </div>
                    </div>
                    <div>
                      <div className="flex justify-between text-sm mb-1 text-gray-700 dark:text-gray-300">
                        <span>Memory Usage</span>
                        <span className="font-medium">{memoryPercent}%</span>
                      </div>
                      <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
                        <div
                          className="bg-primary-600 h-2 rounded-full"
                          style={{ width: `${memoryPercent}%` }}
                        />
                      </div>
                    </div>
                    {Array.isArray(resource?.security_groups) &&
                      resource.security_groups.length > 0 && (
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
                            Security Groups
                          </p>
                          <div className="flex flex-wrap gap-2">
                            {resource.security_groups.map((group) => (
                              <span
                                key={group.id}
                                className="inline-flex items-center px-2 py-1 rounded-full text-xs bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-300"
                              >
                                {group.name}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                  </div>

                  <div className="flex justify-end space-x-3 pt-4 border-t border-gray-100 dark:border-gray-700 mt-auto">
                    {currentOrganization?.my_role !== "viewer" &&
                      status === "stopped" && (
                        <button
                          onClick={(event) => {
                            event.stopPropagation();
                            handleStartVM(resource);
                          }}
                          className="p-2 text-success-600 hover:bg-success-50 dark:hover:bg-success-900/20 rounded-lg transition-colors"
                          title="Start Resource"
                        >
                          <PlayIcon className="w-5 h-5" />
                        </button>
                      )}
                    {currentOrganization?.my_role !== "viewer" &&
                      status === "running" && (
                        <button
                          onClick={(event) => {
                            event.stopPropagation();
                            handleRestartVM(resource);
                          }}
                          className="p-2 text-primary-600 hover:bg-primary-50 dark:hover:bg-primary-900/20 rounded-lg transition-colors"
                          title="Restart Resource"
                        >
                          <ArrowPathIcon className="w-5 h-5" />
                        </button>
                      )}
                    {currentOrganization?.my_role !== "viewer" &&
                      status === "running" && (
                        <button
                          onClick={(event) => {
                            event.stopPropagation();
                            handleStopVM(resource);
                          }}
                          className="p-2 text-warning-600 hover:bg-warning-50 dark:hover:bg-warning-900/20 rounded-lg transition-colors"
                          title="Stop Resource"
                        >
                          <StopIcon className="w-5 h-5" />
                        </button>
                      )}
                    {(currentOrganization?.my_role === "admin" ||
                      currentOrganization?.my_role === "owner") && (
                      <button
                        onClick={(event) => {
                          event.stopPropagation();
                          handleDeleteVM(resource);
                        }}
                        className="p-2 text-danger-600 hover:bg-danger-50 dark:hover:bg-danger-900/20 rounded-lg transition-colors"
                        title="Delete Resource"
                      >
                        <TrashIcon className="w-5 h-5" />
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
            {resources?.length === 0 && !loading && (
              <div className="col-span-full py-16 text-center bg-white dark:bg-gray-800 rounded-xl border border-dashed border-gray-300 dark:border-gray-700 shadow-sm">
                <ServerIcon className="mx-auto h-12 w-12 text-gray-400 mb-4" />
                <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-1">
                  No resources yet
                </h3>
                <p className="text-gray-500 dark:text-gray-400">
                  Create your first VM or Database to get started.
                </p>
              </div>
            )}
            {loading && (
              <div className="col-span-full py-16 text-center text-gray-500 dark:text-gray-400">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600 mx-auto mb-4"></div>
                Loading resources...
              </div>
            )}
          </div>

          <VmDetailModal
            vm={selectedVM}
            open={Boolean(selectedVM)}
            onClose={() => setSelectedVM(null)}
            securityGroups={securityGroups}
            authHeaders={authHeaders}
            currentOrganizationId={currentOrganization?.id}
            currentRole={currentOrganization?.my_role}
            onResourceUpdated={updateResourceInState}
            onResourceDeleted={removeResourceFromState}
          />
        </>
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
            <div className="card p-6 xl:col-span-1">
              {currentOrganization?.my_role !== "viewer" ? (
                <>
                  <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                    Create Security Group
                  </h2>
                  <form
                    onSubmit={handleCreateSecurityGroup}
                    className="space-y-4"
                  >
                    <div>
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Name
                      </label>
                      <input
                        type="text"
                        className="input-field"
                        value={newSecurityGroup.name}
                        onChange={(event) =>
                          setNewSecurityGroup({
                            ...newSecurityGroup,
                            name: event.target.value,
                          })
                        }
                        placeholder="web-prod"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Description
                      </label>
                      <textarea
                        className="input-field min-h-[96px]"
                        value={newSecurityGroup.description}
                        onChange={(event) =>
                          setNewSecurityGroup({
                            ...newSecurityGroup,
                            description: event.target.value,
                          })
                        }
                        placeholder="Describe the purpose of this security group"
                      />
                    </div>
                    <button type="submit" className="btn-primary w-full">
                      Create Group
                    </button>
                  </form>
                </>
              ) : (
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Viewers can inspect security groups, but cannot create or
                  modify them.
                </p>
              )}
            </div>

            <div className="card p-6 xl:col-span-2">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Security Groups
                </h2>
                {securityGroupsLoading && (
                  <span className="text-sm text-gray-500 dark:text-gray-400">
                    Refreshing...
                  </span>
                )}
              </div>
              <div className="space-y-4">
                {securityGroups.map((group) => (
                  <div
                    key={group.id}
                    className="rounded-xl border border-gray-200 dark:border-gray-700 p-4"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <h3 className="font-semibold text-gray-900 dark:text-white">
                          {group.name}
                        </h3>
                        <p className="text-sm text-gray-500 dark:text-gray-400">
                          {group.description || "No description"}
                        </p>
                      </div>
                      <div className="text-xs text-gray-500 dark:text-gray-400 text-right">
                        <div>{group.rule_count || 0} rules</div>
                        <div>{group.vm_count || 0} VMs</div>
                      </div>
                    </div>
                    <div className="mt-4 space-y-2">
                      {(group.rules || []).map((rule) => (
                        <div
                          key={rule.id}
                          className="flex flex-col md:flex-row md:items-center md:justify-between gap-2 rounded-lg bg-gray-50 dark:bg-gray-800 px-3 py-2"
                        >
                          <div className="text-sm text-gray-700 dark:text-gray-300">
                            <span className="font-medium text-gray-900 dark:text-white">
                              {rule.direction}
                            </span>{" "}
                            | {rule.protocol} | port {rule.port_range} |{" "}
                            {rule.source_cidr}
                          </div>
                          <div className="flex items-center gap-3">
                            <span
                              className={`text-xs px-2 py-1 rounded-full ${rule.action === "allow" ? "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-300" : "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-300"}`}
                            >
                              {rule.action}
                            </span>
                            {(currentOrganization?.my_role === "admin" ||
                              currentOrganization?.my_role === "owner") && (
                              <div className="flex items-center gap-2">
                                <button
                                  type="button"
                                  onClick={() =>
                                    setEditingSecurityRule({
                                      ...rule,
                                      group_id: group.id,
                                    })
                                  }
                                  className="text-xs text-primary-600 hover:underline"
                                >
                                  Edit
                                </button>
                                <button
                                  type="button"
                                  onClick={() =>
                                    handleDeleteSecurityGroupRule(
                                      group.id,
                                      rule.id,
                                    )
                                  }
                                  className="text-xs text-danger-600 hover:underline"
                                >
                                  Delete
                                </button>
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                      {(group.rules || []).length === 0 && (
                        <p className="text-sm text-gray-500 dark:text-gray-400">
                          No rules defined yet.
                        </p>
                      )}
                    </div>
                  </div>
                ))}
                {securityGroups.length === 0 && !securityGroupsLoading && (
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    No security groups found for this organization.
                  </p>
                )}
              </div>
            </div>
          </div>

          {currentOrganization?.my_role !== "viewer" && (
            <div className="card p-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                Add Rule
              </h2>
              <form
                onSubmit={handleAddSecurityGroupRule}
                className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-6 gap-4"
              >
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Security Group
                  </label>
                  <select
                    className="input-field"
                    value={newSecurityRule.group_id}
                    onChange={(event) =>
                      setNewSecurityRule({
                        ...newSecurityRule,
                        group_id: event.target.value,
                      })
                    }
                  >
                    <option value="">Select group</option>
                    {securityGroups.map((group) => (
                      <option key={group.id} value={group.id}>
                        {group.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Direction
                  </label>
                  <select
                    className="input-field"
                    value={newSecurityRule.direction}
                    onChange={(event) =>
                      setNewSecurityRule({
                        ...newSecurityRule,
                        direction: event.target.value,
                      })
                    }
                  >
                    <option value="inbound">Inbound</option>
                    <option value="outbound">Outbound</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Protocol
                  </label>
                  <select
                    className="input-field"
                    value={newSecurityRule.protocol}
                    onChange={(event) =>
                      setNewSecurityRule({
                        ...newSecurityRule,
                        protocol: event.target.value,
                      })
                    }
                  >
                    <option value="TCP">TCP</option>
                    <option value="UDP">UDP</option>
                    <option value="ICMP">ICMP</option>
                    <option value="All">All</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Port Range
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    value={newSecurityRule.port_range}
                    onChange={(event) =>
                      setNewSecurityRule({
                        ...newSecurityRule,
                        port_range: event.target.value,
                      })
                    }
                    placeholder="22 or 80-443"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Source CIDR
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    value={newSecurityRule.source_cidr}
                    onChange={(event) =>
                      setNewSecurityRule({
                        ...newSecurityRule,
                        source_cidr: event.target.value,
                      })
                    }
                    placeholder="0.0.0.0/0"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Action
                  </label>
                  <select
                    className="input-field"
                    value={newSecurityRule.action}
                    onChange={(event) =>
                      setNewSecurityRule({
                        ...newSecurityRule,
                        action: event.target.value,
                      })
                    }
                  >
                    <option value="allow">Allow</option>
                    <option value="deny">Deny</option>
                  </select>
                </div>
                <div className="md:col-span-2 xl:col-span-6">
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Description
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    value={newSecurityRule.description}
                    onChange={(event) =>
                      setNewSecurityRule({
                        ...newSecurityRule,
                        description: event.target.value,
                      })
                    }
                    placeholder="Optional description"
                  />
                </div>
                <div className="md:col-span-2 xl:col-span-6 flex justify-end">
                  <button type="submit" className="btn-primary">
                    Add Rule
                  </button>
                </div>
              </form>
            </div>
          )}
        </div>
      )}

      {editingSecurityRule && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
            <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">
              Edit Security Group Rule
            </h2>
            <form
              onSubmit={handleUpdateSecurityGroupRule}
              className="space-y-4"
            >
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Direction
                  </label>
                  <select
                    className="input-field"
                    value={editingSecurityRule.direction}
                    onChange={(event) =>
                      setEditingSecurityRule({
                        ...editingSecurityRule,
                        direction: event.target.value,
                      })
                    }
                  >
                    <option value="inbound">Inbound</option>
                    <option value="outbound">Outbound</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Action
                  </label>
                  <select
                    className="input-field"
                    value={editingSecurityRule.action}
                    onChange={(event) =>
                      setEditingSecurityRule({
                        ...editingSecurityRule,
                        action: event.target.value,
                      })
                    }
                  >
                    <option value="allow">Allow</option>
                    <option value="deny">Deny</option>
                  </select>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Protocol
                  </label>
                  <select
                    className="input-field"
                    value={editingSecurityRule.protocol}
                    onChange={(event) =>
                      setEditingSecurityRule({
                        ...editingSecurityRule,
                        protocol: event.target.value,
                      })
                    }
                  >
                    <option value="TCP">TCP</option>
                    <option value="UDP">UDP</option>
                    <option value="ICMP">ICMP</option>
                    <option value="All">All</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Port Range
                  </label>
                  <input
                    className="input-field"
                    value={editingSecurityRule.port_range}
                    onChange={(event) =>
                      setEditingSecurityRule({
                        ...editingSecurityRule,
                        port_range: event.target.value,
                      })
                    }
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Source CIDR
                </label>
                <input
                  className="input-field"
                  value={editingSecurityRule.source_cidr}
                  onChange={(event) =>
                    setEditingSecurityRule({
                      ...editingSecurityRule,
                      source_cidr: event.target.value,
                    })
                  }
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Description
                </label>
                <input
                  className="input-field"
                  value={editingSecurityRule.description || ""}
                  onChange={(event) =>
                    setEditingSecurityRule({
                      ...editingSecurityRule,
                      description: event.target.value,
                    })
                  }
                />
              </div>
              <div className="flex justify-end space-x-3 pt-4">
                <button
                  type="button"
                  onClick={() => setEditingSecurityRule(null)}
                  className="btn-secondary"
                >
                  Cancel
                </button>
                <button type="submit" className="btn-primary">
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {learningActionKey && (
        <LearningPanel
          action_key={learningActionKey}
          onClose={() => setLearningActionKey(null)}
        />
      )}

      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 w-full max-w-md mx-4">
            <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">
              {createMode === "database"
                ? "Create Database"
                : "Create Virtual Machine"}
            </h2>
            <form onSubmit={handleCreateResource} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  {createMode === "database" ? "Database Name" : "VM Name"}
                </label>
                <input
                  type="text"
                  className="input-field"
                  value={newVM?.name || ""}
                  onChange={(event) =>
                    setNewVM({ ...newVM, name: event.target.value })
                  }
                  placeholder={
                    createMode === "database"
                      ? "e.g., analytics-db"
                      : "e.g., web-server-01"
                  }
                />
              </div>
              {createMode === "database" ? (
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Engine
                  </label>
                  <select
                    className="input-field"
                    value={newVM?.engine || "PostgreSQL"}
                    onChange={(event) =>
                      setNewVM({ ...newVM, engine: event.target.value })
                    }
                  >
                    <option value="PostgreSQL">PostgreSQL</option>
                    <option value="MySQL">MySQL</option>
                    <option value="MongoDB">MongoDB</option>
                  </select>
                </div>
              ) : (
                <>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      VM Size
                    </label>
                    <select
                      className="input-field"
                      value={newVM?.instance_type || "t2.micro"}
                      onChange={(event) =>
                        setNewVM({
                          ...newVM,
                          instance_type: event.target.value,
                        })
                      }
                    >
                      <option value="t2.micro">t2.micro (1 CPU, 1 GB)</option>
                      <option value="t2.small">t2.small (1 CPU, 2 GB)</option>
                      <option value="t2.medium">t2.medium (2 CPU, 4 GB)</option>
                      <option value="t2.large">t2.large (2 CPU, 8 GB)</option>
                      <option value="t2.xlarge">
                        t2.xlarge (4 CPU, 16 GB)
                      </option>
                    </select>
                  </div>
                  <div className="flex space-x-4">
                    <div className="flex-1">
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                        CPU
                      </label>
                      <input
                        type="text"
                        className="input-field bg-gray-100 dark:bg-gray-700 text-gray-500 cursor-not-allowed"
                        disabled
                        value={
                          newVM?.instance_type === "t2.xlarge"
                            ? "4 Core"
                            : newVM?.instance_type === "t2.large" ||
                                newVM?.instance_type === "t2.medium"
                              ? "2 Core"
                              : "1 Core"
                        }
                      />
                    </div>
                    <div className="flex-1">
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Memory
                      </label>
                      <input
                        type="text"
                        className="input-field bg-gray-100 dark:bg-gray-700 text-gray-500 cursor-not-allowed"
                        disabled
                        value={
                          newVM?.instance_type === "t2.xlarge"
                            ? "16 GB"
                            : newVM?.instance_type === "t2.large"
                              ? "8 GB"
                              : newVM?.instance_type === "t2.medium"
                                ? "4 GB"
                                : newVM?.instance_type === "t2.small"
                                  ? "2 GB"
                                  : "1 GB"
                        }
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                      Security Groups
                    </label>
                    <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
                      {securityGroups.map((group) => {
                        const checked = selectedSecurityGroupIds.includes(
                          group.id,
                        );
                        return (
                          <label
                            key={group.id}
                            className={`flex items-start gap-3 rounded-lg border p-3 cursor-pointer transition-colors ${
                              checked
                                ? "border-primary-500 bg-primary-50 dark:border-primary-400 dark:bg-primary-900/20"
                                : "border-gray-200 dark:border-gray-700"
                            }`}
                          >
                            <input
                              type="checkbox"
                              className="mt-1"
                              checked={checked}
                              onChange={(event) => {
                                if (event.target.checked) {
                                  setSelectedSecurityGroupIds((prev) => [
                                    ...new Set([...prev, group.id]),
                                  ]);
                                } else {
                                  setSelectedSecurityGroupIds((prev) =>
                                    prev.filter((id) => id !== group.id),
                                  );
                                }
                              }}
                            />
                            <div>
                              <div className="font-medium text-gray-900 dark:text-white">
                                {group.name}
                              </div>
                              <div className="text-xs text-gray-500 dark:text-gray-400">
                                {group.description || "No description"} |{" "}
                                {group.rule_count || 0} rules
                              </div>
                            </div>
                          </label>
                        );
                      })}
                      {securityGroups.length === 0 &&
                        !securityGroupsLoading && (
                          <p className="text-sm text-gray-500 dark:text-gray-400">
                            No security groups found. Create one in the Security
                            Groups tab.
                          </p>
                        )}
                    </div>
                  </div>
                </>
              )}
              <div className="flex justify-end space-x-3 pt-4">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="btn-secondary"
                >
                  Cancel
                </button>
                <button type="submit" className="btn-primary">
                  {createMode === "database" ? "Create Database" : "Create VM"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default Resources;
