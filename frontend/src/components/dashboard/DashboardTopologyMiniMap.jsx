import React, { useMemo, useState } from "react";
import {
  ArrowTrendingUpIcon,
  ServerStackIcon,
  ShieldExclamationIcon,
  ShieldCheckIcon,
  CircleStackIcon,
  CpuChipIcon,
  SignalIcon,
  BoltIcon,
} from "@heroicons/react/24/outline";

const HEALTH_STYLES = {
  green: "bg-emerald-500 ring-emerald-200/70 dark:ring-emerald-900/40",
  yellow: "bg-amber-400 ring-amber-200/70 dark:ring-amber-900/40",
  red: "bg-red-500 ring-red-200/70 dark:ring-red-900/40",
};

const NODE_STYLES = {
  load_balancer: "border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-800 dark:bg-sky-900/20 dark:text-sky-100",
  vm: "border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-100",
  database: "border-purple-200 bg-purple-50 text-purple-800 dark:border-purple-800 dark:bg-purple-900/20 dark:text-purple-100",
  security_group: "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-100",
  threat: "border-red-200 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-900/20 dark:text-red-100",
  scaling: "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-100",
};

const EDGE_STYLES = {
  dependency: "stroke-slate-300 dark:stroke-slate-600",
  security: "stroke-emerald-300 dark:stroke-emerald-700",
  attack: "stroke-red-400 dark:stroke-red-500",
};

const SCALE_STYLES = {
  steady: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-100",
  scale_out: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-100",
  scale_in: "bg-sky-100 text-sky-800 dark:bg-sky-900/30 dark:text-sky-100",
  pressure: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-100",
};

const NODE_ICON = {
  load_balancer: ArrowTrendingUpIcon,
  vm: CpuChipIcon,
  database: CircleStackIcon,
  security_group: ShieldCheckIcon,
  threat: ShieldExclamationIcon,
  scaling: SignalIcon,
};

const typeLabel = (type) => {
  if (!type) return "Resource";
  return type
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
};

const formatDetailValue = (value) => {
  if (value === null || value === undefined || value === "") return "-";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
};

const getNodeDescription = (node) => {
  if (!node) return "";
  const details = node.details || {};
  if (node.type === "load_balancer") {
    return `${details.running_vms || 0} VMs, ${details.queue_total_ms || 0} ms queue`;
  }
  if (node.type === "vm") {
    return `${details.cpu_utilization ?? 0}% CPU, ${details.memory_utilization ?? 0}% memory`;
  }
  if (node.type === "database") {
    return `${details.engine || "database"} • ${details.connections || 0} connections`;
  }
  if (node.type === "security_group") {
    return `${details.rule_count || 0} rules • ${details.vm_count || 0} VMs`;
  }
  if (node.type === "threat") {
    return `${details.severity || "high"} confidence ${(details.confidence_score || 0).toFixed ? (details.confidence_score || 0).toFixed(2) : details.confidence_score || 0}`;
  }
  if (node.type === "scaling") {
    return `${details.direction || "steady"} • desired ${details.desired_capacity || 0}`;
  }
  return "";
};

export default function DashboardTopologyMiniMap({ topologyMap = {}, snapshotAgeSeconds = 0 }) {
  const [hoveredNodeId, setHoveredNodeId] = useState(null);
  const nodes = useMemo(() => topologyMap.nodes || [], [topologyMap.nodes]);
  const edges = useMemo(() => topologyMap.edges || [], [topologyMap.edges]);
  const summary = useMemo(() => topologyMap.summary || {}, [topologyMap.summary]);
  const scaling = useMemo(() => topologyMap.scaling || {}, [topologyMap.scaling]);
  const activeThreats = useMemo(
    () => topologyMap.active_threat_overlays || [],
    [topologyMap.active_threat_overlays],
  );
  const hoveredNode = useMemo(
    () => nodes.find((node) => node.id === hoveredNodeId) || null,
    [hoveredNodeId, nodes],
  );

  const nodeById = useMemo(() => {
    const lookup = new Map();
    nodes.forEach((node) => lookup.set(node.id, node));
    return lookup;
  }, [nodes]);

  return (
    <div className="card overflow-hidden border-l-4 border-cyan-500">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
            Realtime Topology Mini-Map
          </p>
          <h2 className="mt-1 text-lg font-semibold text-gray-900 dark:text-white">
            Infrastructure dependencies, health, and active risk
          </h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Snapshot-driven, org-scoped, and updated on every websocket refresh.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs font-medium">
          <span className={`inline-flex rounded-full px-2.5 py-1 ${SCALE_STYLES[scaling.direction] || SCALE_STYLES.steady}`}>
            {scaling.direction || "steady"}
          </span>
          <span className="rounded-full bg-gray-100 px-2.5 py-1 text-gray-700 dark:bg-gray-700 dark:text-gray-200">
            {summary.vm_count || 0} VMs
          </span>
          <span className="rounded-full bg-gray-100 px-2.5 py-1 text-gray-700 dark:bg-gray-700 dark:text-gray-200">
            {summary.database_count || 0} DBs
          </span>
          <span className="rounded-full bg-gray-100 px-2.5 py-1 text-gray-700 dark:bg-gray-700 dark:text-gray-200">
            {summary.security_group_count || 0} SGs
          </span>
          <span className={`rounded-full px-2.5 py-1 ${summary.health === "red" ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-100" : summary.health === "yellow" ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-100" : "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-100"}`}>
            {summary.active_threats || 0} active threats
          </span>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.5fr_0.8fr]">
        <div className="relative overflow-hidden rounded-2xl border border-gray-200 bg-gradient-to-br from-slate-50 via-white to-cyan-50/60 p-4 dark:border-gray-700 dark:from-gray-900 dark:via-gray-900 dark:to-gray-800/70">
          <svg
            className="pointer-events-none absolute inset-0 h-full w-full"
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <defs>
              <marker id="topology-arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                <path d="M0,0 L6,3 L0,6 z" fill="currentColor" />
              </marker>
            </defs>
            {edges.map((edge) => {
              const source = nodeById.get(edge.source);
              const target = nodeById.get(edge.target);
              if (!source || !target) return null;
              const edgeColor = EDGE_STYLES[edge.kind] || EDGE_STYLES.dependency;
              const dashed = edge.kind === "attack" || edge.kind === "security";
              return (
                <line
                  key={edge.id}
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  className={`${edgeColor} ${dashed ? "[stroke-dasharray:4_3]" : ""}`}
                  style={{ color: edge.kind === "attack" ? "#ef4444" : edge.kind === "security" ? "#10b981" : "#94a3b8" }}
                  strokeWidth={edge.kind === "attack" ? 1.8 : 1.2}
                  markerEnd="url(#topology-arrow)"
                />
              );
            })}
          </svg>

          <div className="relative h-[360px]">
            {nodes.map((node) => {
              const Icon = NODE_ICON[node.type] || ServerStackIcon;
              const isHovered = hoveredNodeId === node.id;
              return (
                <button
                  key={node.id}
                  type="button"
                  className="group absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center focus:outline-none"
                  style={{ left: `${node.x}%`, top: `${node.y}%` }}
                  onMouseEnter={() => setHoveredNodeId(node.id)}
                  onMouseLeave={() => setHoveredNodeId(null)}
                  onFocus={() => setHoveredNodeId(node.id)}
                  onBlur={() => setHoveredNodeId(null)}
                  aria-label={`${node.label} ${node.health} ${node.status}`}
                >
                  <span
                    className={`inline-flex h-12 w-12 items-center justify-center rounded-2xl border shadow-sm transition-transform duration-150 group-hover:scale-105 ${NODE_STYLES[node.type] || NODE_STYLES.vm} ${isHovered ? "ring-2 ring-offset-2" : ""} ${HEALTH_STYLES[node.health] || HEALTH_STYLES.yellow}`}
                  >
                    <Icon className="h-5 w-5" />
                  </span>
                  <span className="mt-2 max-w-[110px] rounded-full border border-white/70 bg-white/80 px-2 py-0.5 text-[11px] font-semibold text-gray-700 shadow-sm backdrop-blur dark:border-gray-700 dark:bg-gray-900/80 dark:text-gray-200">
                    {node.label}
                  </span>
                </button>
              );
            })}
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] font-medium text-gray-500 dark:text-gray-400">
            <span className="inline-flex items-center gap-1 rounded-full bg-white/80 px-2 py-1 shadow-sm dark:bg-gray-900/70">
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" /> Green healthy
            </span>
            <span className="inline-flex items-center gap-1 rounded-full bg-white/80 px-2 py-1 shadow-sm dark:bg-gray-900/70">
              <span className="h-2.5 w-2.5 rounded-full bg-amber-400" /> Yellow warning
            </span>
            <span className="inline-flex items-center gap-1 rounded-full bg-white/80 px-2 py-1 shadow-sm dark:bg-gray-900/70">
              <span className="h-2.5 w-2.5 rounded-full bg-red-500" /> Red unhealthy
            </span>
            <span className="inline-flex items-center gap-1 rounded-full bg-white/80 px-2 py-1 shadow-sm dark:bg-gray-900/70">
              <BoltIcon className="h-3.5 w-3.5 text-red-500" /> Attack overlays
            </span>
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-2xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-800/60">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  Hover details
                </p>
                <h3 className="mt-1 text-sm font-semibold text-gray-900 dark:text-white">
                  {hoveredNode?.label || "Move over a node"}
                </h3>
              </div>
              <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${hoveredNode ? HEALTH_STYLES[hoveredNode.health] || HEALTH_STYLES.yellow : "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300"}`}>
                {hoveredNode ? hoveredNode.health : "idle"}
              </span>
            </div>

            {hoveredNode ? (
              <div className="mt-4 space-y-3 text-sm text-gray-600 dark:text-gray-300">
                <p>{getNodeDescription(hoveredNode)}</p>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <DetailChip label="Type" value={typeLabel(hoveredNode.type)} />
                  <DetailChip label="Status" value={hoveredNode.status} />
                  <DetailChip label="Health" value={hoveredNode.health} />
                  <DetailChip label="Resource" value={hoveredNode.resource_kind} />
                </div>
                <div className="rounded-xl bg-white p-3 text-xs shadow-sm dark:bg-gray-900/70">
                  {Object.entries(hoveredNode.details || {}).length > 0 ? (
                    <dl className="space-y-2">
                      {Object.entries(hoveredNode.details).map(([key, value]) => (
                        <div key={key} className="flex items-start justify-between gap-3">
                          <dt className="font-medium text-gray-500 dark:text-gray-400">{key}</dt>
                          <dd className="max-w-[60%] text-right font-medium text-gray-900 dark:text-white">{formatDetailValue(value)}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : (
                    <p className="text-gray-500 dark:text-gray-400">No additional details available.</p>
                  )}
                </div>
              </div>
            ) : (
              <div className="mt-4 rounded-xl border border-dashed border-gray-300 bg-white p-4 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900/60 dark:text-gray-400">
                Hover a node to inspect resource state, security posture, and attached dependencies.
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-800/60">
            <div className="flex items-center gap-2">
              <ShieldCheckIcon className="h-5 w-5 text-emerald-500" />
              <p className="text-sm font-semibold text-gray-900 dark:text-white">Topology summary</p>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
              <MiniMetric label="Nodes" value={summary.node_count || nodes.length} />
              <MiniMetric label="Edges" value={summary.edge_count || edges.length} />
              <MiniMetric label="Unhealthy" value={summary.unhealthy_node_count || 0} />
              <MiniMetric label="Threats" value={summary.active_threats || 0} />
            </div>
            <div className="mt-3 rounded-xl bg-white p-3 text-xs text-gray-600 shadow-sm dark:bg-gray-900/70 dark:text-gray-300">
              {scaling.direction === "scale_out"
                ? "Scale-out pressure is active and the control plane is expanding capacity."
                : scaling.direction === "scale_in"
                  ? "Scale-in pressure is active and the control plane is contracting capacity."
                  : scaling.direction === "pressure"
                    ? "Backlog pressure is high enough that scaling is likely needed soon."
                    : "Capacity is stable and the mini-map is tracking the same snapshot the dashboard uses."}
            </div>
          </div>

          <div className="rounded-2xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-800/60">
            <div className="flex items-center gap-2">
              <BoltIcon className="h-5 w-5 text-red-500" />
              <p className="text-sm font-semibold text-gray-900 dark:text-white">Attack overlays</p>
            </div>
            {activeThreats.length > 0 ? (
              <ul className="mt-3 space-y-2 text-sm text-gray-600 dark:text-gray-300">
                {activeThreats.map((overlay) => (
                  <li key={overlay.id} className="rounded-xl bg-white p-3 shadow-sm dark:bg-gray-900/70">
                    <p className="font-medium text-gray-900 dark:text-white">{overlay.label}</p>
                    <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                      Targets: {overlay.targets?.length || 0} • severity {overlay.severity || "unknown"}
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">No active threats in the current snapshot.</p>
            )}
            <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">
              Snapshot age: {Number(snapshotAgeSeconds || topologyMap.freshness_seconds || 0).toFixed(1)}s
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function DetailChip({ label, value }) {
  return (
    <div className="rounded-xl bg-white px-3 py-2 shadow-sm dark:bg-gray-900/70">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">{label}</p>
      <p className="mt-0.5 text-sm font-medium text-gray-900 dark:text-white">{formatDetailValue(value)}</p>
    </div>
  );
}

function MiniMetric({ label, value }) {
  return (
    <div className="rounded-xl bg-white px-3 py-2 shadow-sm dark:bg-gray-900/70">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">{label}</p>
      <p className="mt-0.5 text-sm font-semibold text-gray-900 dark:text-white">{value}</p>
    </div>
  );
}