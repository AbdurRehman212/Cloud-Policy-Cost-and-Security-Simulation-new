import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSelector } from "react-redux";
import { ArrowPathIcon, ClockIcon, FunnelIcon } from "@heroicons/react/24/outline";

import apiClient from "../../services/api";
import { selectDateFormat } from "../../store/slices/settingsSlice";
import { formatDate, formatDateTime, humanize, parseApiDate } from "../../utils/format";

const CATEGORY_LABELS = {
  auth: "Authentication",
  organization: "Organization & members",
  resource: "Resources",
  security: "Security",
  governance: "Governance",
  cost: "Cost & budgets",
  report: "Reports",
  remediation: "Remediation",
  settings: "Settings",
  data: "Data",
  learning: "Learning",
  other: "Other",
};

const OUTCOME_CLASS = { success: "status-running", failure: "status-critical", denied: "status-warning" };
const EMPTY_FILTERS = { category: "", outcome: "", q: "", date_from: "", date_to: "" };
const PER_PAGE = 20;

const ChangeBlock = ({ label, value }) => {
  if (value === null || value === undefined || (typeof value === "object" && Object.keys(value).length === 0)) return null;
  return (
    <div>
      <p className="text-xs font-medium text-gray-500 dark:text-gray-400">{label}</p>
      <pre className="mt-1 max-h-64 overflow-auto rounded bg-gray-50 p-2 text-xs text-gray-800 dark:bg-gray-900 dark:text-gray-200">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
};

const AuditTrail = () => {
  const { currentOrganization } = useSelector((state) => state.organization);
  const dateFormat = useSelector(selectDateFormat);
  const orgId = currentOrganization?.id;

  const [scope, setScope] = useState("organization"); // organization | me
  const [draft, setDraft] = useState(EMPTY_FILTERS);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  const [result, setResult] = useState(null);
  const [state, setState] = useState({ loading: true, error: null });
  const [expanded, setExpanded] = useState(null);
  const requestSeq = useRef(0); // only the newest request may update the timeline

  const load = useCallback(async () => {
    if (scope === "organization" && !orgId) return;
    const seq = ++requestSeq.current;
    setState({ loading: true, error: null });
    const params = { page, per_page: PER_PAGE };
    Object.entries(filters).forEach(([k, v]) => { if (v) params[k] = v; });
    try {
      const response = scope === "me"
        ? await apiClient.get("/audit/me", { params })
        : await apiClient.get("/audit/events", { params: { ...params, organization_id: orgId } });
      if (seq !== requestSeq.current) return; // a newer filter/page request superseded this one
      setResult(response.data.data);
      setState({ loading: false, error: null });
    } catch (error) {
      if (seq !== requestSeq.current) return;
      setState({ loading: false, error: error?.response?.data?.error?.message || "The audit trail could not be loaded." });
    }
  }, [scope, orgId, page, filters]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(1); setExpanded(null); }, [scope, orgId, filters]);

  const groups = useMemo(() => {
    const byDay = [];
    (result?.events || []).forEach((event) => {
      const day = formatDate(event.timestamp, dateFormat);
      const last = byDay[byDay.length - 1];
      if (last && last.day === day) last.events.push(event);
      else byDay.push({ day, events: [event] });
    });
    return byDay;
  }, [result, dateFormat]);

  const applyFilters = (e) => {
    e.preventDefault();
    if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) {
      setState({ loading: false, error: "The start date must be before the end date." });
      return;
    }
    setFilters(draft);
  };

  if (scope === "organization" && !orgId) {
    return (
      <div className="flex h-64 items-center justify-center">
        <p className="text-gray-500 dark:text-gray-400">No organization selected. Please select one from the sidebar.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Audit Trail</h1>
          <p className="mt-1 max-w-3xl text-sm text-gray-500 dark:text-gray-400">
            A read-only, chronological record of who did what and when. Entries cannot be edited or deleted.
          </p>
        </div>
        <button type="button" className="btn-secondary" onClick={load}>
          <ArrowPathIcon className="h-4 w-4" aria-hidden="true" /> Refresh
        </button>
      </div>

      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Audit scope" data-tour="audit-scope">
        {[
          ["organization", `Organization: ${currentOrganization?.name || "—"}`],
          ["me", "My account activity"],
        ].map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={scope === id}
            onClick={() => setScope(id)}
            className={`rounded-lg px-4 py-2 text-sm font-medium ${scope === id ? "bg-primary-600 text-white" : "bg-white text-gray-700 ring-1 ring-gray-200 hover:bg-gray-50 dark:bg-gray-800 dark:text-gray-200 dark:ring-gray-700"}`}
          >
            {label}
          </button>
        ))}
      </div>

      {result?.scope === "own_actions" && (
        <p className="rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm text-gray-600 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300" role="note">
          Your role shows only your own actions in this organization. Admins and owners see everyone&apos;s.
        </p>
      )}

      <form className="card p-4" onSubmit={applyFilters} aria-label="Audit filters" data-tour="audit-filters">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-6">
          <label className="text-sm text-gray-700 dark:text-gray-300 lg:col-span-2">
            Search
            <input
              type="search"
              className="input-field mt-1"
              placeholder="Action, resource type or id"
              value={draft.q}
              onChange={(e) => setDraft({ ...draft, q: e.target.value })}
            />
          </label>
          <label className="text-sm text-gray-700 dark:text-gray-300">
            Activity type
            <select className="input-field mt-1" value={draft.category} onChange={(e) => setDraft({ ...draft, category: e.target.value })}>
              <option value="">All types</option>
              {Object.entries(CATEGORY_LABELS).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </label>
          <label className="text-sm text-gray-700 dark:text-gray-300">
            Outcome
            <select className="input-field mt-1" value={draft.outcome} onChange={(e) => setDraft({ ...draft, outcome: e.target.value })}>
              <option value="">Any</option>
              <option value="success">Success</option>
              <option value="failure">Failure</option>
              <option value="denied">Denied</option>
            </select>
          </label>
          <label className="text-sm text-gray-700 dark:text-gray-300">
            From
            <input type="date" className="input-field mt-1" value={draft.date_from} onChange={(e) => setDraft({ ...draft, date_from: e.target.value })} />
          </label>
          <label className="text-sm text-gray-700 dark:text-gray-300">
            To
            <input type="date" className="input-field mt-1" value={draft.date_to} onChange={(e) => setDraft({ ...draft, date_to: e.target.value })} />
          </label>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="submit" className="btn-primary"><FunnelIcon className="h-4 w-4" aria-hidden="true" /> Apply filters</button>
          <button type="button" className="btn-secondary" onClick={() => { setDraft(EMPTY_FILTERS); setFilters(EMPTY_FILTERS); }}>Clear</button>
        </div>
      </form>

      <section className="card p-4" aria-labelledby="timeline-heading" aria-busy={state.loading} data-tour="audit-timeline">
        <div className="flex items-center justify-between">
          <h2 id="timeline-heading" className="section-title">Timeline</h2>
          {result && <span className="text-xs text-gray-500 dark:text-gray-400">{result.total} event{result.total === 1 ? "" : "s"}</span>}
        </div>

        {state.loading && !result && <p className="mt-4 text-sm text-gray-500 dark:text-gray-400">Loading audit events…</p>}
        {state.error && <p className="mt-4 text-sm text-red-600 dark:text-red-400" role="alert">{state.error}</p>}
        {!state.loading && !state.error && result?.events.length === 0 && (
          <div className="mt-6 text-center text-sm text-gray-500 dark:text-gray-400">
            <ClockIcon className="mx-auto h-8 w-8 text-gray-400" aria-hidden="true" />
            <p className="mt-2">No events match these filters.</p>
          </div>
        )}

        <ol className="mt-4 space-y-6">
          {groups.map((group) => (
            <li key={group.day}>
              <h3 className="section-label">{group.day}</h3>
              <ol className="mt-2 border-l border-gray-200 dark:border-gray-700">
                {group.events.map((event) => {
                  const open = expanded === event.id;
                  const time = parseApiDate(event.timestamp);
                  return (
                    <li key={event.id} className="relative ml-4 pb-3">
                      <span className="absolute -left-[21px] top-2 h-2.5 w-2.5 rounded-full bg-primary-500 ring-4 ring-white dark:ring-gray-800" aria-hidden="true" />
                      <button
                        type="button"
                        aria-expanded={open}
                        onClick={() => setExpanded(open ? null : event.id)}
                        className="w-full rounded-lg p-2 text-left hover:bg-gray-50 dark:hover:bg-gray-700/40"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-xs tabular-nums text-gray-500 dark:text-gray-400">
                            {time ? time.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : ""}
                          </span>
                          <span className="text-sm font-medium text-gray-900 dark:text-white">{humanize(event.action)}</span>
                          <span className="status-badge status-stopped">{CATEGORY_LABELS[event.category] || "Other"}</span>
                          <span className={`status-badge ${OUTCOME_CLASS[event.outcome] || "status-stopped"}`}>{humanize(event.outcome)}</span>
                        </div>
                        <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
                          {event.actor ? event.actor.name : "System"}
                          {event.resource_type ? ` · ${humanize(event.resource_type)}` : ""}
                          {event.resource_id ? ` ${event.resource_id}` : ""}
                        </p>
                      </button>
                      {open && (
                        <div className="mt-1 space-y-2 rounded-lg border border-gray-200 p-3 dark:border-gray-700">
                          <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-xs sm:grid-cols-2">
                            <div><dt className="inline text-gray-500 dark:text-gray-400">Event id: </dt><dd className="inline text-gray-800 dark:text-gray-200">{event.id}</dd></div>
                            <div><dt className="inline text-gray-500 dark:text-gray-400">Recorded: </dt><dd className="inline text-gray-800 dark:text-gray-200">{formatDateTime(event.timestamp, dateFormat)}</dd></div>
                            <div><dt className="inline text-gray-500 dark:text-gray-400">Scope: </dt><dd className="inline text-gray-800 dark:text-gray-200">{event.organization_id ? `Organization ${event.organization_id}` : "Account"}</dd></div>
                            {event.compliance_relevant && <div><dt className="inline text-gray-500 dark:text-gray-400">Compliance relevant: </dt><dd className="inline text-gray-800 dark:text-gray-200">Yes</dd></div>}
                          </dl>
                          <ChangeBlock label="Before" value={event.changes?.old} />
                          <ChangeBlock label="After / details" value={event.changes?.new} />
                        </div>
                      )}
                    </li>
                  );
                })}
              </ol>
            </li>
          ))}
        </ol>

        {result && result.pages > 1 && (
          <nav className="mt-4 flex items-center justify-between border-t border-gray-200 pt-3 text-sm dark:border-gray-700" aria-label="Audit pages">
            <button type="button" className="btn-secondary disabled:opacity-50" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
            <span className="text-gray-600 dark:text-gray-300">Page {result.page} of {result.pages}</span>
            <button type="button" className="btn-secondary disabled:opacity-50" disabled={page >= result.pages} onClick={() => setPage(page + 1)}>Next</button>
          </nav>
        )}
      </section>
    </div>
  );
};

export default AuditTrail;
