import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSelector } from "react-redux";
import toast from "react-hot-toast";
import {
  ArrowPathIcon,
  CheckCircleIcon,
  ExclamationTriangleIcon,
  ShieldExclamationIcon,
  WrenchScrewdriverIcon,
} from "@heroicons/react/24/outline";

import apiClient, { createSocket } from "../../services/api";
import { selectDateFormat } from "../../store/slices/settingsSlice";
import { formatDateTime, humanize } from "../../utils/format";

const TYPE_FILTERS = [
  { id: "all", label: "All" },
  { id: "threat", label: "Threats" },
  { id: "violation", label: "Policy violations" },
  { id: "idle", label: "Idle resources" },
];

const SEVERITY_CLASS = {
  critical: "status-critical",
  high: "status-critical",
  medium: "status-warning",
  warning: "status-warning",
  low: "status-stopped",
  info: "status-stopped",
};

const STATUS_CLASS = {
  succeeded: "status-running",
  resolved: "status-running",
  failed: "status-critical",
  awaiting_review: "status-warning",
  under_review: "status-warning",
  contained: "status-warning",
  active: "status-critical",
  open: "status-critical",
};

const apiError = (error, fallback) =>
  error?.response?.data?.error?.message || error?.response?.data?.error || fallback;

const Badge = ({ value, map = STATUS_CLASS }) => (
  <span className={`status-badge ${map[String(value || "").toLowerCase()] || "status-stopped"}`}>
    {humanize(value)}
  </span>
);

const PreviewTable = ({ preview }) => {
  const rows = Object.entries(preview || {});
  if (rows.length === 0) return null;
  const show = (v) => (v === null || v === undefined ? "none" : Array.isArray(v) ? v.join(", ") || "none" : typeof v === "object" ? JSON.stringify(v) : String(v));
  return (
    <table className="mt-2 w-full text-xs">
      <thead>
        <tr className="text-left text-gray-500 dark:text-gray-400">
          <th scope="col" className="py-1 pr-2 font-medium">Field</th>
          <th scope="col" className="py-1 pr-2 font-medium">Before</th>
          <th scope="col" className="py-1 font-medium">After</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([field, change]) => (
          <tr key={field} className="border-t border-gray-100 dark:border-gray-700">
            <td className="py-1 pr-2 text-gray-600 dark:text-gray-300">{humanize(field)}</td>
            <td className="py-1 pr-2 font-mono text-gray-700 dark:text-gray-200 break-all">{show(change.before)}</td>
            <td className="py-1 font-mono text-gray-900 dark:text-white break-all">{show(change.after)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
};

const Remediation = () => {
  const { currentOrganization } = useSelector((state) => state.organization);
  const { vms } = useSelector((state) => state.resources || {});
  const dateFormat = useSelector(selectDateFormat);
  const orgId = currentOrganization?.id;

  const [issues, setIssues] = useState([]);
  const [canExecute, setCanExecute] = useState(false);
  const [issuesState, setIssuesState] = useState({ loading: true, error: null });
  const [filter, setFilter] = useState("all");
  const [selectedKey, setSelectedKey] = useState(null);
  const [plan, setPlan] = useState(null);
  const [planState, setPlanState] = useState({ loading: false, error: null });
  const [chosen, setChosen] = useState([]);
  const [approved, setApproved] = useState(false);
  const [targetId, setTargetId] = useState("");
  const [executing, setExecuting] = useState(false);
  const [outcome, setOutcome] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyError, setHistoryError] = useState(null);
  const planSeq = useRef(0); // ignore plans for an issue the user has already moved away from

  const loadIssues = useCallback(async () => {
    if (!orgId) return;
    setIssuesState((s) => ({ ...s, loading: true }));
    try {
      const response = await apiClient.get("/remediation/issues", { params: { organization_id: orgId } });
      setIssues(response.data.data.issues);
      setCanExecute(Boolean(response.data.data.can_execute));
      setIssuesState({ loading: false, error: null });
    } catch (error) {
      setIssuesState({ loading: false, error: apiError(error, "Issues could not be loaded.") });
    }
  }, [orgId]);

  const loadHistory = useCallback(async () => {
    if (!orgId) return;
    try {
      const response = await apiClient.get("/remediation/history", { params: { organization_id: orgId, limit: 25 } });
      setHistory(response.data.data.actions);
      setHistoryError(null);
    } catch (error) {
      setHistoryError(apiError(error, "History could not be loaded."));
    }
  }, [orgId]);

  const loadPlan = useCallback(
    async (key, target) => {
      if (!orgId || !key) return;
      const seq = ++planSeq.current;
      setPlanState({ loading: true, error: null });
      setOutcome(null);
      try {
        const response = await apiClient.post("/remediation/plan", {
          organization_id: orgId,
          issue_key: key,
          ...(target ? { target_resource_id: Number(target) } : {}),
        });
        const data = response.data.data;
        if (seq !== planSeq.current) return;
        setPlan(data);
        setChosen(data.actions.filter((a) => a.applicable).map((a) => a.action));
        setApproved(false);
        setPlanState({ loading: false, error: null });
      } catch (error) {
        if (seq !== planSeq.current) return;
        setPlan(null);
        setPlanState({ loading: false, error: apiError(error, "Recommendations could not be generated.") });
      }
    },
    [orgId],
  );

  useEffect(() => {
    setSelectedKey(null);
    setPlan(null);
    setOutcome(null);
    loadIssues();
    loadHistory();
  }, [loadIssues, loadHistory]);

  // Threat detections and other users' remediations arrive over the socket.
  useEffect(() => {
    if (!orgId) return undefined;
    const socket = createSocket("/metrics");
    if (!socket) return undefined;
    const join = () => socket.emit("join_room", { org_id: orgId });
    const refresh = () => {
      loadIssues();
      loadHistory();
    };
    socket.on("connect", join);
    socket.on("threats:update", refresh);
    if (socket.connected) join();
    return () => {
      socket.off("connect", join);
      socket.off("threats:update", refresh);
    };
  }, [orgId, loadIssues, loadHistory]);

  const visibleIssues = useMemo(
    () => (filter === "all" ? issues : issues.filter((issue) => issue.type === filter)),
    [issues, filter],
  );

  const selectIssue = (key) => {
    setSelectedKey(key);
    setTargetId("");
    loadPlan(key);
  };

  const toggle = (action) =>
    setChosen((current) => (current.includes(action) ? current.filter((a) => a !== action) : [...current, action]));

  const needsApproval = plan?.actions.some((a) => chosen.includes(a.action) && a.requires_approval);

  const execute = async () => {
    if (!plan || chosen.length === 0) return;
    setExecuting(true);
    try {
      const response = await apiClient.post("/remediation/execute", {
        organization_id: orgId,
        issue_key: plan.issue.key,
        actions: chosen,
        approved,
        ...(targetId ? { target_resource_id: Number(targetId) } : {}),
      });
      const data = response.data.data;
      setOutcome({ ok: true, ...data });
      toast.success(`Issue ${humanize(data.issue_status).toLowerCase()}`);
      await Promise.all([loadIssues(), loadHistory()]);
      if (data.issue_status !== "resolved") loadPlan(plan.issue.key, targetId);
    } catch (error) {
      const msg = apiError(error, "Remediation failed.");
      setOutcome({ ok: false, message: msg });
      toast.error(msg);
      loadHistory();
    } finally {
      setExecuting(false);
    }
  };

  if (!orgId) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-gray-500 dark:text-gray-400">No organization selected. Please select one from the sidebar.</p>
      </div>
    );
  }

  const needsTarget = plan && !plan.resource && plan.actions.some((a) => !a.applicable && /target resource/.test(a.not_applicable_reason || ""));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Remediation Agent</h1>
          <p className="mt-1 max-w-3xl text-sm text-gray-500 dark:text-gray-400">
            Pick an open threat, policy violation or idle resource, review the recommended fixes and what they change,
            then approve and run them. Actions change <strong>simulated</strong> resources in this application only.
          </p>
        </div>
        <button type="button" className="btn-secondary" onClick={() => { loadIssues(); loadHistory(); }}>
          <ArrowPathIcon className="h-4 w-4" aria-hidden="true" /> Refresh
        </button>
      </div>

      {!canExecute && !issuesState.loading && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-200" role="note">
          You can review issues and recommendations. Only organization admins and owners can execute remediation.
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
        {/* Issues */}
        <section className="card p-4 xl:col-span-2" aria-labelledby="issues-heading" data-tour="remediation-issues">
          <div className="flex items-center justify-between gap-2">
            <h2 id="issues-heading" className="section-title">Open issues</h2>
            <span className="text-xs text-gray-500 dark:text-gray-400">{visibleIssues.length} shown</span>
          </div>
          <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Filter issues by type">
            {TYPE_FILTERS.map((f) => (
              <button
                key={f.id}
                type="button"
                aria-pressed={filter === f.id}
                onClick={() => setFilter(f.id)}
                className={`rounded-full px-3 py-1 text-xs font-medium ${filter === f.id ? "bg-primary-600 text-white" : "bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-200"}`}
              >
                {f.label}
              </button>
            ))}
          </div>

          <div className="mt-4 space-y-2">
            {issuesState.loading && issues.length === 0 && <p className="text-sm text-gray-500 dark:text-gray-400">Loading issues…</p>}
            {issuesState.error && (
              <p className="text-sm text-red-600 dark:text-red-400" role="alert">{issuesState.error}</p>
            )}
            {!issuesState.loading && !issuesState.error && visibleIssues.length === 0 && (
              <div className="rounded-lg border border-dashed border-gray-300 p-6 text-center dark:border-gray-600">
                <CheckCircleIcon className="mx-auto h-8 w-8 text-emerald-500" aria-hidden="true" />
                <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">No open issues.</p>
                <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                  Simulate an attack on the Security page or run a compliance check on Governance to create one.
                </p>
              </div>
            )}
            {visibleIssues.map((issue) => (
              <button
                key={issue.key}
                type="button"
                onClick={() => selectIssue(issue.key)}
                aria-current={selectedKey === issue.key ? "true" : undefined}
                className={`w-full rounded-lg border p-3 text-left transition-colors ${selectedKey === issue.key ? "border-primary-500 bg-primary-50 dark:bg-primary-900/20" : "border-gray-200 hover:border-gray-300 dark:border-gray-700 dark:hover:border-gray-500"}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-medium text-gray-900 dark:text-white">{issue.title}</span>
                  <Badge value={issue.severity} map={SEVERITY_CLASS} />
                </div>
                <p className="mt-1 line-clamp-2 text-xs text-gray-500 dark:text-gray-400">{issue.summary || "No details recorded."}</p>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
                  <Badge value={issue.status} />
                  {issue.confidence !== null && issue.confidence !== undefined && <span>confidence {issue.confidence.toFixed(2)}</span>}
                  {issue.resource_ref && <span className="font-mono">{issue.resource_ref}</span>}
                  {issue.detected_at && <span>{formatDateTime(issue.detected_at, dateFormat)}</span>}
                </div>
              </button>
            ))}
          </div>
        </section>

        {/* Plan */}
        <section className="card p-4 xl:col-span-3" aria-labelledby="plan-heading" data-tour="remediation-plan">
          <h2 id="plan-heading" className="section-title">Recommended actions</h2>
          {!selectedKey && (
            <div className="mt-6 text-center text-sm text-gray-500 dark:text-gray-400">
              <WrenchScrewdriverIcon className="mx-auto h-8 w-8 text-gray-400" aria-hidden="true" />
              <p className="mt-2">Select an issue to see what the agent recommends and why.</p>
            </div>
          )}
          {planState.loading && <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Generating recommendations…</p>}
          {planState.error && <p className="mt-4 text-sm text-red-600 dark:text-red-400" role="alert">{planState.error}</p>}

          {plan && !planState.loading && (
            <div className="mt-3 space-y-4">
              <div className="rounded-lg bg-gray-50 p-3 text-sm dark:bg-gray-700/40">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-gray-900 dark:text-white">{plan.issue.title}</span>
                  <Badge value={plan.issue.status} />
                </div>
                <p className="mt-1 text-gray-600 dark:text-gray-300">{plan.issue.summary}</p>
                <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                  Target: {plan.resource ? `${plan.resource.name} (${plan.resource.kind}, ${plan.resource.status})` : "no linked resource"} · Engine: {plan.engine}
                </p>
              </div>

              {needsTarget && (
                <label className="block text-sm text-gray-700 dark:text-gray-300">
                  This threat has no linked resource. Choose the VM to act on:
                  <select
                    className="input-field mt-1"
                    value={targetId}
                    onChange={(e) => { setTargetId(e.target.value); loadPlan(plan.issue.key, e.target.value); }}
                  >
                    <option value="">Select a VM…</option>
                    {(vms || []).filter((vm) => String(vm.status).toLowerCase() !== "terminated").map((vm) => (
                      <option key={vm.id} value={vm.id}>{vm.name} ({vm.instance_type || vm.status})</option>
                    ))}
                  </select>
                </label>
              )}

              <fieldset className="space-y-3">
                <legend className="sr-only">Actions to run</legend>
                {plan.actions.map((action) => (
                  <div
                    key={action.action}
                    className={`rounded-lg border p-3 ${action.applicable ? "border-gray-200 dark:border-gray-700" : "border-dashed border-gray-300 opacity-70 dark:border-gray-600"}`}
                  >
                    <label className="flex items-start gap-3">
                      <input
                        type="checkbox"
                        className="mt-1 h-4 w-4 rounded border-gray-300 text-primary-600"
                        checked={chosen.includes(action.action)}
                        disabled={!action.applicable || !canExecute}
                        onChange={() => toggle(action.action)}
                      />
                      <span className="flex-1">
                        <span className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-medium text-gray-900 dark:text-white">{action.label}</span>
                          {action.requires_approval ? (
                            <span className="status-badge status-warning">Needs approval</span>
                          ) : (
                            <span className="status-badge status-stopped">No configuration change</span>
                          )}
                        </span>
                        <span className="mt-1 block text-xs text-gray-600 dark:text-gray-300"><strong>Why:</strong> {action.reason}</span>
                        <span className="block text-xs text-gray-600 dark:text-gray-300"><strong>What it does:</strong> {action.description}</span>
                        <span className="block text-xs text-gray-600 dark:text-gray-300"><strong>Consequence:</strong> {action.consequence}</span>
                        <span className="block text-xs text-gray-500 dark:text-gray-400"><strong>Recovery:</strong> {action.recovery}</span>
                        {!action.applicable && (
                          <span className="mt-1 block text-xs text-amber-700 dark:text-amber-300">Not available: {action.not_applicable_reason}</span>
                        )}
                        <PreviewTable preview={action.preview} />
                      </span>
                    </label>
                  </div>
                ))}
              </fieldset>

              {canExecute && (
                <div className="space-y-3 border-t border-gray-200 pt-3 dark:border-gray-700">
                  {needsApproval && (
                    <label className="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-300">
                      <input type="checkbox" className="mt-1 h-4 w-4 rounded border-gray-300 text-primary-600" checked={approved} onChange={(e) => setApproved(e.target.checked)} />
                      I have reviewed the consequences and approve these configuration changes to the simulated resources.
                    </label>
                  )}
                  <button
                    type="button"
                    className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={executing || chosen.length === 0 || (needsApproval && !approved)}
                    onClick={execute}
                  >
                    <WrenchScrewdriverIcon className="h-4 w-4" aria-hidden="true" />
                    {executing ? "Executing…" : `Execute ${chosen.length} action${chosen.length === 1 ? "" : "s"}`}
                  </button>
                </div>
              )}

              {outcome && (
                <div
                  role="status"
                  className={`rounded-lg border p-3 text-sm ${outcome.ok ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-200" : "border-red-200 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-900/20 dark:text-red-200"}`}
                >
                  {outcome.ok ? (
                    <>
                      <p className="flex items-center gap-2 font-medium"><CheckCircleIcon className="h-5 w-5" aria-hidden="true" /> Issue status: {humanize(outcome.previous_status)} → {humanize(outcome.issue_status)}</p>
                      <ul className="mt-1 list-disc pl-6 text-xs">
                        {outcome.actions.map((a) => <li key={a.id}>{a.result}</li>)}
                      </ul>
                      {outcome.verification && (
                        <p className="mt-1 text-xs">Policy re-check: {outcome.verification.compliant ? "compliant" : outcome.verification.violations.join("; ")}</p>
                      )}
                    </>
                  ) : (
                    <p className="flex items-center gap-2"><ExclamationTriangleIcon className="h-5 w-5" aria-hidden="true" /> {outcome.message} The issue remains unresolved and no changes were kept.</p>
                  )}
                </div>
              )}
            </div>
          )}
        </section>
      </div>

      {/* History */}
      <section className="card p-4" aria-labelledby="history-heading" data-tour="remediation-history">
        <h2 id="history-heading" className="section-title">Action history</h2>
        <p className="section-sub">Every executed, failed or review-only action. The full record is in the Audit Trail.</p>
        {historyError && <p className="mt-3 text-sm text-red-600 dark:text-red-400" role="alert">{historyError}</p>}
        {!historyError && history.length === 0 && <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">No remediation actions yet.</p>}
        {history.length > 0 && (
          <div className="mt-3 overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-left text-xs uppercase tracking-wide text-gray-500 dark:border-gray-700 dark:text-gray-400">
                  <th scope="col" className="py-2 pr-3">When</th>
                  <th scope="col" className="py-2 pr-3">Issue</th>
                  <th scope="col" className="py-2 pr-3">Action</th>
                  <th scope="col" className="py-2 pr-3">Status</th>
                  <th scope="col" className="py-2 pr-3">Verified</th>
                  <th scope="col" className="py-2">Result</th>
                </tr>
              </thead>
              <tbody>
                {history.map((row) => (
                  <tr key={row.id} className="border-b border-gray-100 align-top dark:border-gray-700/60">
                    <td className="whitespace-nowrap py-2 pr-3 text-gray-600 dark:text-gray-300">{formatDateTime(row.executed_at, dateFormat)}</td>
                    <td className="py-2 pr-3 font-mono text-xs text-gray-700 dark:text-gray-200">{row.issue_key || "—"}</td>
                    <td className="py-2 pr-3 text-gray-900 dark:text-white">{humanize(row.action_type)}</td>
                    <td className="py-2 pr-3"><Badge value={row.legacy ? "legacy" : row.status} /></td>
                    <td className="py-2 pr-3 text-gray-600 dark:text-gray-300">{row.verified ? "Yes" : "No"}</td>
                    <td className="py-2 text-xs text-gray-600 dark:text-gray-300">
                      {row.legacy ? "Recorded by an earlier build; never applied to a resource." : row.result}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
        <ShieldExclamationIcon className="h-4 w-4" aria-hidden="true" />
        Recommendations come from fixed, explainable rules (not a trained model). Low-confidence detections are sent to human review.
      </p>
    </div>
  );
};

export default Remediation;
