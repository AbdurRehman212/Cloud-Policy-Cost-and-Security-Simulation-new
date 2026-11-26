import React, { useEffect, useRef, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import {
  BellIcon,
  RectangleGroupIcon,
  ShieldCheckIcon,
  SwatchIcon,
  UserCircleIcon,
} from "@heroicons/react/24/outline";
import toast from "react-hot-toast";

import { fetchProfile } from "../../store/slices/authSlice";
import { fetchSettings, resetSettings, saveSettings } from "../../store/slices/settingsSlice";
import { formatDateTime } from "../../utils/format";

const TABS = [
  { id: "profile", name: "Profile", icon: UserCircleIcon },
  { id: "appearance", name: "Appearance", icon: SwatchIcon },
  { id: "dashboard", name: "Dashboard", icon: RectangleGroupIcon },
  { id: "alerts", name: "Alerts", icon: BellIcon },
  { id: "security", name: "Security", icon: ShieldCheckIcon },
];

const DATE_FORMAT_EXAMPLES = { "YYYY-MM-DD": "2026-11-26", "DD/MM/YYYY": "26/11/2026", "MM/DD/YYYY": "11/26/2026" };

const Field = ({ label, hint, children, htmlFor }) => (
  <div>
    <label htmlFor={htmlFor} className="block text-sm font-medium text-gray-700 dark:text-gray-300">{label}</label>
    <div className="mt-1">{children}</div>
    {hint && <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{hint}</p>}
  </div>
);

const Toggle = ({ id, label, description, checked, onChange }) => (
  <label htmlFor={id} className="flex items-start justify-between gap-4 rounded-lg border border-gray-200 p-3 dark:border-gray-700">
    <span>
      <span className="block text-sm font-medium text-gray-900 dark:text-white">{label}</span>
      {description && <span className="block text-xs text-gray-500 dark:text-gray-400">{description}</span>}
    </span>
    <input id={id} type="checkbox" className="mt-1 h-4 w-4 rounded border-gray-300 text-primary-600" checked={checked} onChange={(e) => onChange(e.target.checked)} />
  </label>
);

/** Build the editable form from the API representation. */
const toForm = (data) => ({
  profile: {
    first_name: data.profile.first_name || "",
    last_name: data.profile.last_name || "",
    department: data.profile.department || "",
    job_title: data.profile.job_title || "",
    phone: data.profile.phone || "",
  },
  appearance: { theme: data.appearance.theme, date_format: data.appearance.date_format, timezone: data.appearance.timezone },
  dashboard: {
    default_view: data.dashboard.default_view === "list" ? "list" : "grid",
    default_organization_id: data.dashboard.default_organization_id ?? "",
  },
  alerts: {
    security_alerts: data.notifications.preferences.security_alerts,
    security_severity: data.notifications.preferences.security_severity,
    cost_alerts: data.notifications.preferences.cost_alerts,
    cost_threshold: String(data.notifications.preferences.cost_threshold),
    compliance_alerts: data.notifications.preferences.compliance_alerts,
  },
  security: { session_timeout: String(data.security.session_timeout) },
});

const Settings = () => {
  const dispatch = useDispatch();
  const { data, loading, saving, error } = useSelector((state) => state.settings);
  const { organizations } = useSelector((state) => state.organization);
  const [activeTab, setActiveTab] = useState("profile");
  const [form, setForm] = useState(null);
  const [formError, setFormError] = useState(null);

  useEffect(() => { dispatch(fetchSettings()); }, [dispatch]);
  // Re-initialise the form only when the saved settings change (first load, save, reset). A second
  // fetch of unchanged settings (Layout also loads them) must not wipe edits the user is typing.
  const loadedVersion = useRef(null);
  useEffect(() => {
    if (!data) return;
    const version = data.updated_at || "initial";
    if (loadedVersion.current === version) return;
    loadedVersion.current = version;
    setForm(toForm(data));
  }, [data]);

  const set = (section, key, value) => setForm((f) => ({ ...f, [section]: { ...f[section], [key]: value } }));

  const payloadFor = (tab) => {
    if (tab === "profile") return { profile: form.profile };
    if (tab === "appearance") return { appearance: form.appearance };
    if (tab === "dashboard") {
      return {
        dashboard: {
          default_view: form.dashboard.default_view,
          default_organization_id: form.dashboard.default_organization_id === "" ? null : Number(form.dashboard.default_organization_id),
        },
      };
    }
    if (tab === "alerts") {
      return {
        notifications: {
          preferences: {
            security_alerts: form.alerts.security_alerts,
            security_severity: form.alerts.security_severity,
            cost_alerts: form.alerts.cost_alerts,
            // Sent as typed so the server can reject non-numeric input (UT-70).
            cost_threshold: form.alerts.cost_threshold.trim() === "" ? "" : Number.isNaN(Number(form.alerts.cost_threshold)) ? form.alerts.cost_threshold : Number(form.alerts.cost_threshold),
            compliance_alerts: form.alerts.compliance_alerts,
          },
        },
      };
    }
    return { security: { session_timeout: Number(form.security.session_timeout) } };
  };

  const save = async (event) => {
    event.preventDefault();
    setFormError(null);
    const result = await dispatch(saveSettings(payloadFor(activeTab)));
    if (saveSettings.fulfilled.match(result)) {
      toast.success("Settings saved");
      if (activeTab === "profile") dispatch(fetchProfile());
    } else {
      setFormError(result.payload);
      toast.error(result.payload || "Settings were not saved");
    }
  };

  const restore = async () => {
    setFormError(null);
    const result = await dispatch(resetSettings());
    if (resetSettings.fulfilled.match(result)) toast.success("Default settings restored");
    else toast.error(result.payload || "Defaults could not be restored");
  };

  if (loading && !data) {
    return <p className="p-6 text-sm text-gray-500 dark:text-gray-400">Loading your settings…</p>;
  }
  if (error && !data) {
    return (
      <div className="card p-6" role="alert">
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        <button type="button" className="btn-secondary mt-3" onClick={() => dispatch(fetchSettings())}>Try again</button>
      </div>
    );
  }
  if (!form) return null;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Settings</h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Saved to your account and applied every time you sign in.
            {data.updated_at && ` Last saved ${formatDateTime(data.updated_at, data.appearance.date_format)}.`}
          </p>
        </div>
        <button type="button" className="btn-secondary" onClick={restore} disabled={saving} data-tour="settings-reset">
          Restore defaults
        </button>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        <nav className="card p-2 lg:col-span-1" aria-label="Settings sections" data-tour="settings-tabs">
          <ul className="flex gap-1 overflow-x-auto lg:flex-col">
            {TABS.map((tab) => (
              <li key={tab.id}>
                <button
                  type="button"
                  onClick={() => { setActiveTab(tab.id); setFormError(null); }}
                  aria-current={activeTab === tab.id ? "page" : undefined}
                  className={`flex w-full items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium ${activeTab === tab.id ? "bg-primary-50 text-primary-700 dark:bg-primary-900/30 dark:text-primary-300" : "text-gray-600 hover:bg-gray-50 dark:text-gray-300 dark:hover:bg-gray-700/50"}`}
                >
                  <tab.icon className="h-5 w-5" aria-hidden="true" /> {tab.name}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <form className="card space-y-5 p-6 lg:col-span-3" onSubmit={save} noValidate aria-labelledby="settings-section-title">
          <h2 id="settings-section-title" className="section-title">{TABS.find((t) => t.id === activeTab).name}</h2>

          {activeTab === "profile" && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="First name" htmlFor="first_name">
                <input id="first_name" className="input-field" required maxLength={100} value={form.profile.first_name} onChange={(e) => set("profile", "first_name", e.target.value)} />
              </Field>
              <Field label="Last name" htmlFor="last_name">
                <input id="last_name" className="input-field" required maxLength={100} value={form.profile.last_name} onChange={(e) => set("profile", "last_name", e.target.value)} />
              </Field>
              <Field label="Department" htmlFor="department">
                <input id="department" className="input-field" maxLength={100} value={form.profile.department} onChange={(e) => set("profile", "department", e.target.value)} />
              </Field>
              <Field label="Job title" htmlFor="job_title">
                <input id="job_title" className="input-field" maxLength={100} value={form.profile.job_title} onChange={(e) => set("profile", "job_title", e.target.value)} />
              </Field>
              <Field label="Phone" htmlFor="phone">
                <input id="phone" className="input-field" maxLength={20} inputMode="tel" value={form.profile.phone} onChange={(e) => set("profile", "phone", e.target.value)} />
              </Field>
              <Field label="E-mail" htmlFor="email" hint="Your sign-in e-mail cannot be changed here.">
                <input id="email" className="input-field" value={data.profile.email} readOnly aria-readonly="true" />
              </Field>
              <p className="text-xs text-gray-500 dark:text-gray-400 sm:col-span-2">Change your password on the Profile page; it asks for your current password.</p>
            </div>
          )}

          {activeTab === "appearance" && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Theme" htmlFor="theme" hint="Applied immediately after saving and on every sign-in.">
                <select id="theme" className="input-field" value={form.appearance.theme} onChange={(e) => set("appearance", "theme", e.target.value)}>
                  <option value="light">Light</option>
                  <option value="dark">Dark</option>
                </select>
              </Field>
              <Field label="Date format" htmlFor="date_format" hint="Used for dates on the Remediation, Audit Trail and Settings pages.">
                <select id="date_format" className="input-field" value={form.appearance.date_format} onChange={(e) => set("appearance", "date_format", e.target.value)}>
                  {data.options.date_formats.map((f) => <option key={f} value={f}>{f} ({DATE_FORMAT_EXAMPLES[f]})</option>)}
                </select>
              </Field>
            </div>
          )}

          {activeTab === "dashboard" && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Default organization" htmlFor="default_org" hint="Selected automatically when you sign in. Only organizations you belong to are listed.">
                <select id="default_org" className="input-field" value={form.dashboard.default_organization_id} onChange={(e) => set("dashboard", "default_organization_id", e.target.value)}>
                  <option value="">First available organization</option>
                  {organizations.map((org) => <option key={org.id} value={org.id}>{org.name}</option>)}
                </select>
              </Field>
              <Field label="Default resource view" htmlFor="default_view" hint="How the Resources page lists your VMs when it opens.">
                <select id="default_view" className="input-field" value={form.dashboard.default_view} onChange={(e) => set("dashboard", "default_view", e.target.value)}>
                  <option value="grid">Grid (cards)</option>
                  <option value="list">List (table)</option>
                </select>
              </Field>
            </div>
          )}

          {activeTab === "alerts" && (
            <div className="space-y-3">
              <p className="text-sm text-gray-600 dark:text-gray-300">
                These preferences control the in-app alerts under the bell icon in the header. E-mail, SMS and push delivery are not available in this build.
              </p>
              <Toggle id="security_alerts" label="Security alerts" description="Open threats in the current organization." checked={form.alerts.security_alerts} onChange={(v) => set("alerts", "security_alerts", v)} />
              <Field label="Minimum threat severity" htmlFor="security_severity">
                <select id="security_severity" className="input-field" disabled={!form.alerts.security_alerts} value={form.alerts.security_severity} onChange={(e) => set("alerts", "security_severity", e.target.value)}>
                  {data.options.severities.map((s) => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)} and above</option>)}
                </select>
              </Field>
              <Toggle id="cost_alerts" label="Cost alerts" description="Budgets whose spend has reached your threshold." checked={form.alerts.cost_alerts} onChange={(v) => set("alerts", "cost_alerts", v)} />
              <Field label="Cost alert threshold (% of budget)" htmlFor="cost_threshold" hint={`Between ${data.options.cost_threshold_range[0]} and ${data.options.cost_threshold_range[1]}.`}>
                <input id="cost_threshold" className="input-field" inputMode="decimal" disabled={!form.alerts.cost_alerts} value={form.alerts.cost_threshold} onChange={(e) => set("alerts", "cost_threshold", e.target.value)} />
              </Field>
              <Toggle id="compliance_alerts" label="Governance alerts" description="Open policy violations from the latest compliance check." checked={form.alerts.compliance_alerts} onChange={(v) => set("alerts", "compliance_alerts", v)} />
            </div>
          )}

          {activeTab === "security" && (
            <div className="space-y-4">
              <Field label="Sign out after inactivity (minutes)" htmlFor="session_timeout" hint={`Between ${data.options.session_timeout_range[0]} and ${data.options.session_timeout_range[1]}. Sessions also end when the 1-hour access token expires.`}>
                <input id="session_timeout" type="number" className="input-field" min={data.options.session_timeout_range[0]} max={data.options.session_timeout_range[1]} value={form.security.session_timeout} onChange={(e) => set("security", "session_timeout", e.target.value)} />
              </Field>
              <p className="rounded-lg bg-gray-50 p-3 text-xs text-gray-600 dark:bg-gray-700/40 dark:text-gray-300">
                Two-factor authentication is not available in this build. Signing out revokes your tokens immediately, and
                repeated failed sign-ins lock the account for 15 minutes.
              </p>
            </div>
          )}

          {formError && <p className="text-sm text-red-600 dark:text-red-400" role="alert">{formError}</p>}
          <div className="flex justify-end border-t border-gray-200 pt-4 dark:border-gray-700">
            <button type="submit" className="btn-primary disabled:opacity-50" disabled={saving} data-tour="settings-save">
              {saving ? "Saving…" : "Save changes"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default Settings;
