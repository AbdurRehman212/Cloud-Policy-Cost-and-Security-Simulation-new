import React, { useEffect, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import {
  BellIcon,
  RectangleGroupIcon,
  ShieldCheckIcon,
  SwatchIcon,
  UserCircleIcon,
} from "@heroicons/react/24/outline";
import toast from "react-hot-toast";

import apiClient from "../../services/api";
import { updateProfile } from "../../store/slices/authSlice";

const DEFAULT_WIDGET_ORDER = ["resources", "security", "costs", "governance", "activity"];

const SETTINGS_TABS = [
  { id: "profile", name: "Profile", icon: UserCircleIcon },
  { id: "dashboard", name: "Dashboard", icon: RectangleGroupIcon },
  { id: "appearance", name: "Appearance", icon: SwatchIcon },
  { id: "notifications", name: "Notifications", icon: BellIcon },
  { id: "security", name: "Security", icon: ShieldCheckIcon },
];

const WIDGET_LABELS = {
  resources: "Resources",
  security: "Security",
  costs: "Costs",
  governance: "Governance",
  activity: "Recent Activity",
};

const Settings = () => {
  const dispatch = useDispatch();
  const { user } = useSelector((state) => state.auth);

  const [settings, setSettings] = useState(null);
  const [profileForm, setProfileForm] = useState({
    first_name: "",
    last_name: "",
  });
  const [activeTab, setActiveTab] = useState("profile");
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const loadSettings = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await apiClient.get("/settings/");
        const payload = response?.data?.data;
        setSettings(payload);
        setProfileForm({
          first_name: payload?.user?.first_name || user?.first_name || "",
          last_name: payload?.user?.last_name || user?.last_name || "",
        });
      } catch (loadError) {
        setError(
          loadError?.response?.data?.error?.message ||
            "Unable to load your saved settings.",
        );
      } finally {
        setLoading(false);
      }
    };

    loadSettings();
  }, [user?.first_name, user?.last_name]);

  useEffect(() => {
    const theme = settings?.appearance?.theme;
    if (!theme) {
      return;
    }

    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [settings?.appearance?.theme]);

  const updateSettingsState = (updater) => {
    setSettings((current) => (typeof updater === "function" ? updater(current) : updater));
  };

  const saveSettingsSection = async (sectionKey, payload) => {
    setSavingKey(sectionKey);
    try {
      const response = await apiClient.put("/settings/", payload);
      setSettings(response?.data?.data);
      toast.success("Settings saved");
    } catch (saveError) {
      toast.error(
        saveError?.response?.data?.error?.message || "Unable to save settings",
      );
    } finally {
      setSavingKey(null);
    }
  };

  const moveWidget = (widgetKey, direction) => {
    updateSettingsState((current) => {
      const currentOrder =
        current?.dashboard?.dashboard_layout?.widget_order?.length > 0
          ? [...current.dashboard.dashboard_layout.widget_order]
          : [...DEFAULT_WIDGET_ORDER];
      const index = currentOrder.indexOf(widgetKey);
      if (index === -1) {
        return current;
      }

      const targetIndex = direction === "up" ? index - 1 : index + 1;
      if (targetIndex < 0 || targetIndex >= currentOrder.length) {
        return current;
      }

      [currentOrder[index], currentOrder[targetIndex]] = [
        currentOrder[targetIndex],
        currentOrder[index],
      ];

      return {
        ...current,
        dashboard: {
          ...current.dashboard,
          dashboard_layout: {
            ...current.dashboard.dashboard_layout,
            widget_order: currentOrder,
          },
        },
      };
    });
  };

  const toggleHiddenWidget = (widgetKey) => {
    updateSettingsState((current) => {
      const hiddenWidgets = new Set(
        current?.dashboard?.dashboard_layout?.hidden_widgets || [],
      );
      if (hiddenWidgets.has(widgetKey)) {
        hiddenWidgets.delete(widgetKey);
      } else {
        hiddenWidgets.add(widgetKey);
      }

      return {
        ...current,
        dashboard: {
          ...current.dashboard,
          dashboard_layout: {
            ...current.dashboard.dashboard_layout,
            hidden_widgets: Array.from(hiddenWidgets),
          },
        },
      };
    });
  };

  const handleProfileSave = async () => {
    setSavingKey("profile");
    try {
      const result = await dispatch(updateProfile(profileForm));
      if (result.meta.requestStatus !== "fulfilled") {
        throw new Error(result.payload || result.error?.message || "Unable to update profile");
      }
      setSettings((current) => ({
        ...current,
        user: result.payload?.user || current?.user,
      }));
      toast.success("Profile updated");
    } catch (profileError) {
      toast.error(profileError.message || "Unable to update profile");
    } finally {
      setSavingKey(null);
    }
  };

  if (loading) {
    return <div className="p-6 text-gray-600 dark:text-gray-300">Loading settings...</div>;
  }

  if (error || !settings) {
    return (
      <div className="rounded-lg border border-danger-100 bg-danger-50 px-4 py-3 text-sm text-danger-700 dark:border-danger-800 dark:bg-danger-900/20 dark:text-danger-100">
        {error || "Unable to load settings."}
      </div>
    );
  }

  const widgetOrder =
    settings.dashboard?.dashboard_layout?.widget_order?.length > 0
      ? settings.dashboard.dashboard_layout.widget_order
      : DEFAULT_WIDGET_ORDER;
  const hiddenWidgets = new Set(settings.dashboard?.dashboard_layout?.hidden_widgets || []);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Settings</h1>
      <div className="flex flex-col gap-6 lg:flex-row">
        <div className="space-y-1 lg:w-64">
          {SETTINGS_TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex w-full items-center rounded-lg px-4 py-3 text-left transition-colors ${
                activeTab === tab.id
                  ? "bg-primary-50 text-primary-600 dark:bg-primary-900/20 dark:text-primary-400"
                  : "text-gray-600 hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-gray-800"
              }`}
            >
              <tab.icon className="mr-3 h-5 w-5" />
              {tab.name}
            </button>
          ))}
        </div>

        <div className="flex-1">
          {activeTab === "profile" && (
            <div className="card space-y-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Profile</h2>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                    First Name
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    value={profileForm.first_name}
                    onChange={(event) =>
                      setProfileForm((current) => ({ ...current, first_name: event.target.value }))
                    }
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                    Last Name
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    value={profileForm.last_name}
                    onChange={(event) =>
                      setProfileForm((current) => ({ ...current, last_name: event.target.value }))
                    }
                  />
                </div>
                <div className="md:col-span-2">
                  <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                    Email
                  </label>
                  <input type="email" className="input-field" value={user?.email || ""} disabled />
                </div>
              </div>
              <div className="flex justify-end">
                <button
                  className="btn-primary"
                  onClick={handleProfileSave}
                  disabled={savingKey === "profile"}
                >
                  {savingKey === "profile" ? "Saving..." : "Save Profile"}
                </button>
              </div>
            </div>
          )}

          {activeTab === "dashboard" && (
            <div className="card space-y-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                Dashboard Preferences
              </h2>
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                  Default Dashboard View
                </label>
                <select
                  className="input-field"
                  value={settings.dashboard?.default_view || "overview"}
                  onChange={(event) =>
                    updateSettingsState((current) => ({
                      ...current,
                      dashboard: {
                        ...current.dashboard,
                        default_view: event.target.value,
                      },
                    }))
                  }
                >
                  <option value="overview">Overview</option>
                  <option value="grid">Grid</option>
                  <option value="list">List</option>
                  <option value="map">Map</option>
                </select>
              </div>

              <div className="space-y-3">
                <p className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  Widget Order and Visibility
                </p>
                {widgetOrder.map((widgetKey, index) => (
                  <div
                    key={widgetKey}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-gray-50 px-4 py-3 dark:bg-gray-800/60"
                  >
                    <div>
                      <p className="font-medium text-gray-900 dark:text-white">
                        {WIDGET_LABELS[widgetKey] || widgetKey}
                      </p>
                      <p className="text-sm text-gray-500 dark:text-gray-400">
                        Position {index + 1} {hiddenWidgets.has(widgetKey) ? "• hidden" : "• visible"}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        className="btn-secondary px-3 py-1 text-sm"
                        onClick={() => moveWidget(widgetKey, "up")}
                        disabled={index === 0}
                      >
                        Up
                      </button>
                      <button
                        type="button"
                        className="btn-secondary px-3 py-1 text-sm"
                        onClick={() => moveWidget(widgetKey, "down")}
                        disabled={index === widgetOrder.length - 1}
                      >
                        Down
                      </button>
                      <button
                        type="button"
                        className="btn-secondary px-3 py-1 text-sm"
                        onClick={() => toggleHiddenWidget(widgetKey)}
                      >
                        {hiddenWidgets.has(widgetKey) ? "Show" : "Hide"}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
              <div className="flex justify-end">
                <button
                  className="btn-primary"
                  onClick={() =>
                    saveSettingsSection("dashboard", {
                      dashboard: settings.dashboard,
                    })
                  }
                  disabled={savingKey === "dashboard"}
                >
                  {savingKey === "dashboard" ? "Saving..." : "Save Dashboard Preferences"}
                </button>
              </div>
            </div>
          )}

          {activeTab === "appearance" && (
            <div className="card space-y-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Appearance</h2>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                    Theme
                  </label>
                  <select
                    className="input-field"
                    value={settings.appearance?.theme || "light"}
                    onChange={(event) =>
                      updateSettingsState((current) => ({
                        ...current,
                        appearance: {
                          ...current.appearance,
                          theme: event.target.value,
                        },
                      }))
                    }
                  >
                    <option value="light">Light</option>
                    <option value="dark">Dark</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                    Timezone
                  </label>
                  <select
                    className="input-field"
                    value={settings.appearance?.timezone || "UTC"}
                    onChange={(event) =>
                      updateSettingsState((current) => ({
                        ...current,
                        appearance: {
                          ...current.appearance,
                          timezone: event.target.value,
                        },
                      }))
                    }
                  >
                    <option value="UTC">UTC</option>
                    <option value="America/New_York">Eastern Time</option>
                    <option value="America/Los_Angeles">Pacific Time</option>
                    <option value="Europe/London">London</option>
                    <option value="Asia/Karachi">Karachi</option>
                  </select>
                </div>
              </div>
              <div className="flex justify-end">
                <button
                  className="btn-primary"
                  onClick={() =>
                    saveSettingsSection("appearance", {
                      appearance: settings.appearance,
                    })
                  }
                  disabled={savingKey === "appearance"}
                >
                  {savingKey === "appearance" ? "Saving..." : "Save Appearance"}
                </button>
              </div>
            </div>
          )}

          {activeTab === "notifications" && (
            <div className="card space-y-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                Notification Preferences
              </h2>
              <div className="space-y-4">
                {[
                  ["email", "Email Notifications", "Receive notification emails"],
                  ["push", "Push Notifications", "Receive in-app notification prompts"],
                  ["sms", "SMS Notifications", "Receive SMS notifications if support is added later"],
                ].map(([key, label, description]) => (
                  <div
                    key={key}
                    className="flex items-center justify-between rounded-lg bg-gray-50 p-4 dark:bg-gray-800/60"
                  >
                    <div>
                      <p className="font-medium text-gray-900 dark:text-white">{label}</p>
                      <p className="text-sm text-gray-500 dark:text-gray-400">{description}</p>
                    </div>
                    <input
                      type="checkbox"
                      className="h-5 w-5 rounded text-primary-600"
                      checked={Boolean(settings.notifications?.[key])}
                      onChange={(event) =>
                        updateSettingsState((current) => ({
                          ...current,
                          notifications: {
                            ...current.notifications,
                            [key]: event.target.checked,
                          },
                        }))
                      }
                    />
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {[
                  ["cost_alerts", "Cost Alerts"],
                  ["security_alerts", "Security Alerts"],
                  ["compliance_alerts", "Compliance Alerts"],
                  ["maintenance_notifications", "Maintenance Notices"],
                  ["feature_announcements", "Feature Announcements"],
                  ["email_cost_alerts", "Email Cost Alerts"],
                  ["email_security_alerts", "Email Security Alerts"],
                  ["in_app_cost_alerts", "In-app Cost Alerts"],
                  ["in_app_security_alerts", "In-app Security Alerts"],
                ].map(([key, label]) => (
                  <label
                    key={key}
                    className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3 dark:bg-gray-800/60"
                  >
                    <span className="text-sm font-medium text-gray-900 dark:text-white">{label}</span>
                    <input
                      type="checkbox"
                      className="h-5 w-5 rounded text-primary-600"
                      checked={Boolean(settings.notifications?.preferences?.[key])}
                      onChange={(event) =>
                        updateSettingsState((current) => ({
                          ...current,
                          notifications: {
                            ...current.notifications,
                            preferences: {
                              ...current.notifications.preferences,
                              [key]: event.target.checked,
                            },
                          },
                        }))
                      }
                    />
                  </label>
                ))}
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700 dark:text-gray-300">
                  Cost Alert Threshold (%)
                </label>
                <input
                  type="range"
                  min="50"
                  max="100"
                  className="w-full"
                  value={settings.notifications?.preferences?.cost_threshold || 80}
                  onChange={(event) =>
                    updateSettingsState((current) => ({
                      ...current,
                      notifications: {
                        ...current.notifications,
                        preferences: {
                          ...current.notifications.preferences,
                          cost_threshold: Number(event.target.value),
                        },
                      },
                    }))
                  }
                />
                <div className="mt-1 flex justify-between text-xs text-gray-500">
                  <span>50%</span>
                  <span>{settings.notifications?.preferences?.cost_threshold || 80}%</span>
                  <span>100%</span>
                </div>
              </div>
              <div className="flex justify-end">
                <button
                  className="btn-primary"
                  onClick={() =>
                    saveSettingsSection("notifications", {
                      notifications: settings.notifications,
                    })
                  }
                  disabled={savingKey === "notifications"}
                >
                  {savingKey === "notifications" ? "Saving..." : "Save Notifications"}
                </button>
              </div>
            </div>
          )}

          {activeTab === "security" && (
            <div className="card space-y-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Security</h2>
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-800/60">
                <p className="font-medium text-gray-900 dark:text-white">
                  Two-Factor Authentication
                </p>
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                  Two-factor authentication is not enabled in this build. No recovery codes or OTP enrollment flow are available.
                </p>
              </div>

              <div className="space-y-4">
                <label className="flex items-center justify-between rounded-lg bg-gray-50 p-4 dark:bg-gray-800/60">
                  <div>
                    <p className="font-medium text-gray-900 dark:text-white">Login Notifications</p>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      Notify me when a new login is detected.
                    </p>
                  </div>
                  <input
                    type="checkbox"
                    className="h-5 w-5 rounded text-primary-600"
                    checked={Boolean(settings.security?.login_notifications)}
                    onChange={(event) =>
                      updateSettingsState((current) => ({
                        ...current,
                        security: {
                          ...current.security,
                          login_notifications: event.target.checked,
                        },
                      }))
                    }
                  />
                </label>

                <label className="flex items-center justify-between rounded-lg bg-gray-50 p-4 dark:bg-gray-800/60">
                  <div>
                    <p className="font-medium text-gray-900 dark:text-white">
                      Suspicious Activity Alerts
                    </p>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      Notify me about suspicious account activity.
                    </p>
                  </div>
                  <input
                    type="checkbox"
                    className="h-5 w-5 rounded text-primary-600"
                    checked={Boolean(settings.security?.suspicious_activity_alerts)}
                    onChange={(event) =>
                      updateSettingsState((current) => ({
                        ...current,
                        security: {
                          ...current.security,
                          suspicious_activity_alerts: event.target.checked,
                        },
                      }))
                    }
                  />
                </label>

                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                    Session Timeout
                  </label>
                  <select
                    className="input-field w-48"
                    value={settings.security?.session_timeout || 30}
                    onChange={(event) =>
                      updateSettingsState((current) => ({
                        ...current,
                        security: {
                          ...current.security,
                          session_timeout: Number(event.target.value),
                        },
                      }))
                    }
                  >
                    <option value={15}>15 min</option>
                    <option value={30}>30 min</option>
                    <option value={60}>1 hour</option>
                    <option value={120}>2 hours</option>
                  </select>
                </div>
              </div>
              <div className="flex justify-end">
                <button
                  className="btn-primary"
                  onClick={() =>
                    saveSettingsSection("security", {
                      security: settings.security,
                    })
                  }
                  disabled={savingKey === "security"}
                >
                  {savingKey === "security" ? "Saving..." : "Save Security Settings"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Settings;
